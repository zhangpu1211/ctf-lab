/*
 * CTFLab 受控 SPICE 图形客户端。
 *
 * 这个小客户端只接收运行器传入的固定 --uri 参数，不接受 QEMU 参数；关键的
 * agent 和绝对鼠标模式就绪后才开启 resize-guest，并合并拖动过程的连续尺寸事件，
 * 使 spice-gtk 向来宾发送最终的 monitors config。剪贴板必须由运行器显式传入
 * --clipboard 才开启；USB 自动重定向与文件拖入始终关闭。
 *
 * 项目代码按 MIT 发布；编译时动态链接系统中的 spice-gtk/GTK，随 App 打包时
 * 由构建器收集并校验对应的第三方动态库与许可证文本。
 */

#include <gtk/gtk.h>
#include <spice-client-gtk.h>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <signal.h>
#include <unistd.h>

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

static void request_client_quit(SessionContext *context, SpiceSession *session)
{
    if (context->quitting) {
        return;
    }
    context->quitting = TRUE;
    fprintf(stderr, "CTFLAB_SPICE_STATE quit-requested\\n");
    fflush(stderr);
    spice_session_disconnect(session);
    gtk_main_quit();
}

static void on_session_disconnected(SpiceSession *session, gpointer user_data)
{
    SessionContext *context = (SessionContext *)user_data;
    fprintf(stderr, "CTFLAB_SPICE_STATE disconnected\\n");
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

static gboolean watch_qemu_process(gpointer user_data)
{
    SessionContext *context = (SessionContext *)user_data;
    pid_t qemu_pid = context->qemu->pid;
    if (kill(qemu_pid, 0) == 0 || errno == EPERM) {
        return G_SOURCE_CONTINUE;
    }
    if (errno == ESRCH) {
        fprintf(stderr, "CTFLAB_SPICE_STATE qemu-exited pid=%d\n", (int)qemu_pid);
        fflush(stderr);
        request_client_quit(context, context->session);
        context->qemu->source_id = 0;
        return G_SOURCE_REMOVE;
    }
    return G_SOURCE_CONTINUE;
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
    guint resize_generation;
} ClientContext;

typedef struct {
    ClientContext *context;
    guint generation;
} ResizeTimerContext;

static void apply_guest_resize(ClientContext *context)
{
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
     * GTK 的 allocation 是逻辑像素；来宾显示应使用 Retina 设备像素。
     * 直接调用 update_display，避免 resize-guest 内部再次按逻辑像素发送
     * monitors config，同时保留 SpiceDisplay 的缩放输入变换。
     */
    width = MAX(640, allocation.width * scale_factor);
    height = MAX(480, allocation.height * scale_factor);
    fprintf(stderr,
            "CTFLAB_SPICE_STATE resize-target logical=%dx%d scale=%d physical=%dx%d\\n",
            allocation.width, allocation.height, scale_factor, width, height);
    fflush(stderr);
    spice_main_channel_update_display(context->main_channel, 0, 0, 0,
                                      width, height, TRUE);
}

static gboolean enable_guest_resize(gpointer user_data)
{
    ResizeTimerContext *timer = (ResizeTimerContext *)user_data;
    ClientContext *context = timer->context;
    gboolean current = timer->generation == context->resize_generation;
    if (current && context->display_ready && context->agent_connected &&
        context->absolute_mouse_ready) {
        context->resize_timer_id = 0;
        fprintf(stderr, "CTFLAB_SPICE_STATE resize-enable generation=%u\\n", timer->generation);
        fflush(stderr);
        apply_guest_resize(context);
    }
    g_free(timer);
    return G_SOURCE_REMOVE;
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
    if (context->resize_timer_id != 0) {
        g_source_remove(context->resize_timer_id);
        context->resize_timer_id = 0;
    }
    context->resize_generation++;
    /* 在用户继续拖动时先抑制中间尺寸；计时器只会应用最后一个尺寸。 */
    g_object_set(context->display, "resize-guest", FALSE, NULL);
    ResizeTimerContext *timer = g_new0(ResizeTimerContext, 1);
    timer->context = context;
    timer->generation = context->resize_generation;
    context->resize_timer_id = g_timeout_add(180, enable_guest_resize, timer);
}

static gboolean on_window_configure(GtkWidget *window, GdkEventConfigure *event,
                                    gpointer user_data)
{
    (void)window;
    (void)event;
    ClientContext *context = (ClientContext *)user_data;
    fprintf(stderr, "CTFLAB_SPICE_STATE configure generation=%u\\n", context->resize_generation + 1);
    fflush(stderr);
    schedule_guest_resize(context);
    return FALSE;
}

static void update_mouse_mode(SpiceMainChannel *channel, ClientContext *context)
{
    gboolean agent_connected = FALSE;
    gint mouse_mode = 0;
    g_object_get(channel, "agent-connected", &agent_connected, NULL);
    g_object_get(channel, "mouse-mode", &mouse_mode, NULL);
    context->agent_connected = agent_connected;
    fprintf(stderr, "CTFLAB_SPICE_STATE agent=%d mouse-mode=%d\\n", agent_connected ? 1 : 0, mouse_mode);
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

static void on_main_agent_update(SpiceMainChannel *channel, gpointer user_data)
{
    update_mouse_mode(channel, (ClientContext *)user_data);
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
    fprintf(stderr, "CTFLAB_SPICE_STATE display-ready=%d\\n", ready ? 1 : 0);
    fflush(stderr);
    schedule_guest_resize(context);
}

static void on_channel_new(SpiceSession *session, SpiceChannel *channel, gpointer user_data)
{
    (void)session;
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
static gboolean resize_test_window(gpointer user_data)
{
    /* 只编入本机 E2E 测试副本：通过真实 GTK resize 事件触发 monitors config。 */
    GtkWindow *window = GTK_WINDOW(user_data);
    static unsigned step = 0;
    gtk_window_resize(window, step % 2 == 0 ? 1000 : 800,
                      step % 2 == 0 ? 700 : 600);
    step++;
    gint width = 0;
    gint height = 0;
    gtk_window_get_size(window, &width, &height);
    fprintf(stderr, "CTFLAB_E2E_TEST prior-window=%dx%d\n", width, height);
    fflush(stderr);
    return step < 12 ? G_SOURCE_CONTINUE : G_SOURCE_REMOVE;
}

static void display_ready_for_resize(GObject *display,
                                     GParamSpec *property,
                                     gpointer user_data)
{
    gboolean ready = FALSE;
    (void)property;
    g_object_get(display, "ready", &ready, NULL);
    if (ready) {
        /* 等来宾桌面已就绪后再缩放，避免把启动阶段的最小窗口误当成结果。 */
        g_timeout_add(15000, resize_test_window, user_data);
        g_signal_handlers_disconnect_by_func(display,
                                             display_ready_for_resize,
                                             user_data);
    }
}
#endif

int main(int argc, char **argv)
{
    const char *uri = uri_argument(argc, argv);
    gboolean allow_clipboard = clipboard_argument(argc, argv);
    pid_t qemu_pid = 0;
    int qemu_pid_result = qemu_pid_argument(argc, argv, &qemu_pid);
    if (uri == NULL || *uri == '\0') {
        fprintf(stderr, "用法：ctflab-spicy --uri spice+unix:///path/to/display.sock [--clipboard] [--qemu-pid PID]\n");
        return 2;
    }
    if (qemu_pid_result < 0) {
        fprintf(stderr, "--qemu-pid 必须是正整数。\n");
        return 2;
    }

    gtk_init(&argc, &argv);

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
    g_object_set(session, "uri", uri, "enable-audio", FALSE,
                 "enable-usbredir", FALSE, NULL);
    /* SpiceDisplay 内部也会取得 GtkSession；剪贴板只接受运行器的显式授权。 */
    SpiceGtkSession *gtk_session = spice_gtk_session_get(session);
    g_object_set(gtk_session, "auto-clipboard", allow_clipboard,
                 "auto-usbredir", FALSE, NULL);

    /* connect 同步建立 main channel 对象，再创建 display，避免空通道尺寸更新。 */
    if (!spice_session_connect(session)) {
        fprintf(stderr, "无法连接 SPICE URI：%s\n", uri);
        g_object_unref(session);
        return 1;
    }

    GtkWidget *window = gtk_window_new(GTK_WINDOW_TOPLEVEL);
    gtk_window_set_title(GTK_WINDOW(window), "CTFLab Kali");
    gtk_window_set_resizable(GTK_WINDOW(window), TRUE);
    gtk_window_set_default_size(GTK_WINDOW(window), 1000, 700);

    SpiceDisplay *display = spice_display_new(session, 0);
    ClientContext context = {
        .display = display,
        .main_channel = NULL,
        .agent_connected = FALSE,
        .absolute_mouse_ready = FALSE,
        .display_ready = FALSE,
        .resize_timer_id = 0,
        .resize_generation = 0,
    };
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
    gtk_container_add(GTK_CONTAINER(window), GTK_WIDGET(display));
    gtk_drag_dest_unset(GTK_WIDGET(display));

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
    if (qemu_pid_result > 0) {
        qemu_watch.source_id = g_timeout_add(250, watch_qemu_process, &session_context);
    }
    gtk_widget_show_all(window);
    /* 极快连接中 ready 可能先于 show 后的通知，主动同步一次当前状态。 */
    on_display_ready(G_OBJECT(display), NULL, &context);

#ifdef CTFLAB_E2E_TEST
    if (getenv("CTFLAB_TEST_RESIZE") != NULL) {
        /* 回调真正只在 ready 后启用；环境变量仅存在于测试副本。 */
        g_signal_connect(display, "notify::ready", G_CALLBACK(display_ready_for_resize), window);
    }
#endif

    gtk_main();
    if (context.resize_timer_id != 0) {
        g_source_remove(context.resize_timer_id);
        context.resize_timer_id = 0;
    }
    if (qemu_watch.source_id != 0) {
        g_source_remove(qemu_watch.source_id);
        qemu_watch.source_id = 0;
    }
    g_object_unref(session);
    return 0;
}
