/*
 * CTFLab 受控 SPICE 图形客户端。
 *
 * 这个小客户端只接收运行器传入的固定 --uri 参数，不接受 QEMU 参数；关键的
 * agent 和绝对鼠标模式就绪后才开启 resize-guest，并合并拖动过程的连续尺寸事件，
 * 使 spice-gtk 向来宾发送最终的 monitors config。剪贴板必须由运行器显式传入
 * --clipboard 才开启；USB 自动重定向与文件拖入始终关闭。
 *
 * 窗口几何（尺寸/全屏）经 --state-file 持久化，--geometry 显式覆盖记忆值。
 * 按下未释放的按键在失焦/抓取断裂/退出时统一向来宾补发 release；分辨率切换
 * 过渡期冻结最后一帧并拦截指针输入，避免旧画面与新坐标混用。
 *
 * 项目代码按 MIT 发布；编译时动态链接系统中的 spice-gtk/GTK，随 App 打包时
 * 由构建器收集并校验对应的第三方动态库与许可证文本。
 */

#include <gtk/gtk.h>
#include <spice-client-gtk.h>
#if defined(__APPLE__)
#include <spice/vd_agent.h>
#endif

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <signal.h>
#include <unistd.h>
#include <fcntl.h>
#include <glib-unix.h>
#if defined(__APPLE__)
#include <sys/sysctl.h>
#include <sys/proc.h>
#include <objc/runtime.h>
#include <objc/message.h>
#endif

/* pid_t 不经过 GINT_TO_POINTER 缩窄；客户端生命周期由这个上下文统一管理。 */
typedef struct {
    pid_t pid;
    guint source_id;
    gboolean quitting;
} QemuWatchContext;

typedef struct {
    QemuWatchContext *qemu;
    SpiceSession *session;
    gboolean quitting;
} SessionContext;

/*
 * 后台线程只访问 pasteboard 与锁内缓存；SPICE 操作由 GTK 主线程固定 timer 执行。
 * 待发送内容最多一份。退出先移除 timer/信号，再取消子进程通信，确认线程完成
 * 后清理状态。pbpaste/pbcopy 都可取消，数据承诺不阻塞 GTK 主循环。
 */
#if defined(__APPLE__)
#ifndef CTFLAB_PBPASTE
#define CTFLAB_PBPASTE "/usr/bin/pbpaste"
#endif
#ifndef CTFLAB_PBCOPY
#define CTFLAB_PBCOPY "/usr/bin/pbcopy"
#endif

typedef struct {
    GMutex lock;
    GCond cond;
    gboolean initialized, shutdown, thread_done;
    GCancellable *cancel;
    GThread *thread;
    guint dispatch_timer_id;       /* 仅 GTK 主线程登记和移除 */
    guint64 guest_sequence;        /* 来宾写入后丢弃此前开始的宿主采样 */
    SpiceMainChannel *main_channel; /* 持有引用，仅 GTK 主线程访问 */
    GBytes *guest_write, *guest_text, *pending_host, *host_text;
} HostClipboardShared;
static HostClipboardShared host_clipboard_shared;

/* 可取消通信；取消后终止并回收直接子进程，无 shell 或 pasteboard 孤儿进程。 */
static gboolean clipboard_transfer(const gchar *const *argv, GBytes *input,
                                    GBytes **output, GCancellable *cancel)
{
    GSubprocessFlags flags = G_SUBPROCESS_FLAGS_STDERR_SILENCE;
    flags |= input != NULL ? (G_SUBPROCESS_FLAGS_STDIN_PIPE | G_SUBPROCESS_FLAGS_STDOUT_SILENCE)
                           : G_SUBPROCESS_FLAGS_STDOUT_PIPE;
    GError *error = NULL;
    GSubprocess *process = g_subprocess_newv(argv, flags, &error);
    if (process == NULL) {
        g_clear_error(&error);
        return FALSE;
    }
    gboolean ok = g_subprocess_communicate(process, input, cancel, output, NULL, &error);
    if (!ok) g_subprocess_force_exit(process);
    g_subprocess_wait(process, NULL, NULL);
    ok = ok && g_subprocess_get_successful(process);
    g_clear_error(&error);
    g_object_unref(process);
    return ok;
}

static GBytes *read_host_pasteboard(GCancellable *cancel)
{
    const gchar *argv[] = {CTFLAB_PBPASTE, NULL};
    GBytes *text = NULL;
    if (!clipboard_transfer(argv, NULL, &text, cancel))
        g_clear_pointer(&text, g_bytes_unref);
    return text;
}
static gboolean write_host_pasteboard(GBytes *text, GCancellable *cancel)
{
    const gchar *argv[] = {CTFLAB_PBCOPY, NULL};
    return clipboard_transfer(argv, text, NULL, cancel);
}

/* 所有通道访问都在 GTK 主线程；agent 未就绪时不消费待发缓存。 */
static gboolean host_clipboard_dispatch(gpointer user_data)
{
    HostClipboardShared *shared = user_data;
    g_mutex_lock(&shared->lock);
    gboolean active = !shared->shutdown && shared->pending_host != NULL;
    g_mutex_unlock(&shared->lock);
    if (!active || shared->main_channel == NULL) return G_SOURCE_CONTINUE;
    gboolean connected = FALSE;
    g_object_get(shared->main_channel, "agent-connected", &connected, NULL);
    if (!connected || !spice_main_channel_agent_test_capability(
            shared->main_channel, VD_AGENT_CAP_CLIPBOARD_BY_DEMAND))
        return G_SOURCE_CONTINUE;
    g_mutex_lock(&shared->lock);
    GBytes *text = shared->pending_host;
    shared->pending_host = NULL;
    if (text != NULL) {
        g_clear_pointer(&shared->host_text, g_bytes_unref);
        shared->host_text = g_bytes_ref(text);
    }
    g_mutex_unlock(&shared->lock);
    if (text != NULL) {
        gsize length = 0;
        const guchar *data = g_bytes_get_data(text, &length);
        guint32 utf8 = VD_AGENT_CLIPBOARD_UTF8_TEXT;
        spice_main_channel_clipboard_selection_grab(shared->main_channel,
            VD_AGENT_CLIPBOARD_SELECTION_CLIPBOARD, &utf8, 1);
        spice_main_channel_clipboard_selection_notify(shared->main_channel,
            VD_AGENT_CLIPBOARD_SELECTION_CLIPBOARD, utf8, data, length);
        fprintf(stderr, "CTFLAB_SPICE_STATE clipboard-h2g bytes=%zu\n", length);
        g_bytes_unref(text);
    }
    return G_SOURCE_CONTINUE;
}

static gpointer host_clipboard_thread(gpointer user_data)
{
    HostClipboardShared *shared = user_data;
    GBytes *candidate = NULL, *last_seen = NULL;
    for (;;) {
        g_mutex_lock(&shared->lock);
        if (!shared->shutdown && shared->guest_write == NULL)
            g_cond_wait_until(&shared->cond, &shared->lock,
                             g_get_monotonic_time() + G_USEC_PER_SEC / 2);
        gboolean shutdown = shared->shutdown;
        GBytes *write = shared->guest_write;
        shared->guest_write = NULL;
        g_mutex_unlock(&shared->lock);
        if (shutdown) {
            g_clear_pointer(&write, g_bytes_unref);
            break;
        }
        if (write != NULL) {
            if (write_host_pasteboard(write, shared->cancel))
                fprintf(stderr, "CTFLAB_SPICE_STATE clipboard-g2h bytes=%zu\n",
                        g_bytes_get_size(write));
            g_bytes_unref(write);
            g_clear_pointer(&candidate, g_bytes_unref);
            g_clear_pointer(&last_seen, g_bytes_unref);
        }
        g_mutex_lock(&shared->lock);
        guint64 guest_sequence = shared->guest_sequence;
        g_mutex_unlock(&shared->lock);
        GBytes *text = read_host_pasteboard(shared->cancel);
        if (text == NULL) continue;
        g_mutex_lock(&shared->lock);
        gboolean superseded = shared->guest_sequence != guest_sequence;
        g_mutex_unlock(&shared->lock);
        if (superseded) {
            g_bytes_unref(text);
            g_clear_pointer(&candidate, g_bytes_unref);
            g_clear_pointer(&last_seen, g_bytes_unref);
            continue;
        }
        if (last_seen != NULL && g_bytes_equal(text, last_seen)) {
            g_bytes_unref(text);
            continue;
        }
        if (candidate == NULL || !g_bytes_equal(text, candidate)) {
            g_clear_pointer(&candidate, g_bytes_unref);
            candidate = text;
            continue;
        }
        g_bytes_unref(text);
        /* 连续两次相同才发布；来宾写入回声不回推。 */
        g_mutex_lock(&shared->lock);
        if (!shared->shutdown && shared->guest_sequence == guest_sequence &&
            (shared->guest_text == NULL || !g_bytes_equal(candidate, shared->guest_text))) {
            g_clear_pointer(&shared->pending_host, g_bytes_unref);
            shared->pending_host = g_bytes_ref(candidate);
            g_clear_pointer(&shared->guest_text, g_bytes_unref);
        }
        g_mutex_unlock(&shared->lock);
        g_clear_pointer(&last_seen, g_bytes_unref);
        last_seen = candidate;
        candidate = NULL;
    }
    g_clear_pointer(&candidate, g_bytes_unref);
    g_clear_pointer(&last_seen, g_bytes_unref);
    g_mutex_lock(&shared->lock);
    shared->thread_done = TRUE;
    g_cond_broadcast(&shared->cond);
    g_mutex_unlock(&shared->lock);
    return NULL;
}

/* 信号回调仅在 GTK 主线程执行；退出先断开信号，再销毁锁。 */
static gboolean clipboard_accepts_work(HostClipboardShared *shared)
{
    if (!shared->initialized) return FALSE;
    g_mutex_lock(&shared->lock);
    gboolean active = !shared->shutdown;
    g_mutex_unlock(&shared->lock);
    return active;
}
static gboolean on_clipboard_guest_grab(SpiceMainChannel *channel, guint selection,
                                        guint32 *types, guint ntypes, gpointer user_data)
{
    HostClipboardShared *shared = user_data;
    if (!clipboard_accepts_work(shared)) return FALSE;
    for (guint i = 0; i < ntypes; i++) {
        if (selection == VD_AGENT_CLIPBOARD_SELECTION_CLIPBOARD &&
            types[i] == VD_AGENT_CLIPBOARD_UTF8_TEXT) {
            spice_main_channel_clipboard_selection_request(channel, selection,
                                                           VD_AGENT_CLIPBOARD_UTF8_TEXT);
            break;
        }
    }
    return TRUE;
}
static void on_clipboard_guest_data(SpiceMainChannel *channel, guint selection,
                                    guint32 type, const guchar *data, guint size,
                                    gpointer user_data)
{
    HostClipboardShared *shared = user_data;
    (void)channel;
    if (!clipboard_accepts_work(shared) ||
        selection != VD_AGENT_CLIPBOARD_SELECTION_CLIPBOARD ||
        type != VD_AGENT_CLIPBOARD_UTF8_TEXT) return;
    g_mutex_lock(&shared->lock);
    g_clear_pointer(&shared->guest_write, g_bytes_unref);
    g_clear_pointer(&shared->guest_text, g_bytes_unref);
    g_clear_pointer(&shared->pending_host, g_bytes_unref);
    shared->guest_write = g_bytes_new(data, size);
    shared->guest_text = g_bytes_ref(shared->guest_write);
    shared->guest_sequence++;
    g_cond_broadcast(&shared->cond);
    g_mutex_unlock(&shared->lock);
}
static gboolean on_clipboard_guest_request(SpiceMainChannel *channel, guint selection,
                                           guint32 type, gpointer user_data)
{
    HostClipboardShared *shared = user_data;
    if (!clipboard_accepts_work(shared) ||
        selection != VD_AGENT_CLIPBOARD_SELECTION_CLIPBOARD ||
        type != VD_AGENT_CLIPBOARD_UTF8_TEXT) return FALSE;
    g_mutex_lock(&shared->lock);
    GBytes *text = shared->host_text != NULL ? g_bytes_ref(shared->host_text) : NULL;
    g_mutex_unlock(&shared->lock);
    if (text != NULL) {
        gsize length = 0;
        const guchar *data = g_bytes_get_data(text, &length);
        spice_main_channel_clipboard_selection_notify(channel, selection, type, data, length);
        fprintf(stderr, "CTFLAB_SPICE_STATE clipboard-request-answered bytes=%zu\n", length);
        g_bytes_unref(text);
    }
    return TRUE;
}

static void host_clipboard_start(SpiceMainChannel *channel)
{
    HostClipboardShared *shared = &host_clipboard_shared;
    g_return_if_fail(!shared->initialized);
    g_mutex_init(&shared->lock);
    g_cond_init(&shared->cond);
    shared->initialized = TRUE;
    shared->shutdown = FALSE;
    shared->thread_done = FALSE;
    shared->cancel = g_cancellable_new();
    shared->main_channel = channel != NULL ? g_object_ref(channel) : NULL;
    if (channel != NULL) {
        g_signal_connect(channel, "main-clipboard-selection-grab",
                         G_CALLBACK(on_clipboard_guest_grab), shared);
        g_signal_connect(channel, "main-clipboard-selection",
                         G_CALLBACK(on_clipboard_guest_data), shared);
        g_signal_connect(channel, "main-clipboard-selection-request",
                         G_CALLBACK(on_clipboard_guest_request), shared);
    }
    shared->dispatch_timer_id = g_timeout_add(100, host_clipboard_dispatch, shared);
    shared->thread = g_thread_new("ctflab-clipboard-poll", host_clipboard_thread, shared);
}
static void host_clipboard_stop_new_work(void)
{
    HostClipboardShared *shared = &host_clipboard_shared;
    if (!shared->initialized) return;
    g_mutex_lock(&shared->lock);
    shared->shutdown = TRUE;
    g_cond_broadcast(&shared->cond);
    g_mutex_unlock(&shared->lock);
    if (shared->dispatch_timer_id != 0) {
        g_source_remove(shared->dispatch_timer_id);
        shared->dispatch_timer_id = 0;
    }
    if (shared->main_channel != NULL)
        g_signal_handlers_disconnect_by_data(shared->main_channel, shared);
    g_cancellable_cancel(shared->cancel);
}

/* thread_done 的有界等待通过后，join 只回收已完成线程；超时则保留静态状态，
 * 不销毁活跃线程的锁。外部退出 gtk_main 时也会先完整停止新工作。 */
static void host_clipboard_shutdown(void)
{
    HostClipboardShared *shared = &host_clipboard_shared;
    if (!shared->initialized) return;
    host_clipboard_stop_new_work();
    gint64 deadline = g_get_monotonic_time() + 2 * G_USEC_PER_SEC;
    g_mutex_lock(&shared->lock);
    while (!shared->thread_done) {
        if (!g_cond_wait_until(&shared->cond, &shared->lock, deadline)) break;
    }
    gboolean done = shared->thread_done;
    g_mutex_unlock(&shared->lock);
    if (!done) {
        fprintf(stderr, "CTFLAB_SPICE_STATE clipboard-thread-timeout\n");
        return;
    }
    g_thread_join(shared->thread);
    shared->thread = NULL;
    g_clear_pointer(&shared->guest_write, g_bytes_unref);
    g_clear_pointer(&shared->guest_text, g_bytes_unref);
    g_clear_pointer(&shared->pending_host, g_bytes_unref);
    g_clear_pointer(&shared->host_text, g_bytes_unref);
    g_clear_object(&shared->main_channel);
    g_clear_object(&shared->cancel);
    g_mutex_clear(&shared->lock);
    g_cond_clear(&shared->cond);
    shared->initialized = FALSE;
}
#else
static void host_clipboard_stop_new_work(void) {}
static void host_clipboard_shutdown(void) {}
#endif /* defined(__APPLE__) */

/*
 * 输入跟踪：key snooper 在事件进入控件树之前记录已按下的 keyval；窗口失焦、
 * 抓取断裂或客户端退出时统一向来宾补发 release，避免 Cmd-Tab 切走时
 * “修饰键卡住”。集合只在 GTK 主线程访问，不需要锁。
 */
#define CTFLAB_MAX_PRESSED_KEYS 32

typedef struct {
    GtkWidget *window;
    gboolean fullscreen;
    guint snooper_id;
    gint windowed_width, windowed_height; /* 进入全屏前的窗口尺寸 */
    guint pressed[CTFLAB_MAX_PRESSED_KEYS];
    gint pressed_count;
    guint host_release_keys[CTFLAB_MAX_PRESSED_KEYS]; /* 已由宿主处理的按键不向来宾漏发 release */
    gint host_release_count;
    SpiceDisplay *display; /* 弱引用，与主线程同生命周期 */
    SpiceInputsChannel *inputs; /* 主线程持有，客户端退出时释放 */
    guint held_buttons; /* 只跟踪真实按下的左/中/右键，不合成点击 */
    gboolean reset_shortcut_held;
    guint reset_source_id;
    guint reset_next_scancode;
} InputContext;

static InputContext *g_input_context = NULL;

/* E2E 测量用：日志行尾附单调毫秒，不改变既有断言子串。 */
static unsigned long long mono_ms(void)
{
    return (unsigned long long)g_get_monotonic_time() / 1000;
}

static void input_track_key(InputContext *context, guint keyval, gboolean press)
{
    for (gint index = 0; index < context->pressed_count; index++) {
        if (context->pressed[index] == keyval) {
            if (!press) {
                context->pressed[index] = context->pressed[context->pressed_count - 1];
                context->pressed_count--;
            }
            return;
        }
    }
    if (press && context->pressed_count < CTFLAB_MAX_PRESSED_KEYS) {
        context->pressed[context->pressed_count++] = keyval;
    }
}

/* display 为 NULL 时只清空集合不发送，供单元测试与未映射窗口路径使用。 */
static void input_release_pressed_keys(InputContext *context)
{
    guint held = context->held_buttons;
    context->held_buttons = 0;
    if (context->inputs != NULL) {
        for (guint button = 1; button <= 3; button++) {
            if (held & (1u << button)) {
                gint spice_button = button == 2 ? 3 : button == 3 ? 2 : 1;
                spice_inputs_channel_button_release(context->inputs, spice_button, 0);
            }
        }
    }
    if (context->pressed_count <= 0) {
        return;
    }
    gint count = context->pressed_count;
    context->pressed_count = 0;
    if (context->display != NULL && SPICE_IS_DISPLAY(context->display)) {
        spice_display_send_keys(context->display, context->pressed, count,
                                SPICE_DISPLAY_KEY_EVENT_RELEASE);
        fprintf(stderr, "CTFLAB_SPICE_STATE keys-released count=%d\n", count);
        fflush(stderr);
    }
}

/* 合成 Unicode 事件的 keyval 可能与实际发给来宾的硬件扫描码不一致，
 * 旧客户端的集合也不会跨重连保存。显式恢复时补发基础 Set-1 键的 release，
 * 不发送 press、不改变 Caps/Num Lock 状态，不在普通点击/失焦时遍历。 */
static void input_cancel_scancode_reset(InputContext *context)
{
    if (context->reset_source_id != 0) {
        g_source_remove(context->reset_source_id);
        context->reset_source_id = 0;
    }
}

static gboolean input_reset_scancode_tick(gpointer user_data)
{
    InputContext *context = user_data;
    if (context->inputs == NULL || context->reset_next_scancode > 0x58) {
        context->reset_source_id = 0;
        return G_SOURCE_REMOVE;
    }
    guint code = context->reset_next_scancode++;
    if (code != 0x1e) spice_inputs_channel_key_release(context->inputs, code);
    if (context->reset_next_scancode > 0x58) {
        context->reset_source_id = 0;
        fprintf(stderr, "CTFLAB_SPICE_STATE input-reset paced-base-keys-complete=88\n");
        fflush(stderr);
        return G_SOURCE_REMOVE;
    }
    return G_SOURCE_CONTINUE;
}

static void input_reset_untracked_keys(InputContext *context)
{
    input_cancel_scancode_reset(context);
    input_release_pressed_keys(context);
    if (context->inputs == NULL) return;
    /* QEMU USB HID 的队列仅 16 项，不能把 88 个 release 一次塞入。
     * 优先清理此次观察到的 a；其余每 30 ms 一项，不阻塞 GTK。 */
    spice_inputs_channel_key_release(context->inputs, 0x1e);
    context->reset_next_scancode = 1;
    context->reset_source_id = g_timeout_add(30, input_reset_scancode_tick, context);
    fprintf(stderr, "CTFLAB_SPICE_STATE input-reset paced-base-keys-scheduled=88\n");
    fflush(stderr);
}

static void on_inputs_recovery_event(SpiceChannel *channel, gint event, gpointer user_data)
{
    InputContext *context = user_data;
    if (SPICE_INPUTS_CHANNEL(channel) != context->inputs) return;
    if (event == SPICE_CHANNEL_OPENED) {
        input_reset_untracked_keys(context);
    } else {
        input_cancel_scancode_reset(context);
    }
}

/*
 * macOS 肌肉记忆桥接：窗口聚焦时 Command+C/V/X/A/Z 映射为来宾的
 * Ctrl+C/V/X/A/Z（spice 协议本身不认识 Command 修饰键，来宾终端与编辑器
 * 只响应 Ctrl 组合）。消费原事件，改用 press+release 组合注入，不进入
 * 按键跟踪集合。
 */
static void input_send_mac_shortcut(InputContext *context, guint letter)
{
    if (context->display == NULL || !SPICE_IS_DISPLAY(context->display)) {
        return;
    }
    guint combo[] = { GDK_KEY_Control_L, letter };
    spice_display_send_keys(context->display, combo, G_N_ELEMENTS(combo),
                            SPICE_DISPLAY_KEY_EVENT_PRESS);
    spice_display_send_keys(context->display, combo, G_N_ELEMENTS(combo),
                            SPICE_DISPLAY_KEY_EVENT_RELEASE);
    fprintf(stderr, "CTFLAB_SPICE_STATE mac-shortcut ctrl+%c\n",
            (gchar)g_unichar_tolower(letter));
    fflush(stderr);
}

static void request_client_quit(SessionContext *context, SpiceSession *session)
{
    if (context->quitting) {
        return;
    }
    context->quitting = TRUE;
    /* 先补发未释放按键，再阻止剪贴板的新回调与通道推送，然后断开 SPICE，
     * 最后退出主循环；窗口关闭/QEMU 退出/SPICE 断开三条路径都经过这里。 */
    if (g_input_context != NULL) {
        input_release_pressed_keys(g_input_context);
    }
    host_clipboard_stop_new_work();
    fprintf(stderr, "CTFLAB_SPICE_STATE quit-requested\n");
    fflush(stderr);
    spice_session_disconnect(session);
    /* 断连可能晚于嵌套 GTK 循环结束；不对不存在的循环调用 quit。 */
    if (gtk_main_level() > 0) {
        gtk_main_quit();
    }
}

/*
 * 运行器停止节点时先向客户端发 SIGTERM。默认终止不走清理路径，窗口记忆
 * 丢失、按键不释放、退出码非 0；这里把 SIGTERM/SIGINT/SIGHUP 转成主循环
 * 上的优雅退出。信号处理器只向非阻塞管道写入；GLib 调度和清理留在主线程。
 */
static SessionContext *g_session_context = NULL;
static int quit_pipe[2] = {-1, -1};
static guint quit_pipe_source = 0;
static volatile sig_atomic_t quit_signal_pending = 0;
/* 先注册兜底，再接受终止通知，避免初始化时触发默认 SIGALRM。 */
static const int quit_signals[] = {SIGALRM, SIGTERM, SIGINT, SIGHUP};
static struct sigaction old_quit_actions[4];

static gboolean quit_from_signal(gpointer user_data)
{
    (void)user_data;
    if (g_session_context != NULL) {
        request_client_quit(g_session_context, g_session_context->session);
    }
    return G_SOURCE_REMOVE;
}

/*
 * 兜底退出：SIGTERM 后主循环偶发未完成清理（具体阻塞点尚未证实），
 * 优雅路径跑不完就被运行器 SIGKILL，日志与窗口
 * 记忆全丢。alarm 到期说明主循环 4 秒内没有处理优雅退出——用 write(2) 记
 * 一行（异步信号安全）后 _exit，保证有界退出并留下证据。
 */
static void on_quit_alarm(int signum)
{
    (void)signum;
    static const char line[] = "CTFLAB_SPICE_STATE quit-forced-timeout\n";
    (void)!write(STDERR_FILENO, line, sizeof(line) - 1);
    _exit(0);
}

static void on_terminate_signal(int signum)
{
    (void)signum;
    int saved_errno = errno;
    if (!quit_signal_pending) {
        quit_signal_pending = 1;
        alarm(4);
        const char byte = 1;
        (void)!write(quit_pipe[1], &byte, 1);
    }
    errno = saved_errno;
}

static gboolean quit_pipe_ready(gint fd, GIOCondition condition, gpointer data)
{
    (void)condition;
    char bytes[32];
    while (read(fd, bytes, sizeof(bytes)) > 0) {}
    quit_from_signal(data);
    return G_SOURCE_CONTINUE;
}

static void install_quit_signals(void)
{
    if (pipe(quit_pipe) != 0) {
        g_error("无法创建退出通知管道");
    }
    for (int i = 0; i < 2; i++) {
        if (fcntl(quit_pipe[i], F_SETFL, O_NONBLOCK) < 0 ||
            fcntl(quit_pipe[i], F_SETFD, FD_CLOEXEC) < 0) {
            g_error("无法设置退出通知管道");
        }
    }
    quit_signal_pending = 0;
    quit_pipe_source = g_unix_fd_add(quit_pipe[0], G_IO_IN, quit_pipe_ready, NULL);
    struct sigaction action = {0};
    sigemptyset(&action.sa_mask);
    sigaddset(&action.sa_mask, SIGTERM);
    sigaddset(&action.sa_mask, SIGINT);
    sigaddset(&action.sa_mask, SIGHUP);
    for (guint i = 0; i < G_N_ELEMENTS(quit_signals); i++) {
        action.sa_handler = quit_signals[i] == SIGALRM ? on_quit_alarm : on_terminate_signal;
        if (sigaction(quit_signals[i], &action, &old_quit_actions[i]) != 0) {
            g_error("无法注册退出信号");
        }
    }
}

static void remove_quit_signals(void)
{
    sigset_t block, previous;
    sigemptyset(&block);
    for (guint i = 0; i < G_N_ELEMENTS(quit_signals); i++) {
        sigaddset(&block, quit_signals[i]);
    }
    sigprocmask(SIG_BLOCK, &block, &previous);
    alarm(0);
    if (quit_pipe_source) {
        g_source_remove(quit_pipe_source);
        quit_pipe_source = 0;
    }
    for (guint i = 0; i < G_N_ELEMENTS(quit_signals); i++) {
        sigaction(quit_signals[i], &old_quit_actions[i], NULL);
    }
    close(quit_pipe[0]);
    close(quit_pipe[1]);
    quit_pipe[0] = quit_pipe[1] = -1;
    quit_signal_pending = 0;
    sigprocmask(SIG_SETMASK, &previous, NULL);
}

/*
 * 全屏切换：Shift+F11 由客户端接管并转换为主窗口全屏，不再转发给来宾；
 * 来宾内部的裸 F11 不受影响。spice-gtk 自带的同名热键依赖 accel group 在
 * 本窗口中的注册时机，SpiceDisplay 先行消费按键时不可靠，这里用 key
 * snooper 在事件进入控件树之前处理。snooper 同时维护已按下键集合。
 */

/*
 * quartz 后端对 gtk_window_fullscreen 的支持不可靠（状态位不翻转），因此这里
 * 用"保留标题栏 + 显示器工作区"实现展开模式；不置顶、不覆盖菜单栏或 Dock。
 * Quartz 运行中切换 decorated 会令绘制原点与输入原点分叉，禁止切换装饰。
 * 这不是 macOS 原生独立 Space 全屏；Shift+F11 在两种状态间切换。
 * 全屏贴合窗口当前所在显示器（而非固定主显示器）；进入时记录窗口尺寸，
 * 退出时恢复，替代原先硬编码的 1000x700。
 */
static void set_fullscreen_layout(GtkWidget *window, gboolean enter, InputContext *context)
{
    GdkDisplay *display = gdk_display_get_default();
    GdkMonitor *monitor = NULL;
    GdkRectangle geometry = {0};
    GdkWindow *gdk_window = gtk_widget_get_window(window);
    if (gdk_window != NULL) {
        monitor = gdk_display_get_monitor_at_window(display, gdk_window);
    }
    if (monitor == NULL) {
        monitor = gdk_display_get_primary_monitor(display);
    }
    if (monitor == NULL) {
        monitor = gdk_display_get_monitor(display, 0);
    }
    if (monitor == NULL) {
        return;
    }
    gdk_monitor_get_workarea(monitor, &geometry);
    if (geometry.width <= 0 || geometry.height <= 0) {
        /* 不以整屏坐标猜测工作区，避免覆盖系统导航区域。 */
        return;
    }
    if (enter) {
        if (context != NULL && context->windowed_width <= 0 && context->windowed_height <= 0) {
            gtk_window_get_size(GTK_WINDOW(window), &context->windowed_width,
                                &context->windowed_height);
        }
        /* 工作区是外框尺寸，GTK resize 接受内容尺寸。按实际框架测量标题栏，
         * 不硬编码 Retina 比例或标题栏高度，也不移动 SPICE 输入坐标。 */
        gint frame_extra_w = 0, frame_extra_h = 0;
        if (gdk_window != NULL) {
            GdkRectangle frame = {0};
            gdk_window_get_frame_extents(gdk_window, &frame);
            frame_extra_w = MAX(0, frame.width - gdk_window_get_width(gdk_window));
            frame_extra_h = MAX(0, frame.height - gdk_window_get_height(gdk_window));
        }
        gint content_w = MAX(1, geometry.width - frame_extra_w);
        gint content_h = MAX(1, geometry.height - frame_extra_h);
        gtk_window_resize(GTK_WINDOW(window), content_w, content_h);
        gtk_window_move(GTK_WINDOW(window), geometry.x, geometry.y);
        gtk_window_set_keep_above(GTK_WINDOW(window), FALSE);
        fprintf(stderr, "CTFLAB_SPICE_STATE fullscreen=on %dx%d+%d+%d area=workarea keep-above=off t=%llums\n",
                geometry.width, geometry.height, geometry.x, geometry.y, mono_ms());
    } else {
        gtk_window_set_keep_above(GTK_WINDOW(window), FALSE);
        gint width = 1000, height = 700;
        if (context != NULL && context->windowed_width > 0 && context->windowed_height > 0) {
            width = context->windowed_width;
            height = context->windowed_height;
        }
        gtk_window_resize(GTK_WINDOW(window), width, height);
        gtk_window_move(GTK_WINDOW(window), 0, 33);
        fprintf(stderr, "CTFLAB_SPICE_STATE fullscreen=off restore=%dx%d t=%llums\n", width, height, mono_ms());
    }
    /* 沿用 GTK 的正常布局路径，绘制与输入共享同一个内容区原点。 */
    gtk_widget_queue_resize(window);
    fflush(stderr);
}

static gboolean apply_start_fullscreen(gpointer user_data)
{
    InputContext *context = (InputContext *)user_data;
    if (gtk_widget_get_window(context->window) != NULL) {
        context->fullscreen = TRUE;
        set_fullscreen_layout(context->window, TRUE, context);
    }
    return G_SOURCE_REMOVE;
}

/* 全屏中显示器几何变化（改分辨率/Retina 切换/外接屏）时重新贴合当前显示器。 */
static void on_screen_geometry_changed(GdkScreen *screen, gpointer user_data)
{
    (void)screen;
    InputContext *context = (InputContext *)user_data;
    if (context->fullscreen) {
        set_fullscreen_layout(context->window, TRUE, context);
    }
}

static gboolean input_key_snooper(GtkWidget *grab_widget, GdkEventKey *event,
                                  gpointer user_data)
{
    InputContext *context = (InputContext *)user_data;
    (void)grab_widget;
    if (event->keyval == GDK_KEY_F12 && ((event->state & GDK_SHIFT_MASK) != 0 || context->reset_shortcut_held)) {
        if (event->type == GDK_KEY_PRESS) {
            context->reset_shortcut_held = TRUE;
            input_reset_untracked_keys(context);
            if (context->display != NULL) spice_display_mouse_ungrab(context->display);
            fprintf(stderr, "CTFLAB_SPICE_STATE input-reset reason=user-shortcut\n");
            fflush(stderr);
        } else context->reset_shortcut_held = FALSE;
        return TRUE;
    }
    /* 只观察系统切换相关键，不记录普通文字/密码键，也不改变转发行为。 */
    if (g_strcmp0(g_getenv("CTFLAB_TRACE_DISPLAY_RECOVERY"), "1") == 0) {
        const char *category = NULL;
        switch (event->keyval) {
        case GDK_KEY_Tab: case GDK_KEY_ISO_Left_Tab: category = "tab"; break;
        case GDK_KEY_Escape: category = "escape"; break;
        case GDK_KEY_Meta_L: case GDK_KEY_Meta_R:
        case GDK_KEY_Super_L: case GDK_KEY_Super_R: category = "command"; break;
        case GDK_KEY_Control_L: case GDK_KEY_Control_R: category = "control"; break;
        case GDK_KEY_Alt_L: case GDK_KEY_Alt_R: category = "alt"; break;
        default: break;
        }
        if (category != NULL) {
            fprintf(stderr, "CTFLAB_SPICE_STATE recovery-key=%s phase=%s t=%llums\n",
                    category, event->type == GDK_KEY_PRESS ? "press" : "release",
                    mono_ms());
            fflush(stderr);
        }
    }
    if (event->type == GDK_KEY_PRESS && event->keyval == GDK_KEY_F11 &&
        (event->state & GDK_SHIFT_MASK) != 0 && context->window != NULL) {
        /* 被客户端消费的按键不转发来宾，也不进入跟踪集合。 */
        context->fullscreen = !context->fullscreen;
        set_fullscreen_layout(context->window, context->fullscreen, context);
        return TRUE;
    }
#if defined(__APPLE__)
    /* Command 属于宿主。若先把它作为 Super 发给 Kali，Cmd+Tab 切走时
     * 补发的单独 Super release 会触发 Xfce 应用菜单。这里不合成来宾事件。 */
    if (event->keyval == GDK_KEY_Meta_L || event->keyval == GDK_KEY_Meta_R ||
        event->keyval == GDK_KEY_Super_L || event->keyval == GDK_KEY_Super_R) {
        return TRUE;
    }
    /* release 可能在 Command 已松开或重新聚焦后才到达，不能只看 state。
     * 若宿主吞掉 release，新一轮普通 press 清掉旧预约但正常转发。 */
    for (gint index = 0; index < context->host_release_count; index++) {
        if (context->host_release_keys[index] == event->keyval) {
            context->host_release_keys[index] = context->host_release_keys[--context->host_release_count];
            if (event->type == GDK_KEY_RELEASE) return TRUE;
            break;
        }
    }
    if (event->type == GDK_KEY_PRESS &&
        (event->state & (GDK_META_MASK | GDK_SUPER_MASK)) != 0) {
        if (context->host_release_count < CTFLAB_MAX_PRESSED_KEYS) {
            context->host_release_keys[context->host_release_count++] = event->keyval;
        }
        if ((event->state & (GDK_CONTROL_MASK | GDK_MOD1_MASK)) == 0) {
            switch (gdk_keyval_to_lower(event->keyval)) {
            case GDK_KEY_c: case GDK_KEY_v: case GDK_KEY_x:
            case GDK_KEY_a: case GDK_KEY_z:
                input_send_mac_shortcut(context, gdk_keyval_to_lower(event->keyval));
                break;
            default: break;
            }
        }
        /* 其余 Command 组合留给 macOS，不把 Tab 或其他字符送进来宾。 */
        return TRUE;
    }
#else
    if (event->type == GDK_KEY_PRESS && (event->state & GDK_META_MASK) != 0 &&
        (event->state & (GDK_CONTROL_MASK | GDK_MOD1_MASK)) == 0) {
        guint letter = 0;
        switch (event->keyval) {
        case GDK_KEY_c: case GDK_KEY_C: letter = GDK_KEY_c; break;
        case GDK_KEY_v: case GDK_KEY_V: letter = GDK_KEY_v; break;
        case GDK_KEY_x: case GDK_KEY_X: letter = GDK_KEY_x; break;
        case GDK_KEY_a: case GDK_KEY_A: letter = GDK_KEY_a; break;
        case GDK_KEY_z: case GDK_KEY_Z: letter = GDK_KEY_z; break;
        default: break;
        }
        if (letter != 0) {
            input_send_mac_shortcut(context, letter);
            return TRUE;
        }
    }
#endif
    /* 恢复期间用户开始正常输入，则不再补发其他键的 release 干扰输入。 */
    if (event->type == GDK_KEY_PRESS) input_cancel_scancode_reset(context);
    input_track_key(context, event->keyval, event->type == GDK_KEY_PRESS);
    return FALSE;
}

static gboolean on_window_focus_out(GtkWidget *window, GdkEvent *event, gpointer user_data)
{
    (void)window;
    (void)event;
    if (g_strcmp0(g_getenv("CTFLAB_TRACE_DISPLAY_RECOVERY"), "1") == 0) {
        InputContext *context = user_data;
        fprintf(stderr, "CTFLAB_SPICE_STATE recovery-phase=focus-out display-focus=%d held-count=%d t=%llums\n",
                context->display != NULL && gtk_widget_has_focus(GTK_WIDGET(context->display)),
                context->pressed_count, mono_ms());
        fflush(stderr);
    }
    /* 失焦时来宾不会再收到 release；补发避免修饰键在来宾侧卡住。 */
    input_release_pressed_keys((InputContext *)user_data);
    return FALSE;
}

static gboolean on_window_grab_broken(GtkWidget *window, GdkEvent *event, gpointer user_data)
{
    (void)window;
    (void)event;
    input_release_pressed_keys((InputContext *)user_data);
    return FALSE;
}

static void on_session_disconnected(SpiceSession *session, gpointer user_data)
{
    SessionContext *context = (SessionContext *)user_data;
    fprintf(stderr, "CTFLAB_SPICE_STATE disconnected\n");
    fflush(stderr);
    request_client_quit(context, session);
}

static gboolean on_window_delete(GtkWidget *window, GdkEvent *event, gpointer user_data)
{
    SessionContext *context = (SessionContext *)user_data;
    (void)window;
    (void)event;
    /* 先断开来宾显示通道，再退出 GTK 主循环；QEMU 的生命周期由 CTFLab 管理。 */
    request_client_quit(context, context->session);
    return TRUE;
}

static const char *uri_argument(int argc, char **argv)
{
    for (int index = 1; index < argc; index++) {
        if (strcmp(argv[index], "--uri") == 0 && index + 1 < argc) {
            return argv[index + 1];
        }
        if (strncmp(argv[index], "--uri=", 6) == 0) {
            return argv[index] + 6;
        }
    }
    return NULL;
}

static gboolean clipboard_argument(int argc, char **argv)
{
    for (int index = 1; index < argc; index++) {
        if (strcmp(argv[index], "--clipboard") == 0) {
            return TRUE;
        }
    }
    return FALSE;
}

static gboolean file_transfer_argument(int argc, char **argv)
{
    for (int index = 1; index < argc; index++) {
        if (strcmp(argv[index], "--file-transfer") == 0) {
            return TRUE;
        }
    }
    return FALSE;
}

static const char *password_file_argument(int argc, char **argv)
{
    for (int index = 1; index < argc - 1; index++) {
        if (strcmp(argv[index], "--password-file") == 0) {
            return argv[index + 1];
        }
    }
    return NULL;
}

static char *read_ticket_file(const char *path)
{
    FILE *handle = fopen(path, "r");
    if (handle == NULL) {
        return NULL;
    }
    char buffer[256];
    size_t length = fread(buffer, 1, sizeof(buffer) - 1, handle);
    fclose(handle);
    if (length == 0) {
        return NULL;
    }
    /* 去掉运行器写入的行尾换行；ticket 不留高于必要的生命周期。 */
    while (length > 0 && (buffer[length - 1] == '\n' || buffer[length - 1] == '\r')) {
        length -= 1;
    }
    buffer[length] = '\0';
    return g_strdup(buffer);
}

static gboolean fullscreen_argument(int argc, char **argv)
{
    for (int index = 1; index < argc; index++) {
        if (strcmp(argv[index], "--fullscreen") == 0) {
            return TRUE;
        }
    }
    return FALSE;
}

/* 窗口几何记忆：--geometry 显式覆盖，--state-file 由运行器提供并跨次启动复用。 */
typedef struct {
    gint width;
    gint height;
    gboolean fullscreen;
} WindowGeometry;

static gboolean parse_geometry_text(const char *text, WindowGeometry *geometry)
{
    if (text == NULL) {
        return FALSE;
    }
    int width = 0, height = 0;
    char tail = '\0';
    if (sscanf(text, "%dx%d%c", &width, &height, &tail) != 2) {
        return FALSE;
    }
    if (width < 400 || height < 300 || width > 16384 || height > 16384) {
        return FALSE;
    }
    geometry->width = width;
    geometry->height = height;
    geometry->fullscreen = FALSE;
    return TRUE;
}

static gboolean geometry_argument(int argc, char **argv, WindowGeometry *geometry)
{
    for (int index = 1; index < argc; index++) {
        const char *value = NULL;
        if (strcmp(argv[index], "--geometry") == 0 && index + 1 < argc) {
            value = argv[++index];
        } else if (strncmp(argv[index], "--geometry=", 11) == 0) {
            value = argv[index] + 11;
        }
        if (value != NULL) {
            return parse_geometry_text(value, geometry);
        }
    }
    return FALSE;
}

static const char *state_file_argument(int argc, char **argv)
{
    for (int index = 1; index < argc - 1; index++) {
        if (strcmp(argv[index], "--state-file") == 0) {
            return argv[index + 1];
        }
    }
    return NULL;
}

/* 显示偏好：sharp=清晰优先（Retina 设备像素），smooth=流畅优先（逻辑分辨率）。 */
static gint display_quality_argument(int argc, char **argv)
{
    for (int index = 1; index < argc; index++) {
        const char *value = NULL;
        if (strcmp(argv[index], "--display-quality") == 0 && index + 1 < argc) {
            value = argv[++index];
        } else if (strncmp(argv[index], "--display-quality=", 18) == 0) {
            value = argv[index] + 18;
        }
        if (value != NULL) {
            return strcmp(value, "smooth") == 0 ? 1 : 0;
        }
    }
    return -1;
}

/*
 * 状态文件是单行自描述文本（g_file_set_contents 原子替换）。越界值按损坏
 * 处理：宁可回到默认几何，也不能把无效尺寸写进窗口。
 */
static gboolean window_state_load(const char *path, WindowGeometry *geometry,
                                  gint *scale_factor, gint *quality_out)
{
    gchar *content = NULL;
    if (path == NULL || !g_file_get_contents(path, &content, NULL, NULL)) {
        return FALSE;
    }
    int width = 0, height = 0, fullscreen = 0, scale = 1, quality = 0;
    int matched = sscanf(content,
                         "ctflab-client-window v1 width=%d height=%d fullscreen=%d scale=%d quality=%d",
                         &width, &height, &fullscreen, &scale, &quality);
    gboolean ok = matched >= 4;
    if (ok && quality_out != NULL) {
        *quality_out = quality == 1 ? 1 : 0;
    }
    g_free(content);
    if (!ok || width < 400 || width > 16384 || height < 300 || height > 16384) {
        return FALSE;
    }
    geometry->width = width;
    geometry->height = height;
    geometry->fullscreen = fullscreen != 0;
    if (scale_factor != NULL) {
        *scale_factor = scale > 0 ? scale : 1;
    }
    return TRUE;
}

static void window_state_save(const char *path, gint width, gint height,
                              gboolean fullscreen, gint scale_factor, gint quality)
{
    if (path == NULL) {
        return;
    }
    if (scale_factor < 1) {
        scale_factor = 1;
    }
    gchar *content = g_strdup_printf(
        "ctflab-client-window v1 width=%d height=%d fullscreen=%d scale=%d quality=%d\n",
        width, height, fullscreen ? 1 : 0, scale_factor, quality == 1 ? 1 : 0);
    GError *error = NULL;
    if (g_file_set_contents(path, content, -1, &error)) {
        fprintf(stderr, "CTFLAB_SPICE_STATE window-state-saved %dx%d fullscreen=%d t=%llums\n",
                width, height, fullscreen ? 1 : 0, mono_ms());
    } else {
        fprintf(stderr, "CTFLAB_SPICE_STATE window-state-save-failed: %s\n",
                error != NULL ? error->message : "unknown");
        g_clear_error(&error);
    }
    fflush(stderr);
    g_free(content);
}

/*
 * CTFLab 启动客户端时把刚创建的 QEMU PID 作为受控参数传入。SPICE 的 disconnected
 * 信号通常会让客户端退出；这个守卫覆盖 QEMU 异常退出、socket 已消失但 GTK 尚未收到
 * 通知的情况，避免用户结束 Kali 后遗留一个无用的 spicy 窗口/进程。
 */
static int qemu_pid_argument(int argc, char **argv, pid_t *pid)
{
    for (int index = 1; index < argc; index++) {
        const char *value = NULL;
        if (strcmp(argv[index], "--qemu-pid") == 0 && index + 1 < argc) {
            value = argv[++index];
        } else if (strncmp(argv[index], "--qemu-pid=", 11) == 0) {
            value = argv[index] + 11;
        }
        if (value != NULL) {
            char *end = NULL;
            long parsed = 0;
            errno = 0;
            parsed = strtol(value, &end, 10);
            if (errno != 0 || end == value || *end != '\0' || parsed <= 0) {
                return -1;
            }
            *pid = (pid_t)parsed;
            return 1;
        }
    }
    return 0;
}

static gboolean qemu_process_running(pid_t pid)
{
    if (pid <= 0) {
        return FALSE;
    }
    if (kill(pid, 0) != 0) {
        return errno != ESRCH;
    }
#if defined(__APPLE__)
    /* kill(pid, 0) 对尚未被父进程回收的僵尸进程也成功，不能据此保留窗口。 */
    int mib[] = {CTL_KERN, KERN_PROC, KERN_PROC_PID, pid};
    struct kinfo_proc info = {0};
    size_t size = sizeof(info);
    if (sysctl(mib, 4, &info, &size, NULL, 0) == 0) {
        return size != 0 && info.kp_proc.p_stat != SZOMB;
    }
#endif
    /* 无权限查询详细状态时保守保留；明确不存在的 PID 已在上面处理。 */
    return TRUE;
}

static gboolean watch_qemu_process(gpointer user_data)
{
    SessionContext *context = (SessionContext *)user_data;
    pid_t qemu_pid = context->qemu->pid;
    if (qemu_process_running(qemu_pid)) {
        return G_SOURCE_CONTINUE;
    }
    fprintf(stderr, "CTFLAB_SPICE_STATE qemu-exited pid=%d\n", (int)qemu_pid);
    fflush(stderr);
    request_client_quit(context, context->session);
    context->qemu->source_id = 0;
    return G_SOURCE_REMOVE;
}

/*
 * resize-guest 每次尺寸事件都会向来宾发送一次 monitors config。直接在拖动窗口时打开它，
 * 会让 XFCE 连续切换显示模式，表现为多次黑屏/刷新。这里在最后一次窗口配置事件后等待
 * 180ms，只提交一次最终尺寸；它不改变“真实动态分辨率”的语义，只避免拖动过程反复 modeset。
 */
typedef struct {
    SpiceDisplay *display;
    SpiceMainChannel *main_channel;
    gboolean agent_connected;
    gboolean absolute_mouse_ready;
    gboolean display_ready;
    guint resize_timer_id;
    guint unstick_timer_id;
    guint resize_generation;
    GtkWidget *shield;          /* 过渡期拦截指针输入的 overlay 覆盖层 */
    GtkWidget *shield_canvas;   /* 冻结帧绘制区 */
    GdkPixbuf *frozen_frame;    /* 提交 monitors config 前捕获的最后一帧 */
    guint transition_timer_id;
    guint frame_check_idle_id;
    guint redraw_idle_id;       /* 恢复可见状态后的合并重绘，不发送来宾 modeset */
    gboolean focus_damage_redraw_pending; /* 焦点/空闲后首个移动先于新帧时，首个 damage 再重绘一次 */
    gint canvas_width, canvas_height; /* 0 号通道实际 primary 尺寸；点击不复制整帧 */
    gint allocated_width, allocated_height; /* 内容区变化与外层 configure 分开观察 */
    gboolean transition_damage_seen;
    gint64 transition_deadline; /* 单调时钟；超时强制结束过渡 */
    gint transition_target_w, transition_target_h;
    gint last_config_w, last_config_h; /* 上次提交的来宾尺寸，避免重复 modeset */
    gint pixel_multiplier;         /* 清晰优先=Retina scale；流畅优先=1（逻辑分辨率） */
    gboolean transition_active;
    gboolean display_state_enabled; /* 已把 0 号显示器标记为 ENABLED（spice-gtk 拒发 UNDEFINED 显示器） */
    gint64 last_reassert_mono;      /* 上次向改写分辨率的来宾重申目标的时间 */
    gint reassert_count;            /* 重申次数（连续被改写 5 次后停手防打持久战） */
    SpiceInputsChannel *inputs_channel; /* 通道级位置注入（E2E 诊断） */
    guint motion_count; /* 只计事件，不记录键入内容；诊断缺失/合并的指针移动 */
    gdouble last_motion_x, last_motion_y;
    gint64 last_motion_mono;
    gint64 recovery_input_log_mono, recovery_damage_log_mono, recovery_draw_log_mono;
    guint recovery_trace_cycle;
    gboolean recovery_trace_pending;
    gint64 recovery_trace_input_mono, recovery_trace_damage_mono;
} ClientContext;

typedef struct {
    ClientContext *context;
    guint generation;
} ResizeTimerContext;

/* 独立验收按需开启：只记阶段与时间，不读画面、键入内容或坐标。
 * damage/GTK draw 是链路阶段，不等于来宾已经解锁或最终画面正确。 */
static void trace_display_recovery(const char *phase, gint64 *last, gint interval_ms)
{
    if (g_strcmp0(g_getenv("CTFLAB_TRACE_DISPLAY_RECOVERY"), "1") != 0) {
        return;
    }
    gint64 now = g_get_monotonic_time();
    if (last != NULL && *last != 0 && now - *last < (gint64)interval_ms * 1000) {
        return;
    }
    if (last != NULL) {
        *last = now;
    }
    fprintf(stderr, "CTFLAB_SPICE_STATE recovery-phase=%s t=%llums\n",
            phase, (long long)(now / 1000));
    fflush(stderr);
}

/* 首个更新/绘制不参与通用日志限流；否则可能把“省略日志”误判为显示停顿。
 * 仍只测输入→damage→GTK draw，不能证明像素正确或来宾已唤醒/解锁。 */
static void begin_recovery_trace(ClientContext *context, const char *reason)
{
    if (g_strcmp0(g_getenv("CTFLAB_TRACE_DISPLAY_RECOVERY"), "1") != 0) {
        return;
    }
    context->recovery_trace_cycle++;
    context->recovery_trace_pending = TRUE;
    context->recovery_trace_input_mono = g_get_monotonic_time();
    context->recovery_trace_damage_mono = 0;
    fprintf(stderr, "CTFLAB_SPICE_STATE recovery-cycle=%u phase=input reason=%s t=%llums\n",
            context->recovery_trace_cycle, reason,
            (long long)(context->recovery_trace_input_mono / 1000));
    fflush(stderr);
}

static gboolean on_display_draw_trace(GtkWidget *widget, cairo_t *cr, gpointer data)
{
    (void)widget; (void)cr;
    ClientContext *context = data;
    if (context->recovery_trace_pending && context->recovery_trace_damage_mono != 0) {
        gint64 now = g_get_monotonic_time();
        fprintf(stderr, "CTFLAB_SPICE_STATE recovery-cycle=%u phase=first-gtk-draw input-us=%lld damage-us=%lld t=%llums\n",
                context->recovery_trace_cycle,
                (long long)(now - context->recovery_trace_input_mono),
                (long long)(now - context->recovery_trace_damage_mono),
                (long long)(now / 1000));
        fflush(stderr);
        context->recovery_trace_pending = FALSE;
    }
    trace_display_recovery("gtk-draw", &context->recovery_draw_log_mono, 100);
    return FALSE;
}

/* Quartz 在息屏/失焦恢复后可能仍保留黑色 backing store。等本轮 SPICE
 * 更新结束再重绘整个原生窗口（含子窗口），不读取像素、不改坐标、不撤屏障。 */
static gboolean redraw_display_idle(gpointer data)
{
    ClientContext *context = data;
    context->redraw_idle_id = 0;
    if (context->display != NULL) {
        GtkWidget *display = GTK_WIDGET(context->display);
        gtk_widget_queue_draw(display);
        GtkWidget *toplevel = gtk_widget_get_toplevel(display);
        if (gtk_widget_get_realized(toplevel)) {
            GdkWindow *window = gtk_widget_get_window(toplevel);
            if (window != NULL) {
                gdk_window_invalidate_rect(window, NULL, TRUE);
            }
        }
    }
    return G_SOURCE_REMOVE;
}

static void queue_display_redraw(ClientContext *context)
{
    if (context->redraw_idle_id == 0) {
        context->redraw_idle_id = g_idle_add(redraw_display_idle, context);
    }
}

static gboolean on_window_focus_in(GtkWidget *window, GdkEvent *event, gpointer data)
{
    (void)window; (void)event;
    trace_display_recovery("focus-in", NULL, 0);
    ClientContext *context = data;
    if (g_strcmp0(g_getenv("CTFLAB_TRACE_DISPLAY_RECOVERY"), "1") == 0) {
        fprintf(stderr, "CTFLAB_SPICE_STATE recovery-phase=focus-detail display-focus=%d t=%llums\n",
                context->display != NULL && gtk_widget_has_focus(GTK_WIDGET(context->display)),
                mono_ms());
        fflush(stderr);
    }
    begin_recovery_trace(context, "focus-in");
    context->focus_damage_redraw_pending = TRUE;
    queue_display_redraw(context);
    return FALSE; /* 不吞掉正常焦点事件。 */
}

/*
 * 分辨率切换过渡：提交 monitors config 后，来宾要重建显示 surface，旧帧消失
 * 出现短暂黑屏，且窗口/来宾尺寸短暂不一致，spice-gtk 的输入变换会把点击映射
 * 到旧坐标。这里用 overlay 冻结最后一帧并拦截指针输入，直到捕获到的帧尺寸与
 * 请求一致或超时；键盘照常转发（按键与显示坐标无关）。
 */
static void shield_end(ClientContext *context, const char *reason)
{
    if (context->frame_check_idle_id != 0) {
        g_source_remove(context->frame_check_idle_id);
        context->frame_check_idle_id = 0;
    }
    if (context->transition_timer_id != 0) {
        g_source_remove(context->transition_timer_id);
        context->transition_timer_id = 0;
    }
    if (!context->transition_active) {
        return;
    }
    context->transition_active = FALSE;
    gtk_widget_hide(context->shield);
    /* Quartz 不保证移除覆盖层后立即重绘下层；即使画布尺寸已经匹配，
     * 仍可能保留 surface 重建时的黑色区域。请求重绘，不改变输入映射。 */
    if (context->display != NULL) {
        gtk_widget_queue_draw(GTK_WIDGET(context->display));
    }
    fprintf(stderr, "CTFLAB_SPICE_STATE display-transition end reason=%s t=%llums\n", reason, mono_ms());
    fflush(stderr);
}

/* 只测量耗时，不改变画布或坐标；详细记录须在独立验收实例显式开启。 */
static GdkPixbuf *measured_frame(SpiceDisplay *display, const char *site)
{
    gint64 started = g_get_monotonic_time();
    gboolean trace = g_strcmp0(g_getenv("CTFLAB_TRACE_FRAME_TIMING"), "1") == 0;
    if (trace) {
        fprintf(stderr, "CTFLAB_SPICE_STATE frame-read begin site=%s\n", site);
        fflush(stderr);
    }
    GdkPixbuf *frame = spice_display_get_pixbuf(display);
    gint64 elapsed = g_get_monotonic_time() - started;
    if (trace || elapsed >= 16000) {
        fprintf(stderr, "CTFLAB_SPICE_STATE frame-read end site=%s us=%lld\n",
                site, (long long)elapsed);
        fflush(stderr);
    }
    return frame;
}

static gboolean shield_check(gpointer user_data)
{
    ClientContext *context = (ClientContext *)user_data;
    if (!context->transition_active) {
        context->transition_timer_id = 0;
        return G_SOURCE_REMOVE;
    }
    if (g_get_monotonic_time() >= context->transition_deadline) {
        GdkPixbuf *frame = context->display != NULL
            ? measured_frame(context->display, "transition-timeout") : NULL;
        gint observed_w = frame != NULL ? gdk_pixbuf_get_width(frame) : 0;
        gint observed_h = frame != NULL ? gdk_pixbuf_get_height(frame) : 0;
        if (frame != NULL) {
            g_object_unref(frame);
        }
        /* 超时时刻来宾画布的真实尺寸：区分“来宾未应用”与“应用了别的模式”。 */
        fprintf(stderr,
                "CTFLAB_SPICE_STATE display-transition observed=%dx%d target=%dx%d\n",
                observed_w, observed_h, context->transition_target_w,
                context->transition_target_h);
        fflush(stderr);
        shield_end(context, "timeout");
        context->transition_timer_id = 0;
        return G_SOURCE_REMOVE;
    }
    /* primary-create/ready 只表示画布已分配；必须等真实绘制更新，
     * 否则尺寸正确的空 surface 会提前撤掉冻结帧、露出黑屏。 */
    if (!context->display_ready || !context->transition_damage_seen) {
        return G_SOURCE_CONTINUE;
    }
    GdkPixbuf *frame = context->display != NULL
        ? measured_frame(context->display, "transition-check") : NULL;
    if (frame != NULL) {
        gboolean matched = gdk_pixbuf_get_width(frame) == context->transition_target_w &&
                           gdk_pixbuf_get_height(frame) == context->transition_target_h;
        g_object_unref(frame);
        if (matched) {
            shield_end(context, "frame-matched");
            context->transition_timer_id = 0;
            return G_SOURCE_REMOVE;
        }
    }
    return G_SOURCE_CONTINUE;
}

static gboolean check_transition_frame_idle(gpointer data)
{
    ClientContext *context = data;
    context->frame_check_idle_id = 0;
    shield_check(context);
    return G_SOURCE_REMOVE;
}

static void queue_transition_frame_check(ClientContext *context)
{
    if (context->transition_active && context->display != NULL && context->frame_check_idle_id == 0) {
        context->frame_check_idle_id = g_idle_add(check_transition_frame_idle, context);
    }
}

static void on_display_invalidate(SpiceChannel *channel, gint x, gint y, gint width, gint height,
                                  gpointer data)
{
    (void)channel; (void)x; (void)y;
    ClientContext *context = data;
    if (width > 0 && height > 0) {
        if (context->recovery_trace_pending && context->recovery_trace_damage_mono == 0) {
            context->recovery_trace_damage_mono = g_get_monotonic_time();
            fprintf(stderr, "CTFLAB_SPICE_STATE recovery-cycle=%u phase=first-damage input-us=%lld t=%llums\n",
                    context->recovery_trace_cycle,
                    (long long)(context->recovery_trace_damage_mono - context->recovery_trace_input_mono),
                    (long long)(context->recovery_trace_damage_mono / 1000));
            fflush(stderr);
        }
        trace_display_recovery("damage", &context->recovery_damage_log_mono, 100);
        if (context->focus_damage_redraw_pending) {
            context->focus_damage_redraw_pending = FALSE;
            trace_display_recovery("fresh-damage-redraw", NULL, 0);
            /* 焦点恢复时旧帧可能仍黑；只对首个新更新再补一轮 native 重绘。
             * idle 等本轮 SPICE 更新完成，不在每帧上重复全窗口失效。 */
            queue_display_redraw(context);
        }
    }
    if (!context->transition_active || width <= 0 || height <= 0) {
        return;
    }
    if (!context->transition_damage_seen) {
        context->transition_damage_seen = TRUE;
        fprintf(stderr, "CTFLAB_SPICE_STATE transition-first-paint t=%llums\n", mono_ms());
        fflush(stderr);
    }
    /* 合并同一轮多个绘制更新；在 SPICE/GTK 完成本轮更新后才读帧。 */
    queue_transition_frame_check(context);
}

static void on_display_primary_create(SpiceChannel *channel, gint format,
                                      gint width, gint height, gint stride,
                                      gint shmid, gpointer pixels, gpointer data)
{
    (void)channel; (void)format; (void)stride; (void)shmid; (void)pixels;
    ClientContext *context = data;
    /* 来宾分配的真实画布，而不是请求尺寸或控件大小；不读取像素。 */
    context->canvas_width = width > 0 && height > 0 ? width : 0;
    context->canvas_height = width > 0 && height > 0 ? height : 0;
    context->transition_damage_seen = FALSE;
}

static void on_display_primary_destroy(SpiceChannel *channel, gpointer data)
{
    (void)channel;
    ClientContext *context = data;
    /* 旧画布的 damage 不能作为新画布已绘制的证据。 */
    context->transition_damage_seen = FALSE;
    context->canvas_width = 0;
    context->canvas_height = 0;
}

static gboolean on_window_state(GtkWidget *window, GdkEventWindowState *event,
                                gpointer user_data)
{
    (void)window;
    fprintf(stderr, "CTFLAB_SPICE_STATE window-state changed=%u state=%u iconified=%d withdrawn=%d t=%llums\n",
            (unsigned)event->changed_mask, (unsigned)event->new_window_state,
            (event->new_window_state & GDK_WINDOW_STATE_ICONIFIED) != 0,
            (event->new_window_state & GDK_WINDOW_STATE_WITHDRAWN) != 0, mono_ms());
    fflush(stderr);
    if (event->changed_mask & (GDK_WINDOW_STATE_ICONIFIED | GDK_WINDOW_STATE_WITHDRAWN)) {
        /* 最小化/隐藏后没有可见画面：立即结束过渡并释放按键，
         * 避免冻结帧覆盖层与来宾修饰键残留到恢复之后。 */
        shield_end((ClientContext *)user_data, "window-state");
        if (g_input_context != NULL) {
            input_release_pressed_keys(g_input_context);
        }
    }
    return FALSE;
}

/*
 * 点击坐标诊断：spice-gtk 的 button_event 会静默丢弃“落在画面区域外”的
 * 点击（transform_input 之后的越界检查）。在 spice 处理之前记录窗口坐标、
 * 控件 allocation、最近一次提交的来宾尺寸与显示控件当前请求尺寸（跟随
 * 画布），用于把“输入被丢弃/映射错位”与“来宾未响应”区分开。
 */
static gboolean on_display_motion(GtkWidget *widget, GdkEventMotion *event,
                                   gpointer user_data)
{
    (void)widget;
    ClientContext *context = (ClientContext *)user_data;
    context->motion_count++;
    context->last_motion_x = event->x;
    context->last_motion_y = event->y;
    gint64 now = g_get_monotonic_time();
    if (context->last_motion_mono == 0 || now - context->last_motion_mono >= G_USEC_PER_SEC) {
        begin_recovery_trace(context, "idle-pointer-motion");
        /* 焦点未变也可能从 DPMS 恢复。空闲后首个真实移动只预约一次新帧重绘，
         * 不合成输入，不循环刷新，也不把移动事件当作来宾已唤醒。 */
        context->focus_damage_redraw_pending = TRUE;
    }
    context->last_motion_mono = now;
    trace_display_recovery("pointer-motion", &context->recovery_input_log_mono, 1000);
    return FALSE; /* 不消费事件，不改变 spice-gtk 的原坐标变换。 */
}

static gboolean on_display_button_release(GtkWidget *widget, GdkEventButton *event,
                                           gpointer user_data)
{
    (void)widget;
    ClientContext *context = (ClientContext *)user_data;
    if (g_input_context != NULL && event->button <= 3) g_input_context->held_buttons &= ~(1u << event->button);
    fprintf(stderr, "CTFLAB_SPICE_STATE input-release button=%u win=%.0f,%.0f motions=%u t=%llums\n",
            event->button, event->x, event->y, context->motion_count, mono_ms());
    fflush(stderr);
    return FALSE;
}

static gboolean sync_pointer_before_press(GtkWidget *widget, GdkEventButton *event,
                                           ClientContext *context)
{
    /* 仅供独立诊断显式启用：普通人工点击已有完整移动/释放事件，
     * 尚未证明该补偿对日常输入有收益，不改变默认输入链。 */
    if (g_strcmp0(g_getenv("CTFLAB_DIAGNOSTIC_POINTER_SYNC"), "1") != 0 ||
        context == NULL || !context->absolute_mouse_ready || !context->display_ready ||
        context->transition_active || event->window == NULL ||
        (context->motion_count > 0 && context->last_motion_x == event->x &&
         context->last_motion_y == event->y)) {
        return FALSE;
    }
    /* Quartz 可合并移动事件却保留点击。让同一控件的原 motion 处理器先收到
     * 点击位置，再交给原 button 处理器；保留 spice-gtk 的缩放/黑边变换，
     * 不自算来宾坐标、不新增按下/释放，不影响相对鼠标模式。 */
    GdkEvent *motion = gdk_event_new(GDK_MOTION_NOTIFY);
    motion->motion.window = g_object_ref(event->window);
    motion->motion.send_event = TRUE;
    motion->motion.time = event->time;
    motion->motion.x = event->x;
    motion->motion.y = event->y;
    motion->motion.x_root = event->x_root;
    motion->motion.y_root = event->y_root;
    motion->motion.state = event->state;
    GdkDevice *device = gdk_event_get_device((GdkEvent *)event);
    if (device != NULL) {
        gdk_event_set_device(motion, device);
    }
    gtk_widget_event(widget, motion);
    gdk_event_free(motion);
    fprintf(stderr, "CTFLAB_SPICE_STATE pointer-sync-before-press win=%.0f,%.0f\n", event->x, event->y);
    fflush(stderr);
    return TRUE;
}

static gboolean on_display_button_press(GtkWidget *widget, GdkEventButton *event,
                                        gpointer user_data)
{
    ClientContext *context = (ClientContext *)user_data;
    if (g_input_context != NULL && event->button <= 3) g_input_context->held_buttons |= 1u << event->button;
    begin_recovery_trace(context, "button-press");
    GtkAllocation allocation = {0};
    gtk_widget_get_allocation(widget, &allocation);
    /* primary-create/destroy 的尺寸反映实际画布；不为诊断在每次点击时复制
     * 数兆像素。未知时明确为 0，不拿窗口或请求尺寸冒充已分配画布。 */
    gint canvas_w = context->canvas_width, canvas_h = context->canvas_height;
    fprintf(stderr,
            "CTFLAB_SPICE_STATE input-press win=%.0f,%.0f alloc=%dx%d guest=%dx%d canvas=%dx%d t=%llums\n",
            event->x, event->y, allocation.width, allocation.height,
            context != NULL ? context->last_config_w : 0,
            context != NULL ? context->last_config_h : 0,
            canvas_w, canvas_h, mono_ms());
    fflush(stderr);
    fprintf(stderr, "CTFLAB_SPICE_STATE input-pointer-context button=%u motions=%u last-motion=%.0f,%.0f focused=%d\n",
            event->button, context->motion_count,
            context->last_motion_x, context->last_motion_y,
            gtk_widget_has_focus(widget) ? 1 : 0);
    fflush(stderr);
    sync_pointer_before_press(widget, event, context);
    return FALSE;
}

/*
 * 窗口权威护栏：来宾侧（显示守护/显示跟随脚本/XFCE 设置）可能自行改分辨率，
 * 与客户端 monitors config 分叉后，绘制与输入几何短暂不一致表现为“点击
 * 向下偏移、左上角正常”。来宾上报 monitors 时若与提交值不同，限速重申
 * 窗口推导的目标；连续 5 次仍被改写则停止（避免与来宾守护打持久战）。
 */
static void schedule_guest_resize(ClientContext *context);

static void on_guest_monitors_changed(SpiceChannel *channel, GParamSpec *property,
                                      gpointer user_data)
{
    (void)property;
    ClientContext *context = (ClientContext *)user_data;
    GArray *monitors = NULL;
    g_object_get(channel, "monitors", &monitors, NULL);
    gint width = 0, height = 0;
    if (monitors != NULL && monitors->len > 0) {
        SpiceDisplayMonitorConfig *config = &g_array_index(
            monitors, SpiceDisplayMonitorConfig, 0);
        width = config->width;
        height = config->height;
        g_array_unref(monitors);
    }
    fprintf(stderr, "CTFLAB_SPICE_STATE guest-monitors=%dx%d\n", width, height);
    fflush(stderr);
    if (width <= 0 || !context->display_ready) {
        return;
    }
    if (width == context->last_config_w && height == context->last_config_h) {
        context->reassert_count = 0;
        return;
    }
    gint64 now = g_get_monotonic_time();
    if (now - context->last_reassert_mono < 4 * G_USEC_PER_SEC ||
        context->reassert_count >= 5) {
        return;
    }
    context->last_reassert_mono = now;
    context->reassert_count++;
    fprintf(stderr, "CTFLAB_SPICE_STATE guest-override-reassert count=%d\n",
            context->reassert_count);
    fflush(stderr);
    schedule_guest_resize(context);
}

static void shield_begin(ClientContext *context, gint target_w, gint target_h)
{
    GdkPixbuf *frame = context->display != NULL
        ? measured_frame(context->display, "transition-freeze") : NULL;
    if (frame != NULL) {
        g_clear_pointer(&context->frozen_frame, g_object_unref);
        context->frozen_frame = frame;
    }
    context->transition_target_w = target_w;
    context->transition_target_h = target_h;
    if (context->frozen_frame != NULL &&
        gdk_pixbuf_get_width(context->frozen_frame) == target_w &&
        gdk_pixbuf_get_height(context->frozen_frame) == target_h) {
        return; /* 来宾已处于目标尺寸，不会发生 modeset */
    }
    context->transition_damage_seen = FALSE;
    if (!context->transition_active) {
        context->transition_active = TRUE;
        gtk_widget_show(context->shield);
        fprintf(stderr, "CTFLAB_SPICE_STATE display-transition begin target=%dx%d frozen=%d t=%llums\n",
                target_w, target_h, context->frozen_frame != NULL ? 1 : 0, mono_ms());
        fflush(stderr);
    }
    /* 120ms 轮询新帧尺寸；3s 超时兜底，保证覆盖层不会永久挡住画面。 */
    context->transition_deadline = g_get_monotonic_time() +
        (gint64)3000 * G_USEC_PER_SEC / 1000;
    if (context->transition_timer_id == 0) {
        context->transition_timer_id = g_timeout_add(120, shield_check, context);
    }
}

static gboolean on_shield_draw(GtkWidget *widget, cairo_t *cr, gpointer user_data)
{
    ClientContext *context = (ClientContext *)user_data;
    if (context->frozen_frame == NULL) {
        return FALSE;
    }
    GtkAllocation allocation = {0};
    gtk_widget_get_allocation(widget, &allocation);
    gint frame_w = gdk_pixbuf_get_width(context->frozen_frame);
    gint frame_h = gdk_pixbuf_get_height(context->frozen_frame);
    if (frame_w <= 0 || frame_h <= 0 || allocation.width <= 0 || allocation.height <= 0) {
        return FALSE;
    }
    /*
     * 与 spice-gtk 的显示几何完全一致：等比缩放并居中（信箱留边），不用
     * 拉伸填满。拉伸会让画面与输入映射（按 spice 的信箱几何换算）出现
     * 视差——冻结帧期间点哪里都会偏。
     */
    double scale = MIN((double)allocation.width / frame_w,
                       (double)allocation.height / frame_h);
    double draw_w = frame_w * scale;
    double draw_h = frame_h * scale;
    double offset_x = ((double)allocation.width - draw_w) / 2.0;
    double offset_y = ((double)allocation.height - draw_h) / 2.0;
    cairo_save(cr);
    cairo_translate(cr, offset_x, offset_y);
    cairo_scale(cr, scale, scale);
    gdk_cairo_set_source_pixbuf(cr, context->frozen_frame, 0, 0);
    cairo_paint(cr);
    cairo_restore(cr);
    return FALSE;
}

static gboolean on_shield_event(GtkWidget *widget, GdkEvent *event, gpointer user_data)
{
    (void)widget;
    (void)event;
    (void)user_data;
    /* 过渡期把指针输入挡在来宾之外，避免按旧坐标投递。 */
    return TRUE;
}

static void apply_guest_resize(ClientContext *context)
{
    if (getenv("CTFLAB_TEST_NORESIZE") != NULL) {
        return; /* 对照实验：禁用客户端驱动的分辨率跟随 */
    }
    GtkAllocation allocation = {0};
    gint scale_factor = 1;
    gint width = 0;
    gint height = 0;

    if (context->main_channel == NULL || context->display == NULL) {
        return;
    }
    gtk_widget_get_allocation(GTK_WIDGET(context->display), &allocation);
    scale_factor = gtk_widget_get_scale_factor(GTK_WIDGET(context->display));
    if (scale_factor < 1) {
        scale_factor = 1;
    }
    /*
     * 清晰优先（默认）：allocation × Retina scale，来宾使用设备像素；
     * 流畅优先：×1，来宾用逻辑分辨率（Retina 上像素数降为 1/4，滚动/拖动
     * 更流畅）。两者都真实改变来宾分辨率并保留 SpiceDisplay 输入变换，
     * 只是像素密度不同——不是拉伸冒充。
     */
    gint multiplier = context->pixel_multiplier > 0 ? context->pixel_multiplier : scale_factor;
    width = MAX(640, allocation.width * multiplier);
    height = MAX(480, allocation.height * multiplier);
    if (context->display_ready &&
        context->last_config_w == width && context->last_config_h == height) {
        return; /* 窗口移动等场景尺寸未变，不重复 modeset */
    }
    fprintf(stderr,
            "CTFLAB_SPICE_STATE resize-target logical=%dx%d scale=%d multiplier=%d physical=%dx%d t=%llums\n",
            allocation.width, allocation.height, scale_factor, multiplier, width, height, mono_ms());
    fflush(stderr);
    if (!context->display_state_enabled) {
        /*
         * spice-gtk 0.42 的 display_state 默认是 DISPLAY_UNDEFINED，monitors
         * config 会被整包拒发（"Not sending monitors config, missing
         * monitors"），update_display 只更新内存映射、来宾永远收不到。
         * 接管手动 resize 前先把 0 号显示器标记 ENABLED；update=FALSE，
         * 只改状态，由随后的 update_display 触发实际发送。
         */
        spice_main_channel_update_display_enabled(context->main_channel, 0, TRUE, FALSE);
        context->display_state_enabled = TRUE;
        fprintf(stderr, "CTFLAB_SPICE_STATE display-enabled id=0\n");
        fflush(stderr);
    }
    if (context->display_ready) {
        shield_begin(context, width, height);
    }
    /* 本客户端已合并 180ms 的窗口事件。update=TRUE 会再触发 spice-gtk
     * 内部 1 秒计时器；只更新本地配置，再明确发送，避免两层防抖叠加。
     * 先冻结旧画面，仍须等实际新帧匹配才恢复指针输入。 */
    spice_main_channel_update_display(context->main_channel, 0, 0, 0,
                                      width, height, FALSE);
    gboolean sent = spice_main_channel_send_monitor_config(context->main_channel);
    fprintf(stderr, "CTFLAB_SPICE_STATE resize-send immediate=1 accepted=%d target=%dx%d t=%llums\n",
            sent, width, height, mono_ms());
    fflush(stderr);
    if (sent) {
        context->last_config_w = width;
        context->last_config_h = height;
    }
}

static gboolean enable_guest_resize(gpointer user_data)
{
    ResizeTimerContext *timer = (ResizeTimerContext *)user_data;
    ClientContext *context = timer->context;
    gboolean current = timer->generation == context->resize_generation;
    if (current) {
        context->resize_timer_id = 0;
    }
    if (current && context->display_ready && context->agent_connected &&
        context->absolute_mouse_ready) {
        fprintf(stderr, "CTFLAB_SPICE_STATE resize-enable generation=%u\n", timer->generation);
        fflush(stderr);
        apply_guest_resize(context);
    }
    return G_SOURCE_REMOVE;
}

/* GLib 拥有计时器参数；执行、取消或客户端退出都统一释放。
 * 原先仅在回调末尾释放，连续拖动取消旧计时器会积累未释放参数。 */
static void queue_guest_resize(ClientContext *context)
{
    if (context->resize_timer_id != 0) {
        g_source_remove(context->resize_timer_id);
        context->resize_timer_id = 0;
    }
    context->resize_generation++;
    ResizeTimerContext *timer = g_new0(ResizeTimerContext, 1);
    timer->context = context;
    timer->generation = context->resize_generation;
    context->resize_timer_id = g_timeout_add_full(
        G_PRIORITY_DEFAULT, 180, enable_guest_resize, timer, g_free);
}

static void schedule_guest_resize(ClientContext *context)
{
    /*
     * 只有显示 surface 已就绪、agent 已连接且主通道确认进入 CLIENT 绝对坐标模式后，
     * 才允许改变来宾分辨率。过早发送 monitors config 会让 GTK 窗口尺寸、来宾 surface
     * 与输入坐标在启动阶段短暂处于不同代际，表现为点击位置偏移。
     */
    if (!context->display_ready || !context->agent_connected ||
        !context->absolute_mouse_ready) {
        return;
    }
    /* 在用户继续拖动时先抑制中间尺寸；计时器只会应用最后一个尺寸。 */
    g_object_set(context->display, "resize-guest", FALSE, NULL);
    queue_guest_resize(context);
}

static gboolean on_window_configure(GtkWidget *window, GdkEventConfigure *event,
                                    gpointer user_data)
{
    (void)window;
    (void)event;
    ClientContext *context = (ClientContext *)user_data;
    fprintf(stderr, "CTFLAB_SPICE_STATE configure generation=%u\n", context->resize_generation + 1);
    fflush(stderr);
    schedule_guest_resize(context);
    return FALSE;
}

static void on_display_size_allocate(GtkWidget *display, GtkAllocation *allocation,
                                     gpointer user_data)
{
    (void)display;
    ClientContext *context = user_data;
    if (allocation->width <= 0 || allocation->height <= 0 ||
        (context->allocated_width == allocation->width &&
         context->allocated_height == allocation->height)) {
        return;
    }
    context->allocated_width = allocation->width;
    context->allocated_height = allocation->height;
    fprintf(stderr, "CTFLAB_SPICE_STATE content-allocation=%dx%d t=%llums\n",
            allocation->width, allocation->height, mono_ms());
    /* 装饰/全屏可能只改变内容分配而无外层事件；仍沿用就绪门禁和合并计时器。
     * 不直接 modeset、不改坐标变换，重复分配不会不断重置计时器。 */
    schedule_guest_resize(context);
}

static void update_mouse_mode(SpiceMainChannel *channel, ClientContext *context)
{
    gboolean agent_connected = FALSE;
    gint mouse_mode = 0;
    g_object_get(channel, "agent-connected", &agent_connected, NULL);
    g_object_get(channel, "mouse-mode", &mouse_mode, NULL);
    context->agent_connected = agent_connected;
    fprintf(stderr, "CTFLAB_SPICE_STATE agent=%d mouse-mode=%d\n", agent_connected ? 1 : 0, mouse_mode);
    fflush(stderr);
    if (!agent_connected) {
        context->absolute_mouse_ready = FALSE;
        return;
    }
    if (mouse_mode != SPICE_MOUSE_MODE_CLIENT) {
        /* 使用绝对坐标，和 QEMU 的 usb-tablet 对齐；等待服务端确认后再启用 resize。 */
        spice_main_channel_request_mouse_mode(channel, SPICE_MOUSE_MODE_CLIENT);
        context->absolute_mouse_ready = FALSE;
        return;
    }
    context->absolute_mouse_ready = TRUE;
    schedule_guest_resize(context);
}

/*
 * 显示死锁解锁：来宾侧 blank/DPMS 后 virtio-gpu 管线要收到客户端的
 * monitors config 才会重建扫描输出，而常规路径又在等 display surface
 * 就绪才发送，两者互相等待。agent 已连接但 display 迟迟未就绪时，按当前
 * 窗口尺寸主动发送一次 monitors config 解锁。
 */
static gboolean unstick_display_config(gpointer user_data)
{
    ClientContext *context = (ClientContext *)user_data;
    context->unstick_timer_id = 0;
    if (context->display_ready || !context->agent_connected) {
        return G_SOURCE_REMOVE;
    }
    fprintf(stderr, "CTFLAB_SPICE_STATE display-unstick sent\n");
    fflush(stderr);
    apply_guest_resize(context);
    return G_SOURCE_REMOVE;
}

static void on_main_agent_update(SpiceMainChannel *channel, gpointer user_data)
{
    ClientContext *context = (ClientContext *)user_data;
    update_mouse_mode(channel, context);
    if (context->agent_connected && !context->display_ready &&
        context->unstick_timer_id == 0) {
        context->unstick_timer_id = g_timeout_add_seconds(3, unstick_display_config, context);
    }
}

static void on_mouse_mode_update(SpiceMainChannel *channel, GParamSpec *property,
                                 gpointer user_data)
{
    (void)property;
    update_mouse_mode(channel, (ClientContext *)user_data);
}

static void on_display_ready(GObject *display, GParamSpec *property, gpointer user_data)
{
    ClientContext *context = (ClientContext *)user_data;
    gboolean ready = FALSE;
    (void)property;
    g_object_get(display, "ready", &ready, NULL);
    context->display_ready = ready;
    trace_display_recovery(ready ? "ready-on" : "ready-off", NULL, 0);
    fprintf(stderr, "CTFLAB_SPICE_STATE display-ready=%d\n", ready ? 1 : 0);
    fflush(stderr);
    if (ready) {
        queue_display_redraw(context);
    }
    if (ready && context->transition_active) {
        /* ready 回调仍在 surface 更新链内，留到 idle 核验；实际绘制与
         * 目标尺寸同时通过才放行，不能仅凭 ready 或新画布尺寸。 */
        queue_transition_frame_check(context);
    }
    schedule_guest_resize(context);
}

#ifdef CTFLAB_E2E_TEST
static void on_inputs_channel_destroy(ClientContext *context, gpointer channel)
{
    if (context->inputs_channel == SPICE_INPUTS_CHANNEL(channel)) {
        context->inputs_channel = NULL;
        fprintf(stderr, "CTFLAB_E2E_TEST inputs-channel-destroyed\n");
        fflush(stderr);
    }
}
#endif

static void on_channel_new(SpiceSession *session, SpiceChannel *channel, gpointer user_data)
{
    (void)session;
    if (SPICE_IS_INPUTS_CHANNEL(channel) && g_input_context != NULL) {
        g_set_object(&g_input_context->inputs, SPICE_INPUTS_CHANNEL(channel));
        g_signal_connect(channel, "channel-event",
                         G_CALLBACK(on_inputs_recovery_event), g_input_context);
    }
#ifdef CTFLAB_E2E_TEST
    if (SPICE_IS_INPUTS_CHANNEL(channel)) {
        ClientContext *ctx = (ClientContext *)user_data;
        ctx->inputs_channel = SPICE_INPUTS_CHANNEL(channel);
        g_signal_connect_swapped(channel, "destroy",
                                 G_CALLBACK(on_inputs_channel_destroy), ctx);
    }
#endif
    if (SPICE_IS_DISPLAY_CHANNEL(channel)) {
        g_signal_connect(channel, "notify::monitors",
                         G_CALLBACK(on_guest_monitors_changed), user_data);
        gint channel_id = -1;
        g_object_get(channel, "channel-id", &channel_id, NULL);
        if (channel_id == 0) {
            g_signal_connect(channel, "display-primary-create", G_CALLBACK(on_display_primary_create), user_data);
            g_signal_connect(channel, "display-invalidate", G_CALLBACK(on_display_invalidate), user_data);
            g_signal_connect(channel, "display-primary-destroy", G_CALLBACK(on_display_primary_destroy), user_data);
            SpiceDisplayPrimary primary = {0};
            if (spice_display_channel_get_primary(channel, 0, &primary)) {
                on_display_primary_create(channel, primary.format, primary.width, primary.height,
                                          primary.stride, primary.shmid, NULL, user_data);
            }
        }
        return;
    }
    if (!SPICE_IS_MAIN_CHANNEL(channel)) {
        return;
    }
    ((ClientContext *)user_data)->main_channel = SPICE_MAIN_CHANNEL(channel);
    g_signal_connect(channel, "main-agent-update", G_CALLBACK(on_main_agent_update), user_data);
    g_signal_connect(channel, "notify::mouse-mode", G_CALLBACK(on_mouse_mode_update), user_data);
    /* 极短会话中 agent 可能已先于回调连接，主动检查一次。 */
    on_main_agent_update(SPICE_MAIN_CHANNEL(channel), user_data);
}

#ifdef CTFLAB_E2E_TEST
/* 只编入本机 E2E 测试副本：按计划驱动窗口尺寸与全屏，配合 display-transition
 * 日志测量真实分辨率跟随（frame-matched 即来宾真实 modeset，非拉伸）。
 * 步骤在 agent 连接且绝对鼠标模式就绪（resize-enable 同一组条件）后才开始，
 * 否则启动阶段的门控会静默丢弃尺寸请求。 */
typedef struct {
    GtkWidget *window;
    InputContext *input;
    ClientContext *client;
} E2EDriveContext;

static const struct {
    gint width, height;
    gboolean fullscreen;
} ctflab_drive_plan[] = {
    {1280, 800, FALSE},
    {1600, 1000, FALSE},
    {1000, 700, FALSE},
    {0, 0, TRUE},
    {0, 0, FALSE},
};

static gboolean drive_test_window(gpointer user_data)
{
    static unsigned step = 0;
    static gboolean armed = FALSE;
    E2EDriveContext *drive = user_data;
    if (!armed) {
        if (!drive->client->display_ready || !drive->client->agent_connected ||
            !drive->client->absolute_mouse_ready) {
            return G_SOURCE_CONTINUE; /* 等 vdagent；外层由测试总时长兜底 */
        }
        armed = TRUE;
        fprintf(stderr, "CTFLAB_E2E_TEST drive-start t=%llums\n", mono_ms());
        fflush(stderr);
    }
    if (step >= sizeof(ctflab_drive_plan) / sizeof(ctflab_drive_plan[0])) {
        fprintf(stderr, "CTFLAB_E2E_TEST drive-done t=%llums\n", mono_ms());
        fflush(stderr);
        return G_SOURCE_REMOVE;
    }
    if (ctflab_drive_plan[step].fullscreen) {
        fprintf(stderr, "CTFLAB_E2E_TEST drive-step=%u fullscreen=on t=%llums\n",
                step, mono_ms());
        set_fullscreen_layout(drive->window, TRUE, drive->input);
    } else if (ctflab_drive_plan[step].width > 0) {
        fprintf(stderr, "CTFLAB_E2E_TEST drive-step=%u size=%dx%d t=%llums\n", step,
                ctflab_drive_plan[step].width, ctflab_drive_plan[step].height,
                mono_ms());
        gtk_window_resize(GTK_WINDOW(drive->window), ctflab_drive_plan[step].width,
                          ctflab_drive_plan[step].height);
    } else {
        fprintf(stderr, "CTFLAB_E2E_TEST drive-step=%u fullscreen=off t=%llums\n",
                step, mono_ms());
        set_fullscreen_layout(drive->window, FALSE, drive->input);
    }
    fflush(stderr);
    step++;
    return G_SOURCE_CONTINUE;
}

static GtkWidget *g_client_window; /* 前向声明：定义在 GtkApplication 外壳一节 */

/*
 * 点击链路验证钩子（仅测试副本，CTFLAB_TEST_FRAMES=1）：每 400ms 记录一帧
 * 的 16x9 降采样亮度指纹与窗口位置。外部驱动（CUA 或人工）点击
 * 窗口后，指纹变化证明点击真实到达并改变了来宾画面。
 */
static gboolean log_frame_fingerprint(gpointer user_data)
{
    ClientContext *context = (ClientContext *)user_data;
    if (context->display == NULL || g_client_window == NULL) {
        return G_SOURCE_CONTINUE;
    }
    GdkPixbuf *frame = measured_frame(context->display, "test-fingerprint");
    if (frame == NULL) {
        return G_SOURCE_CONTINUE;
    }
    gint w = gdk_pixbuf_get_width(frame);
    gint h = gdk_pixbuf_get_height(frame);
    gint stride = gdk_pixbuf_get_rowstride(frame);
    gint channels = gdk_pixbuf_get_n_channels(frame);
    const guchar *pixels = gdk_pixbuf_get_pixels(frame);
    static const char digits[] = "0123456789abcdef";
    char hex[16 * 9 * 2 + 1];
    size_t out = 0;
    if (w > 0 && h > 0) {
        for (int gy = 0; gy < 9; gy++) {
            for (int gx = 0; gx < 16; gx++) {
                int sx = (gx * (w - 1)) / 16;
                int sy = (gy * (h - 1)) / 9;
                const guchar *p = pixels + (size_t)sy * stride + (size_t)sx * channels;
                unsigned lum = ((unsigned)p[0] * 3 + (unsigned)p[1] * 6 + (unsigned)p[2]) / 10;
                hex[out++] = digits[(lum >> 4) & 0xf];
                hex[out++] = digits[lum & 0xf];
            }
        }
    }
    hex[out] = '\0';
    g_object_unref(frame);
    gint wx = 0, wy = 0;
    gtk_window_get_position(GTK_WINDOW(g_client_window), &wx, &wy);
    fprintf(stderr,
            "CTFLAB_E2E_TEST frame-fp=%s canvas=%dx%d winpos=%d,%d t=%llums\n",
            hex, w, h, wx, wy, mono_ms());
    fflush(stderr);
    return G_SOURCE_CONTINUE;
}

/*
 * 合成点击钩子（仅测试副本，CTFLAB_TEST_CLICKS=1）：通过 gtk_widget_event
 * 向 SpiceDisplay 直接注入 motion+press+release，走与真实点击完全相同的
 * GTK→spice 坐标变换链（锁屏/无人工干预也能端到端验证点击映射）。
 */
static void synth_pointer_at(ClientContext *context, gint win_x, gint win_y)
{
    GtkWidget *widget = GTK_WIDGET(context->display);
    GdkWindow *toplevel = gtk_widget_get_window(g_client_window);

    GdkEventMotion motion = {0};
    motion.type = GDK_MOTION_NOTIFY;
    motion.window = toplevel;
    motion.send_event = TRUE;
    motion.x = (gdouble)win_x;
    motion.y = (gdouble)win_y;
    motion.x_root = (gdouble)win_x;
    motion.y_root = (gdouble)win_y;
    motion.time = GDK_CURRENT_TIME;
    gtk_widget_event(widget, (GdkEvent *)&motion);

    GdkEventButton press = {0};
    press.type = GDK_BUTTON_PRESS;
    press.window = toplevel;
    press.send_event = TRUE;
    press.x = (gdouble)win_x;
    press.y = (gdouble)win_y;
    press.x_root = (gdouble)win_x;
    press.y_root = (gdouble)win_y;
    press.button = 1;
    press.time = GDK_CURRENT_TIME;
    gtk_widget_event(widget, (GdkEvent *)&press);

    GdkEventButton release = press;
    release.type = GDK_BUTTON_RELEASE;
    gtk_widget_event(widget, (GdkEvent *)&release);

    fprintf(stderr, "CTFLAB_E2E_TEST synth-click win=%d,%d t=%llums\n",
            win_x, win_y, mono_ms());
    fflush(stderr);
}

/* 目标点（guest 坐标）；gx<0 表示先发 Escape。标签含 dbl 双击。 */
typedef struct { gint gx, gy; const char *label; } ClickPlanStep;
static const ClickPlanStep ctflab_click_plan[] = {
    {-2, 0, "dump-before"},
    {35, 53, "dbl home-icon CENTER guest~71,107"},
    {-2, 0, "dump-after-home"},
    {-3, 0, "altf4-close"},
    {8, 7, "click dragon CENTER guest~17,15"},
    {-2, 0, "dump-after-dragon"},
    {-1, 0, "escape"},
};

static gboolean run_click_plan(gpointer user_data)
{
    static guint step = 0;
    ClientContext *context = (ClientContext *)user_data;
    if (!context->agent_connected || !context->display_ready) {
        return G_SOURCE_CONTINUE;
    }
    if (step >= G_N_ELEMENTS(ctflab_click_plan)) {
        fprintf(stderr, "CTFLAB_E2E_TEST synth-done\n");
        fflush(stderr);
        return G_SOURCE_REMOVE;
    }
    GtkAllocation allocation = {0};
    gtk_widget_get_allocation(GTK_WIDGET(context->display), &allocation);
    GdkPixbuf *frame = measured_frame(context->display, "test-click-plan");
    gint cw = frame != NULL ? gdk_pixbuf_get_width(frame) : 0;
    gint ch = frame != NULL ? gdk_pixbuf_get_height(frame) : 0;
    if (frame != NULL) g_object_unref(frame);
    if (cw <= 0 || allocation.width <= 0) {
        return G_SOURCE_CONTINUE;
    }
    /* 等画布与提交值一致（护栏收敛）才开始，确保测的是稳态映射。 */
    if (context->last_config_w > 0 &&
        (cw != context->last_config_w || ch != context->last_config_h)) {
        return G_SOURCE_CONTINUE;
    }
    const ClickPlanStep *plan = &ctflab_click_plan[step];
    if (plan->gx == -2) {
        GdkPixbuf *shot = measured_frame(context->display, "test-dump");
        if (shot != NULL) {
            const char *out = "/tmp/ctflab-guest-frame.png";
            gdk_pixbuf_save(shot, out, "png", NULL, NULL);
            fprintf(stderr, "CTFLAB_E2E_TEST frame-dump %s %dx%d\n", out,
                    gdk_pixbuf_get_width(shot), gdk_pixbuf_get_height(shot));
            fflush(stderr);
            g_object_unref(shot);
        }
        step++;
        return G_SOURCE_CONTINUE;
    }
    if (plan->gx == -3) {
        guint keys[] = { GDK_KEY_Alt_L, GDK_KEY_F4 };
        spice_display_send_keys(context->display, keys, G_N_ELEMENTS(keys),
                                SPICE_DISPLAY_KEY_EVENT_PRESS);
        spice_display_send_keys(context->display, keys, G_N_ELEMENTS(keys),
                                SPICE_DISPLAY_KEY_EVENT_RELEASE);
        fprintf(stderr, "CTFLAB_E2E_TEST synth-step=%u label=%s\n", step, plan->label);
        fflush(stderr);
        step++;
        return G_SOURCE_CONTINUE;
    }
    if (plan->gx < 0) {
        guint keys[] = { GDK_KEY_Escape };
        spice_display_send_keys(context->display, keys, G_N_ELEMENTS(keys),
                                SPICE_DISPLAY_KEY_EVENT_PRESS);
        spice_display_send_keys(context->display, keys, G_N_ELEMENTS(keys),
                                SPICE_DISPLAY_KEY_EVENT_RELEASE);
        fprintf(stderr, "CTFLAB_E2E_TEST synth-step=%u label=%s\n", step, plan->label);
        fflush(stderr);
        step++;
        return G_SOURCE_CONTINUE;
    }
    gint wx = plan->gx;
    gint wy = plan->gy;
    fprintf(stderr, "CTFLAB_E2E_TEST synth-step=%u label=%s win=%d,%d (canvas=%dx%d alloc=%dx%d)\n",
            step, plan->label, wx, wy, cw, ch, allocation.width, allocation.height);
    synth_pointer_at(context, wx, wy);
    if (g_str_has_prefix(plan->label, "dbl")) {
        synth_pointer_at(context, wx, wy);
    }
    step++;
    return G_SOURCE_CONTINUE;
}

#ifdef CTFLAB_E2E_TEST
/* 文件驱动的位置注入：/tmp/ctflab-sendpos 内容 "x y seq"，seq 变化才发送
 * （同内容重复写入不会重发，调用方必须递增 seq），通过 inputs 通道直发绝对
 * 位置（绕过 GTK 事件层），用于判定客户端→来宾指针链路是否真正按预期落点。 */
static gboolean sendpos_watch(gpointer user_data)
{
    ClientContext *context = (ClientContext *)user_data;
    static gchar *last = NULL;
    gchar *content = NULL;
    if (context->inputs_channel == NULL || !SPICE_IS_INPUTS_CHANNEL(context->inputs_channel) ||
        !g_file_get_contents("/tmp/ctflab-sendpos", &content, NULL, NULL)) {
        return G_SOURCE_CONTINUE;
    }
    if (g_strcmp0(content, last) != 0) {
        gint x = 0, y = 0;
        if (sscanf(content, "%d %d", &x, &y) == 2) {
            spice_inputs_channel_position(context->inputs_channel, x, y, 0, 0);
            fprintf(stderr, "CTFLAB_E2E_TEST sentpos %d,%d\n", x, y);
            fflush(stderr);
        }
        g_free(last);
        last = content;
        return G_SOURCE_CONTINUE;
    }
    g_free(content);
    return G_SOURCE_CONTINUE;
}
#endif

static gboolean drive_test_begin(gpointer user_data)
{
    g_timeout_add(4000, drive_test_window, user_data);
    return G_SOURCE_REMOVE;
}

static void display_ready_for_drive(GObject *display,
                                    GParamSpec *property,
                                    gpointer user_data)
{
    gboolean ready = FALSE;
    (void)property;
    g_object_get(display, "ready", &ready, NULL);
    if (ready) {
        /* 最少等 10s（显示 surface 稳定），随后由计时器轮询等 resize-enable 条件。 */
        g_timeout_add(10000, drive_test_begin, user_data);
        g_signal_handlers_disconnect_by_func(display,
                                             display_ready_for_drive,
                                             user_data);
    }
}
#endif

/*
 * GtkApplication 外壳：纯 GtkWindow + gtk_main 在 GTK3 quartz 后端下没有
 * NSApplicationDelegate，Dock 图标点击（applicationShouldHandleReopen）不会
 * 还原最小化窗口。GTK Quartz 自带代理也未实现 reopen，下面补齐缺失回调，
 * 再进入同一 activate 路径；不替换原代理、不覆盖已有回调。
 * NON_UNIQUE 且不带 app id：多个节点同时开客户端互不抢占。
 */
static GtkApplication *g_client_app = NULL;
static GtkWidget *g_client_window = NULL;
static int g_client_argc = 0;
static char **g_client_argv = NULL;
static pid_t g_client_qemu_pid = 0;

#if defined(__APPLE__)
static BOOL native_handle_reopen(id delegate, SEL selector, id application, BOOL visible)
{
    (void)delegate;
    (void)selector;
    (void)application;
    fprintf(stderr, "CTFLAB_SPICE_STATE dock-reopen visible=%d t=%llums\n",
            visible ? 1 : 0, mono_ms());
    if (g_client_app != NULL) {
        g_application_activate(G_APPLICATION(g_client_app));
    }
    return YES;
}

static gboolean add_native_reopen_callback(Class delegate_class)
{
    SEL reopen = sel_registerName("applicationShouldHandleReopen:hasVisibleWindows:");
    if (delegate_class == Nil || class_getInstanceMethod(delegate_class, reopen) != NULL) {
        return FALSE;
    }
    /* 连继承的实现也不能覆盖；未来 GTK 自带实现时保持其行为。 */
    return class_addMethod(delegate_class,
                           reopen,
                           (IMP)native_handle_reopen, "B@:@B");
}

static void install_native_reopen(void)
{
    id application = ((id (*)(Class, SEL))objc_msgSend)(
        objc_getClass("NSApplication"), sel_registerName("sharedApplication"));
    id delegate = ((id (*)(id, SEL))objc_msgSend)(application, sel_registerName("delegate"));
    Class delegate_class = delegate != nil ? object_getClass(delegate) : Nil;
    /* 只扩展我们当前 GTK 应用的代理，不触碰未知第三方代理。 */
    if (delegate_class != Nil &&
        strcmp(class_getName(delegate_class), "GtkApplicationQuartzDelegate") == 0 &&
        add_native_reopen_callback(delegate_class)) {
        fprintf(stderr, "CTFLAB_SPICE_STATE dock-reopen-handler=installed\n");
        fflush(stderr);
    }
}
#else
static void install_native_reopen(void) {}
#endif

static void client_activate(GtkApplication *app, gpointer user_data)
{
    (void)user_data;
    install_native_reopen();
    if (g_client_window != NULL) {
        /* Dock 重新打开：最小化时只去最小化（quartz 上对已最小化窗口
         * present 可能反而把窗口撤下），否则呈现并聚焦。 */
        GdkWindow *gdk_window = gtk_widget_get_window(g_client_window);
        fprintf(stderr, "CTFLAB_SPICE_STATE window-reopen iconified=%d t=%llums\n",
                gdk_window != NULL &&
                (gdk_window_get_state(gdk_window) & GDK_WINDOW_STATE_ICONIFIED) != 0,
                mono_ms());
        fflush(stderr);
        if (gdk_window != NULL &&
            (gdk_window_get_state(gdk_window) & GDK_WINDOW_STATE_ICONIFIED) != 0) {
            gtk_window_deiconify(GTK_WINDOW(g_client_window));
        } else {
            gtk_window_present(GTK_WINDOW(g_client_window));
        }
        return;
    }
    g_application_hold(G_APPLICATION(app));

    const char *uri = uri_argument(g_client_argc, g_client_argv);
    gboolean allow_clipboard = clipboard_argument(g_client_argc, g_client_argv);
    gboolean allow_file_transfer = file_transfer_argument(g_client_argc, g_client_argv);
    gboolean start_fullscreen = fullscreen_argument(g_client_argc, g_client_argv);
    const char *state_file_path = state_file_argument(g_client_argc, g_client_argv);
    gint requested_quality = display_quality_argument(g_client_argc, g_client_argv);
    pid_t qemu_pid = g_client_qemu_pid;
    int qemu_pid_result = qemu_pid > 0 ? 0 : -1;

    SpiceSession *session = spice_session_new();
    QemuWatchContext qemu_watch = {
        .pid = qemu_pid,
        .source_id = 0,
        .quitting = FALSE,
    };
    SessionContext session_context = {
        .qemu = &qemu_watch,
        .session = session,
        .quitting = FALSE,
    };
    g_session_context = &session_context;
    install_quit_signals();
    /* URI 必须先于 password 设置：spice-gtk 的 uri setter 会清空会话口令
     * （实测读回为 NULL），先设 password 后设 uri 会让客户端以空口令认证，
     * TCP 回退模式必然得到 Invalid password。 */
    g_object_set(session, "uri", uri, "enable-audio", FALSE,
                 "enable-usbredir", FALSE, NULL);
    const char *password_file = password_file_argument(g_client_argc, g_client_argv);
    char *ticket = NULL;
    if (password_file != NULL) {
        ticket = read_ticket_file(password_file);
        if (ticket == NULL || *ticket == '\0') {
            fprintf(stderr, "无法读取 SPICE ticket 文件：%s\n", password_file);
            remove_quit_signals();
            g_object_unref(session);
            g_session_context = NULL;
            g_application_release(G_APPLICATION(app));
            return;
        }
        g_object_set(session, "password", ticket, NULL);
        memset(ticket, 0, strlen(ticket));
        g_free(ticket);
        ticket = NULL;
    }
#ifdef CTFLAB_AUTH_DEBUG
    {
        gchar *pw_after_uri = NULL;
        g_object_get(session, "password", &pw_after_uri, NULL);
        fprintf(stderr, "CTFLAB_SPICE_STATE auth-debug password-after-uri len=%zu\n",
                pw_after_uri ? strlen(pw_after_uri) : (size_t)-1);
        g_free(pw_after_uri);
    }
#endif
    /* SpiceDisplay 内部也会取得 GtkSession；剪贴板只接受运行器的显式授权。
     * macOS 下剪贴板由 main channel 接管（见文件顶部说明），必须关闭
     * auto-clipboard，防止 gtk-session 的半失效状态机与我们并发操作。 */
    SpiceGtkSession *gtk_session = spice_gtk_session_get(session);
#if defined(__APPLE__)
    g_object_set(gtk_session, "auto-clipboard", FALSE,
                 "auto-usbredir", FALSE, NULL);
#else
    g_object_set(gtk_session, "auto-clipboard", allow_clipboard,
                 "auto-usbredir", FALSE, NULL);
#endif

    /* connect 同步建立 main channel 对象，再创建 display，避免空通道尺寸更新。 */
    if (!spice_session_connect(session)) {
        fprintf(stderr, "无法连接 SPICE URI：%s\n", uri);
        remove_quit_signals();
        g_object_unref(session);
        g_session_context = NULL;
        g_application_release(G_APPLICATION(app));
        return;
    }

    GtkWidget *window = gtk_window_new(GTK_WINDOW_TOPLEVEL);
    g_client_window = window;
    gtk_window_set_title(GTK_WINDOW(window), "CTFLab Kali");
    gtk_window_set_resizable(GTK_WINDOW(window), TRUE);

    /*
     * 初始几何：显式 --geometry 优先（并忽略记忆的全屏标记）；否则读取
     * --state-file 记忆值；都没有时用 1000x700。越界值在解析阶段已拒绝，
     * 这里只夹到当前显示器范围内。
     */
    WindowGeometry requested = {0};
    gboolean has_requested = geometry_argument(g_client_argc, g_client_argv, &requested);
    WindowGeometry saved = {0};
    gint remembered_quality = -1;
    gboolean has_saved = !has_requested && state_file_path != NULL &&
                         window_state_load(state_file_path, &saved, NULL,
                                           &remembered_quality);
    gint initial_width = has_requested ? requested.width : (has_saved ? saved.width : 1000);
    gint initial_height = has_requested ? requested.height : (has_saved ? saved.height : 700);
    {
        GdkMonitor *monitor = gdk_display_get_primary_monitor(gdk_display_get_default());
        if (monitor != NULL) {
            GdkRectangle geometry = {0};
            gdk_monitor_get_geometry(monitor, &geometry);
            if (geometry.width > 0 && geometry.height > 0) {
                initial_width = MIN(initial_width, geometry.width);
                initial_height = MIN(initial_height, geometry.height);
            }
        }
    }
    gtk_window_set_default_size(GTK_WINDOW(window), initial_width, initial_height);
    if (has_saved && saved.fullscreen) {
        start_fullscreen = TRUE;
    }

    SpiceDisplay *display = spice_display_new(session, 0);
    ClientContext context = {
        .display = display,
        .main_channel = NULL,
        .agent_connected = FALSE,
        .absolute_mouse_ready = FALSE,
        .display_ready = FALSE,
        .resize_timer_id = 0,
        .unstick_timer_id = 0,
        .resize_generation = 0,
        .shield = NULL,
        .shield_canvas = NULL,
        .frozen_frame = NULL,
        .transition_timer_id = 0,
        .transition_deadline = 0,
        .transition_target_w = 0,
        .transition_target_h = 0,
        .last_config_w = 0,
        .last_config_h = 0,
        /* 无显式请求且无记忆时默认流畅（1:1 逻辑分辨率，UI 大小正常）；
         * 清晰优先（Retina 像素密度，UI 变小）需显式选择或沿用记忆。 */
        .pixel_multiplier = requested_quality == 1 ? 1 :
                            (requested_quality == 0 ? -1 :
                             (remembered_quality == 0 ? -1 : 1)),
        .transition_active = FALSE,
    };
    if (context.pixel_multiplier == -1) {
        context.pixel_multiplier = 0; /* 清晰优先：跟随 Retina scale */
    }
    fprintf(stderr, "CTFLAB_SPICE_STATE display-quality=%s\n",
            context.pixel_multiplier == 1 ? "smooth" : "sharp");
    fflush(stderr);
    InputContext input_context = {
        .window = window,
        .fullscreen = FALSE,
        .snooper_id = 0,
        .windowed_width = 0,
        .windowed_height = 0,
        .pressed_count = 0,
        .display = display,
    };
    g_input_context = &input_context;
    /*
     * 保留 spice-gtk 的缩放坐标变换。macOS 高 DPI 下，来宾帧缓冲区、GTK
     * content allocation 与宿主窗口的逻辑像素可能短暂不同；关闭 scaling 会
     * 让画面看似正常但把点击按旧的帧缓冲坐标发送，出现“点 A 打开 B”。
     * 来宾尺寸由 apply_guest_resize 按 allocation × scale_factor 主动发送；
     * scaling 保持开启，确保窗口尺寸变化和输入映射使用同一套变换。
     */
    g_object_set(display, "resize-guest", FALSE,
                 "scaling", TRUE,
                 "only-downscale", FALSE,
                 NULL);
    g_signal_connect(display, "notify::ready", G_CALLBACK(on_display_ready), &context);
    g_signal_connect_after(display, "draw", G_CALLBACK(on_display_draw_trace), &context);
    g_signal_connect_after(display, "size-allocate", G_CALLBACK(on_display_size_allocate), &context);
    /* 用户信号先于 RUN_LAST 的类处理器执行：即使 spice 丢弃越界点击也能留下坐标证据。 */
    g_signal_connect(display, "button-press-event",
                     G_CALLBACK(on_display_button_press), &context);
    g_signal_connect(display, "motion-notify-event", G_CALLBACK(on_display_motion), &context);
    g_signal_connect(display, "button-release-event", G_CALLBACK(on_display_button_release), &context);
    /* 以上观察发生在类处理器之前，只证明收到事件，不证明来宾已执行。
     * 原 input-press-after 也是普通 connect，不能据它判断 spice 的消费结果。 */
    /* overlay 包裹显示区：过渡期覆盖层挡住指针输入并绘制冻结帧。 */
    GtkWidget *overlay = gtk_overlay_new();
    gtk_container_add(GTK_CONTAINER(overlay), GTK_WIDGET(display));
    context.shield = gtk_event_box_new();
    gtk_widget_set_events(context.shield,
                          GDK_BUTTON_PRESS_MASK | GDK_BUTTON_RELEASE_MASK |
                          GDK_POINTER_MOTION_MASK | GDK_SCROLL_MASK);
    g_signal_connect(context.shield, "button-press-event",
                     G_CALLBACK(on_shield_event), &context);
    g_signal_connect(context.shield, "button-release-event",
                     G_CALLBACK(on_shield_event), &context);
    g_signal_connect(context.shield, "motion-notify-event",
                     G_CALLBACK(on_shield_event), &context);
    g_signal_connect(context.shield, "scroll-event",
                     G_CALLBACK(on_shield_event), &context);
    context.shield_canvas = gtk_drawing_area_new();
    g_signal_connect(context.shield_canvas, "draw", G_CALLBACK(on_shield_draw), &context);
    gtk_container_add(GTK_CONTAINER(context.shield), context.shield_canvas);
    gtk_widget_set_hexpand(context.shield, TRUE);
    gtk_widget_set_vexpand(context.shield, TRUE);
    gtk_widget_set_halign(context.shield, GTK_ALIGN_FILL);
    gtk_widget_set_valign(context.shield, GTK_ALIGN_FILL);
    gtk_widget_set_no_show_all(context.shield, TRUE);
    gtk_overlay_add_overlay(GTK_OVERLAY(overlay), context.shield);
    gtk_widget_show(context.shield_canvas);
    gtk_container_add(GTK_CONTAINER(window), overlay);
    if (!allow_file_transfer) {
        /* 文件写入单独授权，与文本剪贴板开关无关。 */
        gtk_drag_dest_unset(GTK_WIDGET(display));
    }

    g_signal_connect(session, "disconnected", G_CALLBACK(on_session_disconnected), &session_context);
    g_signal_connect(session, "channel-new", G_CALLBACK(on_channel_new), &context);
    /* connect 是同步的，main channel 可能早于上面的信号连接就已创建；补扫已有通道。 */
    GList *channels = spice_session_get_channels(session);
    for (GList *item = channels; item != NULL; item = item->next) {
        on_channel_new(session, SPICE_CHANNEL(item->data), &context);
    }
    g_list_free(channels);
    g_signal_connect(window, "delete-event", G_CALLBACK(on_window_delete), &session_context);
    g_signal_connect(window, "configure-event", G_CALLBACK(on_window_configure), &context);
    g_signal_connect(window, "window-state-event", G_CALLBACK(on_window_state), &context);
    g_signal_connect(window, "focus-out-event", G_CALLBACK(on_window_focus_out), &input_context);
    g_signal_connect(window, "focus-in-event", G_CALLBACK(on_window_focus_in), &context);
    g_signal_connect(window, "grab-broken-event", G_CALLBACK(on_window_grab_broken),
                     &input_context);
    GdkScreen *screen = gdk_screen_get_default();
    if (screen != NULL) {
        g_signal_connect(screen, "monitors-changed",
                         G_CALLBACK(on_screen_geometry_changed), &input_context);
        g_signal_connect(screen, "size-changed",
                         G_CALLBACK(on_screen_geometry_changed), &input_context);
    }
#if defined(__APPLE__)
    if (allow_clipboard) {
        host_clipboard_start(context.main_channel);
    }
#endif
    if (qemu_pid_result > 0) {
        qemu_watch.source_id = g_timeout_add(250, watch_qemu_process, &session_context);
    }
    gtk_widget_show_all(window);
    if (start_fullscreen) {
        /* quartz 后端在 show 之后立即 fullscreen 不生效，等 map 完成再应用 */
        g_timeout_add(300, apply_start_fullscreen, &input_context);
    }
    /* 极快连接中 ready 可能先于 show 后的通知，主动同步一次当前状态。 */
    on_display_ready(G_OBJECT(display), NULL, &context);

    /* GTK3 中 snooper 仍是唯一能在 SpiceDisplay 消费按键之前看到事件的入口
     * （GTK4 移除）；本项目锁定 GTK3，故显式关闭该废弃告警。 */
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
    input_context.snooper_id = gtk_key_snooper_install(input_key_snooper,
                                                       &input_context);
#pragma clang diagnostic pop

#ifdef CTFLAB_E2E_TEST
#ifdef CTFLAB_E2E_TEST
    if (getenv("CTFLAB_TEST_SENDPOS") != NULL) {
        g_timeout_add(500, sendpos_watch, &context);
    }
#endif
    if (getenv("CTFLAB_TEST_FRAMES") != NULL) {
        g_timeout_add(400, log_frame_fingerprint, &context);
    }
    if (getenv("CTFLAB_TEST_CLICKS") != NULL) {
        /* 等就绪后按 1.5s 步进执行合成点击计划。 */
        g_timeout_add(1500, run_click_plan, &context);
    }
    if (getenv("CTFLAB_TEST_RESIZE") != NULL) {
        /* 回调真正只在 ready 后启用；环境变量仅存在于测试副本。 */
        static E2EDriveContext drive_context;
        drive_context.window = window;
        drive_context.input = &input_context;
        drive_context.client = &context;
        g_signal_connect(display, "notify::ready",
                         G_CALLBACK(display_ready_for_drive), &drive_context);
    }
#endif

    gtk_main();
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
    gtk_key_snooper_remove(input_context.snooper_id);
#pragma clang diagnostic pop
    input_context.snooper_id = 0;
    /* 有界等待轮询线程退出并按需释放剪贴板状态；未启用时为空操作。 */
    host_clipboard_shutdown();
    if (context.redraw_idle_id != 0) {
        g_source_remove(context.redraw_idle_id);
        context.redraw_idle_id = 0;
    }
    if (context.resize_timer_id != 0) {
        g_source_remove(context.resize_timer_id);
        context.resize_timer_id = 0;
    }
    if (context.unstick_timer_id != 0) {
        g_source_remove(context.unstick_timer_id);
        context.unstick_timer_id = 0;
    }
    if (context.transition_timer_id != 0) {
        g_source_remove(context.transition_timer_id);
        context.transition_timer_id = 0;
    }
    if (context.frame_check_idle_id != 0) {
        g_source_remove(context.frame_check_idle_id);
        context.frame_check_idle_id = 0;
    }
    g_clear_pointer(&context.frozen_frame, g_object_unref);
    if (qemu_watch.source_id != 0) {
        g_source_remove(qemu_watch.source_id);
        qemu_watch.source_id = 0;
    }
    input_cancel_scancode_reset(&input_context);
    if (input_context.inputs != NULL)
        g_signal_handlers_disconnect_by_data(input_context.inputs, &input_context);
    g_clear_object(&input_context.inputs);
    g_input_context = NULL;
    g_session_context = NULL;
    if (state_file_path != NULL) {
        gint width = 0, height = 0;
        gtk_window_get_size(GTK_WINDOW(window), &width, &height);
        if (input_context.fullscreen && input_context.windowed_width > 0 &&
            input_context.windowed_height > 0) {
            /* 全屏退出时记录窗口化尺寸，下次启动先恢复窗口再进全屏。 */
            width = input_context.windowed_width;
            height = input_context.windowed_height;
        }
        window_state_save(state_file_path, width, height, input_context.fullscreen,
                          gtk_widget_get_scale_factor(window),
                          context.pixel_multiplier);
    }
    /* 栈上会话上下文不能留给后续 disconnected 通知使用。 */
    g_signal_handlers_disconnect_by_data(session, &session_context);
    g_object_unref(session);
    remove_quit_signals();
    fprintf(stderr, "CTFLAB_SPICE_STATE quit-cleanup-complete\n");
    fflush(stderr);
    g_client_window = NULL;
    g_application_release(G_APPLICATION(app));
}

int main(int argc, char **argv)
{
    const char *uri = uri_argument(argc, argv);
    gboolean allow_clipboard = clipboard_argument(argc, argv);
    gboolean allow_file_transfer = file_transfer_argument(argc, argv);
    gboolean start_fullscreen = fullscreen_argument(argc, argv);
    const char *state_file_path = state_file_argument(argc, argv);
    gint requested_quality = display_quality_argument(argc, argv);
    pid_t qemu_pid = 0;
    int qemu_pid_result = qemu_pid_argument(argc, argv, &qemu_pid);
    (void)allow_clipboard;
    (void)allow_file_transfer;
    (void)start_fullscreen;
    (void)state_file_path;
    (void)requested_quality;
    if (uri == NULL || *uri == '\0') {
        fprintf(stderr, "用法：ctflab-spicy --uri spice+unix:///path/to/display.sock [--clipboard] [--qemu-pid PID] [--password-file PATH] [--fullscreen] [--geometry WxH] [--state-file PATH]\n");
        return 2;
    }
    if (qemu_pid_result < 0) {
        fprintf(stderr, "--qemu-pid 必须是正整数。\n");
        return 2;
    }

    g_client_argc = argc;
    g_client_argv = argv;
    g_client_qemu_pid = qemu_pid > 0 ? qemu_pid : 0;
    GtkApplication *app = gtk_application_new(NULL, G_APPLICATION_NON_UNIQUE);
#if defined(__APPLE__)
    /* Quartz 仅在 register-session 时建立 NSApplicationDelegate；否则 Dock
     * 重开事件没有接收方。这是本应用的原生生命周期，不是共享/认证授权。 */
    g_object_set(app, "register-session", TRUE, NULL);
#endif
    g_client_app = app;
    g_signal_connect(app, "activate", G_CALLBACK(client_activate), NULL);
    int status = g_application_run(G_APPLICATION(app), 0, NULL);
    g_object_unref(app);
    g_client_app = NULL;
    return status;
}
