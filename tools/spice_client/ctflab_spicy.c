/*
 * CTFLab 受控 SPICE 图形客户端。
 *
 * 这个小客户端只接收运行器传入的固定 --uri 参数，不接受 QEMU 参数；关键的
 * resize-guest 属性显式设为 TRUE，使 spice-gtk 在窗口尺寸变化时向来宾发送
 * monitors config。显式关闭客户端剪贴板共享、USB 自动重定向与文件拖入。
 *
 * 项目代码按 MIT 发布；编译时动态链接系统中的 spice-gtk/GTK，随 App 打包时
 * 由构建器收集并校验对应的第三方动态库与许可证文本。
 */

#include <gtk/gtk.h>
#include <spice-client-gtk.h>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void on_session_disconnected(SpiceSession *session, gpointer user_data)
{
    (void)session;
    (void)user_data;
    gtk_main_quit();
}

static gboolean on_window_delete(GtkWidget *window, GdkEvent *event, gpointer user_data)
{
    SpiceSession *session = SPICE_SESSION(user_data);
    (void)window;
    (void)event;
    /* 先断开来宾显示通道，再退出 GTK 主循环；QEMU 的生命周期由 CTFLab 管理。 */
    spice_session_disconnect(session);
    gtk_main_quit();
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
    if (uri == NULL || *uri == '\0') {
        fprintf(stderr, "用法：ctflab-spicy --uri spice+unix:///path/to/display.sock\n");
        return 2;
    }

    gtk_init(&argc, &argv);

    SpiceSession *session = spice_session_new();
    g_object_set(session, "uri", uri, "enable-audio", FALSE,
                 "enable-usbredir", FALSE, NULL);
    /* SpiceDisplay 内部也会取得 GtkSession，必须显式关闭共享默认值。 */
    SpiceGtkSession *gtk_session = spice_gtk_session_get(session);
    g_object_set(gtk_session, "auto-clipboard", FALSE, "auto-usbredir", FALSE, NULL);

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
    /* 这是动态分辨率的开关；FALSE 会退化为只缩放画面。 */
    g_object_set(display, "resize-guest", TRUE, "scaling", FALSE, NULL);
    gtk_container_add(GTK_CONTAINER(window), GTK_WIDGET(display));
    gtk_drag_dest_unset(GTK_WIDGET(display));

    g_signal_connect(session, "disconnected", G_CALLBACK(on_session_disconnected), NULL);
    g_signal_connect(window, "delete-event", G_CALLBACK(on_window_delete), session);
    gtk_widget_show_all(window);

#ifdef CTFLAB_E2E_TEST
    if (getenv("CTFLAB_TEST_RESIZE") != NULL) {
        /* 回调真正只在 ready 后启用；环境变量仅存在于测试副本。 */
        g_signal_connect(display, "notify::ready", G_CALLBACK(display_ready_for_resize), window);
    }
#endif

    gtk_main();
    g_object_unref(session);
    return 0;
}
