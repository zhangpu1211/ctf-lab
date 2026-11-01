"""直接编译并运行客户端输入/几何辅助逻辑；不连接 SPICE、不创建窗口。"""

from pathlib import Path
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "spice_client/ctflab_spicy.c"

HARNESS = r"""
#include <spice-client-gtk.h>
static guint reset_release_codes[256];
static guint reset_release_count;
static void capture_reset_release(SpiceInputsChannel *channel, guint code) {
    g_assert_nonnull(channel);
    g_assert_cmpuint(code, >, 0);
    g_assert_cmpuint(code, <=, 0x58);
    reset_release_codes[code]++;
    reset_release_count++;
}
#define spice_inputs_channel_key_release capture_reset_release
#define main ctflab_client_main
#include "SOURCE_PATH"
#undef main

int main(int argc, char **argv) {
    g_assert_cmpint(argc, ==, 2);
    const char *mode = argv[1];
    if (strcmp(mode, "untracked-reset") == 0) {
        InputContext input = {0};
        input_reset_untracked_keys(&input);
        g_assert_cmpuint(reset_release_count, ==, 0);
        SpiceSession *session = spice_session_new();
        SpiceChannel *channel = spice_channel_new(session, SPICE_CHANNEL_INPUTS, 0);
        input.inputs = SPICE_INPUTS_CHANNEL(channel);
        /* 跟踪集合为空也必须释放实际扫描码 a (0x1e)。 */
        input_reset_untracked_keys(&input);
        g_assert_cmpuint(reset_release_count, ==, 1); /* 不再突发 88 项 */
        g_assert_cmpuint(reset_release_codes[0x1e], ==, 1);
        on_inputs_recovery_event(channel, SPICE_CHANNEL_CLOSED, &input);
        g_assert_cmpuint(input.reset_source_id, ==, 0);
        g_assert_cmpuint(reset_release_count, ==, 1);
        on_inputs_recovery_event(channel, SPICE_CHANNEL_OPENED, &input);
        g_assert_cmpuint(reset_release_count, ==, 2);
        gint64 started = g_get_monotonic_time();
        while (input.reset_source_id != 0) {
            guint before = reset_release_count;
            g_main_context_iteration(NULL, TRUE);
            g_assert_cmpuint(reset_release_count - before, <=, 1);
        }
        g_assert_cmpint(g_get_monotonic_time() - started, >=, 2000000);
        g_assert_cmpuint(reset_release_count, ==, 89);
        for (guint code = 1; code <= 0x58; code++)
            g_assert_cmpuint(reset_release_codes[code], ==, code == 0x1e ? 2 : 1);
        input_reset_untracked_keys(&input);
        GdkEventKey key = {.type = GDK_KEY_PRESS, .keyval = GDK_KEY_b};
        g_assert_false(input_key_snooper(NULL, &key, &input));
        g_assert_cmpuint(input.reset_source_id, ==, 0); /* 不干扰新的真实输入 */
        g_object_unref(session);
        return 0;
    }
    if (strcmp(mode, "native-reopen") == 0) {
#if defined(__APPLE__)
        Class delegate_class = objc_allocateClassPair(objc_getClass("NSObject"),
                                                      "CTFLabReopenUnitDelegate", 0);
        g_assert_nonnull(delegate_class);
        objc_registerClassPair(delegate_class);
        g_assert_false(add_native_reopen_callback(Nil));
        g_assert_true(add_native_reopen_callback(delegate_class));
        SEL selector = sel_registerName("applicationShouldHandleReopen:hasVisibleWindows:");
        IMP original = class_getMethodImplementation(delegate_class, selector);
        g_assert_false(add_native_reopen_callback(delegate_class));
        g_assert_true(original == class_getMethodImplementation(delegate_class, selector));
        g_assert_true(native_handle_reopen(nil, selector, nil, NO));
        Class inherited = objc_allocateClassPair(delegate_class, "CTFLabReopenUnitChild", 0);
        objc_registerClassPair(inherited);
        g_assert_false(add_native_reopen_callback(inherited));
        g_assert_true(original == class_getMethodImplementation(inherited, selector));
        objc_disposeClassPair(inherited);
        objc_disposeClassPair(delegate_class);
#endif
        return 0;
    }
    if (strcmp(mode, "content-allocation") == 0) {
        ClientContext context = {0};
        GtkAllocation allocation = {.width = 1512, .height = 949};
        on_display_size_allocate(NULL, &allocation, &context);
        g_assert_cmpint(context.allocated_height, ==, 949);
        g_assert_cmpuint(context.resize_timer_id, ==, 0); /* 未就绪不得提交 */
        allocation.height = 917;
        on_display_size_allocate(NULL, &allocation, &context);
        g_assert_cmpint(context.allocated_height, ==, 917);
        on_display_size_allocate(NULL, &allocation, &context);
        g_assert_cmpuint(context.resize_generation, ==, 0);
        allocation.height = 0;
        on_display_size_allocate(NULL, &allocation, &context);
        g_assert_cmpint(context.allocated_height, ==, 917);
        return 0;
    }
    if (strcmp(mode, "canvas-metadata") == 0) {
        ClientContext context = {.last_config_w = 2000, .last_config_h = 1500,
                                 .transition_active = TRUE, .transition_damage_seen = TRUE};
        on_display_primary_create(NULL, 0, 1280, 800, 0, 0, NULL, &context);
        g_assert_cmpint(context.canvas_width, ==, 1280);
        g_assert_cmpint(context.canvas_height, ==, 800);
        g_assert_false(context.transition_damage_seen);
        g_assert_true(context.transition_active);
        g_assert_cmpint(context.last_config_w, ==, 2000);
        on_display_primary_destroy(NULL, &context);
        g_assert_cmpint(context.canvas_width, ==, 0);
        g_assert_cmpint(context.canvas_height, ==, 0);
        on_display_primary_create(NULL, 0, -1, 800, 0, 0, NULL, &context);
        g_assert_cmpint(context.canvas_height, ==, 0);
        on_display_primary_create(NULL, 0, 1512, 917, 0, 0, NULL, &context);
        g_assert_cmpint(context.canvas_width, ==, 1512);
        g_assert_cmpint(context.canvas_height, ==, 917);
        return 0;
    }
    if (strcmp(mode, "host-command") == 0) {
        InputContext input = {0};
        GdkEventKey key = {.type = GDK_KEY_PRESS, .keyval = GDK_KEY_Meta_L};
        g_assert_true(input_key_snooper(NULL, &key, &input));
        key.keyval = GDK_KEY_Tab; key.state = GDK_META_MASK;
        g_assert_true(input_key_snooper(NULL, &key, &input));
        g_assert_cmpint(input.pressed_count, ==, 0);
        on_window_focus_out(NULL, NULL, &input);
        key.keyval = GDK_KEY_Meta_L; key.type = GDK_KEY_RELEASE; key.state = 0;
        g_assert_true(input_key_snooper(NULL, &key, &input));
        key.keyval = GDK_KEY_Tab;
        g_assert_true(input_key_snooper(NULL, &key, &input));
        g_assert_cmpint(input.host_release_count, ==, 0);
        /* 普通 Tab 和 Ctrl+Tab 仍完整转发给来宾。 */
        key.type = GDK_KEY_PRESS; key.state = GDK_CONTROL_MASK;
        g_assert_false(input_key_snooper(NULL, &key, &input));
        key.type = GDK_KEY_RELEASE;
        g_assert_false(input_key_snooper(NULL, &key, &input));
        /* Command+C/V 仍走显式 Ctrl 桥接，release 不再孤立漏入来宾。 */
        for (guint letter = GDK_KEY_c; letter <= GDK_KEY_v; letter += GDK_KEY_v - GDK_KEY_c) {
            key.type = GDK_KEY_PRESS; key.keyval = letter; key.state = GDK_SUPER_MASK;
            g_assert_true(input_key_snooper(NULL, &key, &input));
            key.type = GDK_KEY_RELEASE; key.state = 0;
            g_assert_true(input_key_snooper(NULL, &key, &input));
        }
        /* 宿主吞掉 release 后的下一个普通按键不能被误吞。 */
        key.type = GDK_KEY_PRESS; key.keyval = GDK_KEY_Tab; key.state = GDK_META_MASK;
        g_assert_true(input_key_snooper(NULL, &key, &input));
        key.state = 0;
        g_assert_false(input_key_snooper(NULL, &key, &input));
        key.type = GDK_KEY_RELEASE;
        g_assert_false(input_key_snooper(NULL, &key, &input));
        g_assert_cmpint(input.pressed_count, ==, 0);
        return 0;
    }
    if (strcmp(mode, "focus-key-trace") == 0) {
        InputContext input = {0};
        g_setenv("CTFLAB_TRACE_DISPLAY_RECOVERY", "1", TRUE);
        GdkEventKey key = {.type = GDK_KEY_PRESS, .keyval = GDK_KEY_Tab};
        g_assert_false(input_key_snooper(NULL, &key, &input));
        key.type = GDK_KEY_RELEASE;
        g_assert_false(input_key_snooper(NULL, &key, &input));
        key.keyval = GDK_KEY_a; /* 普通字符不进入恢复日志。 */
        g_assert_false(input_key_snooper(NULL, &key, &input));
        g_assert_false(on_window_focus_out(NULL, NULL, &input));
        g_assert_cmpint(input.pressed_count, ==, 0);
        g_unsetenv("CTFLAB_TRACE_DISPLAY_RECOVERY");
        return 0;
    }
    if (strcmp(mode, "recovery-first-events") == 0) {
        ClientContext context = {0};
        g_unsetenv("CTFLAB_TRACE_DISPLAY_RECOVERY");
        begin_recovery_trace(&context, "test");
        g_assert_false(context.recovery_trace_pending);
        g_assert_cmpuint(context.recovery_trace_cycle, ==, 0);
        g_setenv("CTFLAB_TRACE_DISPLAY_RECOVERY", "1", TRUE);
        begin_recovery_trace(&context, "test");
        g_assert_true(context.recovery_trace_pending);
        on_display_draw_trace(NULL, NULL, &context); /* 先绘制旧帧不能完成测量。 */
        g_assert_true(context.recovery_trace_pending);
        on_display_invalidate(NULL, 0, 0, 0, 0, &context);
        g_assert_cmpint(context.recovery_trace_damage_mono, ==, 0);
        on_display_invalidate(NULL, 0, 0, 640, 480, &context);
        gint64 first = context.recovery_trace_damage_mono;
        g_assert_cmpint(first, >, 0);
        on_display_invalidate(NULL, 0, 0, 640, 480, &context);
        g_assert_cmpint(context.recovery_trace_damage_mono, ==, first);
        context.recovery_draw_log_mono = g_get_monotonic_time(); /* 普通日志会被限流。 */
        on_display_draw_trace(NULL, NULL, &context);
        g_assert_false(context.recovery_trace_pending); /* 关键首个绘制仍完成记录。 */
        begin_recovery_trace(&context, "next");
        g_assert_cmpuint(context.recovery_trace_cycle, ==, 2);
        g_assert_cmpint(context.recovery_trace_damage_mono, ==, 0);
        g_assert_cmpuint(context.resize_generation, ==, 0);
        g_unsetenv("CTFLAB_TRACE_DISPLAY_RECOVERY");
        return 0;
    }
    if (strcmp(mode, "focus-first-damage") == 0) {
        ClientContext context = {.transition_active = TRUE};
        on_window_focus_in(NULL, NULL, &context);
        g_assert_true(context.focus_damage_redraw_pending);
        while (g_main_context_iteration(NULL, FALSE)) {}
        g_assert_cmpuint(context.redraw_idle_id, ==, 0);
        on_display_invalidate(NULL, 0, 0, 0, 0, &context);
        g_assert_true(context.focus_damage_redraw_pending);
        on_display_invalidate(NULL, 0, 0, 640, 480, &context);
        g_assert_false(context.focus_damage_redraw_pending);
        g_assert_cmpuint(context.redraw_idle_id, !=, 0);
        while (g_main_context_iteration(NULL, FALSE)) {}
        on_display_invalidate(NULL, 0, 0, 640, 480, &context);
        g_assert_cmpuint(context.redraw_idle_id, ==, 0); /* 不在每帧上补刷。 */
        g_assert_true(context.transition_active);
        g_assert_cmpuint(context.resize_generation, ==, 0);
        on_window_focus_in(NULL, NULL, &context);
        g_assert_true(context.focus_damage_redraw_pending);
        while (g_main_context_iteration(NULL, FALSE)) {}
        context.focus_damage_redraw_pending = FALSE;
        GdkEventMotion motion = {0};
        g_assert_false(on_display_motion(NULL, &motion, &context));
        g_assert_true(context.focus_damage_redraw_pending); /* 已有焦点也能预约首帧重绘。 */
        context.focus_damage_redraw_pending = FALSE;
        context.last_motion_mono = g_get_monotonic_time();
        on_display_motion(NULL, &motion, &context);
        g_assert_false(context.focus_damage_redraw_pending); /* 连续移动不每次预约。 */
        context.last_motion_mono -= 2 * G_USEC_PER_SEC;
        on_display_motion(NULL, &motion, &context);
        g_assert_true(context.focus_damage_redraw_pending);
        return 0;
    }
    if (strcmp(mode, "recovery-trace") == 0) {
        gint64 last = 0;
        g_unsetenv("CTFLAB_TRACE_DISPLAY_RECOVERY");
        trace_display_recovery("test", &last, 1000);
        g_assert_cmpint(last, ==, 0); /* 默认关闭，不改诊断状态。 */
        g_setenv("CTFLAB_TRACE_DISPLAY_RECOVERY", "1", TRUE);
        trace_display_recovery("test", &last, 1000);
        g_assert_cmpint(last, >, 0);
        gint64 first = last;
        trace_display_recovery("test", &last, 1000);
        g_assert_cmpint(last, ==, first); /* 同一阶段限流。 */
        ClientContext context = {.transition_active = TRUE};
        g_assert_false(on_display_draw_trace(NULL, NULL, &context));
        g_assert_cmpint(context.recovery_draw_log_mono, >, 0);
        on_display_invalidate(NULL, 0, 0, 0, 0, &context);
        g_assert_cmpint(context.recovery_damage_log_mono, ==, 0);
        on_display_invalidate(NULL, 0, 0, 640, 480, &context);
        g_assert_cmpint(context.recovery_damage_log_mono, >, 0);
        g_assert_true(context.transition_active);
        g_assert_cmpuint(context.resize_generation, ==, 0);
        g_unsetenv("CTFLAB_TRACE_DISPLAY_RECOVERY");
        return 0;
    }
    if (strcmp(mode, "redraw-coalesce") == 0) {
        ClientContext context = {0};
        context.transition_active = TRUE;
        for (int i = 0; i < 2000; i++) {
            g_assert_false(on_window_focus_in(NULL, NULL, &context));
            g_assert_cmpuint(context.redraw_idle_id, !=, 0);
        }
        guint source = context.redraw_idle_id;
        queue_display_redraw(&context);
        g_assert_cmpuint(context.redraw_idle_id, ==, source);
        while (g_main_context_iteration(NULL, FALSE)) {}
        g_assert_cmpuint(context.redraw_idle_id, ==, 0);
        g_assert_true(context.transition_active);
        g_assert_cmpuint(context.resize_generation, ==, 0);
        queue_display_redraw(&context);
        g_assert_cmpuint(context.redraw_idle_id, !=, 0);
        g_source_remove(context.redraw_idle_id);
        context.redraw_idle_id = 0;
        return 0;
    }
    if (strcmp(mode, "pointer-sync-gates") == 0) {
        ClientContext context = {0};
        GdkEventButton event = {.x = 160, .y = 14};
        g_unsetenv("CTFLAB_DIAGNOSTIC_POINTER_SYNC");
        g_assert_false(sync_pointer_before_press(NULL, &event, &context));
        g_setenv("CTFLAB_DIAGNOSTIC_POINTER_SYNC", "1", TRUE);
        g_assert_false(sync_pointer_before_press(NULL, &event, NULL));
        g_assert_false(sync_pointer_before_press(NULL, &event, &context));
        context.absolute_mouse_ready = TRUE;
        g_assert_false(sync_pointer_before_press(NULL, &event, &context));
        context.display_ready = TRUE;
        context.transition_active = TRUE;
        g_assert_false(sync_pointer_before_press(NULL, &event, &context));
        context.transition_active = FALSE;
        g_assert_false(sync_pointer_before_press(NULL, &event, &context)); /* 无窗口不发送。 */
        return 0;
    }
    if (strcmp(mode, "first-paint") == 0) {
        ClientContext context = {0};
        on_display_invalidate(NULL, 0, 0, 1000, 700, &context);
        g_assert_false(context.transition_damage_seen);
        context.transition_active = TRUE;
        context.transition_deadline = g_get_monotonic_time() + G_USEC_PER_SEC;
        g_assert_true(shield_check(&context));
        on_display_invalidate(NULL, 0, 0, 0, 0, &context);
        g_assert_false(context.transition_damage_seen);
        on_display_invalidate(NULL, 0, 0, 1000, 700, &context);
        g_assert_true(context.transition_damage_seen);
        on_display_primary_destroy(NULL, &context);
        g_assert_false(context.transition_damage_seen);
        on_display_invalidate(NULL, 0, 0, 1000, 700, &context);
        g_assert_true(context.transition_damage_seen);
        g_assert_cmpuint(context.frame_check_idle_id, ==, 0);
        g_assert_true(shield_check(&context)); /* 未就绪不能撤掉屏障。 */
        return 0;
    }
    if (strcmp(mode, "resize-cancel") == 0) {
        ClientContext context = {0};
        for (int i = 0; i < 2000; i++) {
            queue_guest_resize(&context);
            g_assert_cmpuint(context.resize_timer_id, !=, 0);
        }
        g_assert_cmpuint(context.resize_generation, ==, 2000);
        g_source_remove(context.resize_timer_id);
        context.resize_timer_id = 0;
        queue_guest_resize(&context);
        gint64 deadline = g_get_monotonic_time() + G_USEC_PER_SEC;
        while (context.resize_timer_id != 0 && g_get_monotonic_time() < deadline) {
            g_main_context_iteration(NULL, FALSE);
            g_usleep(1000);
        }
        g_assert_cmpuint(context.resize_timer_id, ==, 0);
        return 0;
    }
    if (strcmp(mode, "window-events") == 0) {
        ClientContext context = {0};
        InputContext input = {0};
        input_track_key(&input, GDK_KEY_Shift_L, TRUE);
        g_input_context = &input;
        GdkEventWindowState event = {.changed_mask = GDK_WINDOW_STATE_ICONIFIED,
                                    .new_window_state = GDK_WINDOW_STATE_ICONIFIED};
        g_assert_false(on_window_state(NULL, &event, &context));
        g_assert_cmpuint(input.pressed_count, ==, 0);
        event.new_window_state = 0;
        g_assert_false(on_window_state(NULL, &event, &context));
        g_input_context = NULL;
        return 0;
    }
    if (strcmp(mode, "signal-pipe") == 0) {
        for (int cycle = 0; cycle < 3; cycle++) {
            SpiceSession *session = spice_session_new();
            SessionContext context = {.session = session};
            g_session_context = &context;
            install_quit_signals();
            raise(SIGTERM);
            raise(SIGINT);
            raise(SIGHUP);
            g_assert_false(context.quitting);
            g_assert_true(quit_signal_pending);
            while (g_main_context_iteration(NULL, FALSE)) {}
            g_assert_true(context.quitting);
            remove_quit_signals();
            g_assert_cmpint(quit_pipe[0], ==, -1);
            g_assert_cmpint(quit_pipe[1], ==, -1);
            g_assert_cmpuint(quit_pipe_source, ==, 0);
            g_assert_cmpint(alarm(0), ==, 0);
            g_session_context = NULL;
            g_object_unref(session);
        }
        return 0;
    }
    if (strcmp(mode, "quit-without-loop") == 0) {
        SpiceSession *session = spice_session_new();
        SessionContext context = {.session = session};
        g_assert_cmpuint(gtk_main_level(), ==, 0);
        request_client_quit(&context, session);
        request_client_quit(&context, session);
        g_assert_true(context.quitting);
        g_object_unref(session);
        return 0;
    }
    if (strcmp(mode, "pointer-trace") == 0) {
        ClientContext context = {0};
        GdkEventMotion motion = {.x = 160, .y = 14};
        g_assert_false(on_display_motion(NULL, &motion, &context));
        motion.x = 62; motion.y = 176;
        g_assert_false(on_display_motion(NULL, &motion, &context));
        g_assert_cmpuint(context.motion_count, ==, 2);
        g_assert_cmpfloat(context.last_motion_x, ==, 62);
        g_assert_cmpfloat(context.last_motion_y, ==, 176);
        GdkEventButton release = {.button = 1, .x = 62, .y = 176};
        g_assert_false(on_display_button_release(NULL, &release, &context));
        g_assert_cmpuint(context.motion_count, ==, 2);
        return 0;
    }
    if (strcmp(mode, "permissions") == 0) {
        char *text[] = {"client", "--clipboard"};
        char *files[] = {"client", "--file-transfer"};
        char *both[] = {"client", "--clipboard", "--file-transfer"};
        g_assert_true(clipboard_argument(2, text));
        g_assert_false(file_transfer_argument(2, text));
        g_assert_false(clipboard_argument(2, files));
        g_assert_true(file_transfer_argument(2, files));
        g_assert_true(clipboard_argument(3, both));
        g_assert_true(file_transfer_argument(3, both));
        return 0;
    }
    if (strcmp(mode, "geometry") == 0) {
        WindowGeometry geometry = {0};
        g_assert_true(parse_geometry_text("1280x800", &geometry));
        g_assert_cmpint(geometry.width, ==, 1280);
        g_assert_cmpint(geometry.height, ==, 800);
        g_assert_false(geometry.fullscreen);
        g_assert_true(parse_geometry_text("400x300", &geometry));
        g_assert_false(parse_geometry_text("399x300", &geometry));
        g_assert_false(parse_geometry_text("100x100", &geometry));
        g_assert_false(parse_geometry_text("16385x1000", &geometry));
        g_assert_false(parse_geometry_text("1280", &geometry));
        g_assert_false(parse_geometry_text("1280x", &geometry));
        g_assert_false(parse_geometry_text("1280x800x", &geometry));
        g_assert_false(parse_geometry_text("1280xabc", &geometry));
        g_assert_false(parse_geometry_text("-10x800", &geometry));
        g_assert_false(parse_geometry_text(NULL, &geometry));
    } else if (strcmp(mode, "args") == 0) {
        WindowGeometry geometry = {0};
        const char *argv1[] = {"client", "--geometry", "1440x900"};
        g_assert_true(geometry_argument(3, (char **)argv1, &geometry));
        g_assert_cmpint(geometry.width, ==, 1440);
        g_assert_cmpint(geometry.height, ==, 900);
        const char *argv2[] = {"client", "--geometry=640x480"};
        g_assert_true(geometry_argument(2, (char **)argv2, &geometry));
        g_assert_cmpint(geometry.height, ==, 480);
        const char *argv3[] = {"client", "--geometry", "bad"};
        g_assert_false(geometry_argument(3, (char **)argv3, &geometry));
        const char *argv4[] = {"client", "--uri", "spice+unix:///x"};
        g_assert_false(geometry_argument(3, (char **)argv4, &geometry));
        const char *argv5[] = {"client", "--state-file", "/tmp/x.json"};
        g_assert_cmpstr(state_file_argument(3, (char **)argv5), ==, "/tmp/x.json");
        const char *argv6[] = {"client", "--uri", "spice+unix:///x"};
        g_assert_null(state_file_argument(3, (char **)argv6));
    } else if (strcmp(mode, "window-state") == 0) {
        const char *path = g_getenv("CTFLAB_TEST_STATE");
        g_assert_nonnull(path);
        WindowGeometry geometry = {0};
        gint quality = -1;
        g_assert_false(window_state_load(path, &geometry, NULL, NULL));
        window_state_save(path, 1440, 900, TRUE, 2, 1);
        gint scale = 0;
        g_assert_true(window_state_load(path, &geometry, &scale, &quality));
        g_assert_cmpint(quality, ==, 1);
        g_assert_cmpint(geometry.width, ==, 1440);
        g_assert_cmpint(geometry.height, ==, 900);
        g_assert_true(geometry.fullscreen);
        g_assert_cmpint(scale, ==, 2);
        window_state_save(path, 1000, 700, FALSE, 1, 0);
        quality = -1;
        g_assert_true(window_state_load(path, &geometry, &scale, &quality));
        g_assert_false(geometry.fullscreen);
        g_assert_cmpint(quality, ==, 0);
        /* 损坏/越界内容按加载失败处理，不产出半初始化几何。 */
        g_assert_true(g_file_set_contents(path, "garbage", -1, NULL));
        g_assert_false(window_state_load(path, &geometry, NULL, NULL));
        g_assert_true(g_file_set_contents(path,
            "ctflab-client-window v1 width=99999 height=900 fullscreen=0 scale=1",
            -1, NULL));
        g_assert_false(window_state_load(path, &geometry, NULL, NULL));
        g_assert_true(g_file_set_contents(path,
            "ctflab-client-window v1 width=900 height=900 fullscreen=0",
            -1, NULL));
        g_assert_false(window_state_load(path, &geometry, NULL, NULL));
        /* 旧 4 字段格式（无 quality）向后兼容：正常加载，偏好按清晰优先。 */
        g_assert_true(g_file_set_contents(path,
            "ctflab-client-window v1 width=1440 height=900 fullscreen=1 scale=2",
            -1, NULL));
        quality = -1;
        g_assert_true(window_state_load(path, &geometry, NULL, &quality));
        g_assert_true(geometry.fullscreen);
        g_assert_cmpint(quality, ==, 0);
        /* path 为 NULL 时必须安全返回，不访问文件系统。 */
        g_assert_false(window_state_load(NULL, &geometry, NULL, NULL));
        window_state_save(NULL, 1, 2, TRUE, 3, 0);
    } else if (strcmp(mode, "keys") == 0) {
        InputContext input = {0};
        input_track_key(&input, GDK_KEY_Control_L, TRUE);
        input_track_key(&input, GDK_KEY_Control_L, TRUE); /* 按键重复幂等 */
        input_track_key(&input, GDK_KEY_Meta_L, TRUE);
        g_assert_cmpint(input.pressed_count, ==, 2);
        input_track_key(&input, GDK_KEY_Control_L, FALSE);
        g_assert_cmpint(input.pressed_count, ==, 1);
        g_assert_cmpuint(input.pressed[0], ==, GDK_KEY_Meta_L);
        input_track_key(&input, GDK_KEY_A, FALSE); /* 未按下的 release 忽略 */
        g_assert_cmpint(input.pressed_count, ==, 1);
        /* display 为 NULL：只清空集合、不崩溃、不发送。 */
        input_release_pressed_keys(&input);
        g_assert_cmpint(input.pressed_count, ==, 0);
        input.held_buttons = (1u << 1) | (1u << 3);
        input_track_key(&input, GDK_KEY_Control_L, TRUE);
        GdkEventKey reset = {.type = GDK_KEY_PRESS, .keyval = GDK_KEY_F12, .state = GDK_SHIFT_MASK};
        g_assert_true(input_key_snooper(NULL, &reset, &input));
        g_assert_cmpint(input.pressed_count, ==, 0);
        g_assert_cmpuint(input.held_buttons, ==, 0);
        reset.type = GDK_KEY_RELEASE; reset.state = 0;
        g_assert_true(input_key_snooper(NULL, &reset, &input));
        g_assert_false(input.reset_shortcut_held);
        reset.type = GDK_KEY_PRESS;
        g_assert_false(input_key_snooper(NULL, &reset, &input)); /* 普通 F12 不被吞 */
        input_release_pressed_keys(&input); /* 幂等 */
        g_assert_cmpint(input.pressed_count, ==, 0);
        for (int index = 0; index < CTFLAB_MAX_PRESSED_KEYS + 8; index++) {
            input_track_key(&input, GDK_KEY_a + index, TRUE); /* 不越界 */
        }
        g_assert_cmpint(input.pressed_count, ==, CTFLAB_MAX_PRESSED_KEYS);
        input_release_pressed_keys(&input);
        g_assert_cmpint(input.pressed_count, ==, 0);
    } else {
        g_assert_not_reached();
    }
    return 0;
}
"""


@unittest.skipUnless(sys.platform == "darwin", "仅 macOS 编译受控客户端分支")
class ClientInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("clang") or not shutil.which("pkg-config"):
            raise unittest.SkipTest("需要 clang 和 pkg-config")
        result = subprocess.run(
            ["pkg-config", "--cflags", "--libs", "spice-client-gtk-3.0", "gtk+-3.0"],
            capture_output=True, text=True)
        if result.returncode:
            raise unittest.SkipTest("需要本地 spice-gtk/GTK 开发依赖")
        cls.tmp = tempfile.TemporaryDirectory(prefix="ctflab-client-input-tests-")
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.root = Path(cls.tmp.name)
        harness = cls.root / "input.c"
        harness.write_text(HARNESS.replace("SOURCE_PATH", str(SOURCE)))
        cls.binary = cls.root / "input"
        subprocess.run(
            ["clang", "-Wall", "-Wextra", "-Werror", "-fsanitize=address,undefined",
             str(harness), "-o", str(cls.binary), *shlex.split(result.stdout)],
            check=True, capture_output=True, text=True)

    def run_case(self, mode):
        with tempfile.TemporaryDirectory(dir=self.root) as directory:
            env = dict(os.environ, G_DEBUG="fatal-warnings", ASAN_OPTIONS="detect_leaks=0")
            if mode == "window-state":
                env["CTFLAB_TEST_STATE"] = str(Path(directory) / "client-window.txt")
            result = subprocess.run([str(self.binary), mode], env=env,
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_geometry_parsing_bounds_and_rejects(self):
        self.run_case("geometry")

    def test_primary_metadata_tracks_real_canvas_and_clears_stale_size(self):
        self.run_case("canvas-metadata")

    def test_content_allocation_catches_decoration_change_without_configure(self):
        self.run_case("content-allocation")
        source = SOURCE.read_text()
        self.assertIn('"size-allocate", G_CALLBACK(on_display_size_allocate)', source)
        callback = source.split("static void on_display_size_allocate(", 1)[1].split(
            "static void update_mouse_mode", 1)[0]
        self.assertIn("schedule_guest_resize(context)", callback)
        self.assertNotIn("spice_main_channel_send_monitor_config", callback)
        self.assertNotIn("shield_end", callback)

    def test_normal_click_never_copies_full_frame_or_changes_transform(self):
        source = SOURCE.read_text()
        press = source.split("static gboolean on_display_button_press(", 1)[1].split(
            "static void schedule_guest_resize", 1)[0]
        self.assertNotIn("measured_frame", press)
        self.assertNotIn("spice_display_get_pixbuf", press)
        self.assertIn("context->canvas_width", press)
        self.assertIn("return FALSE", press)
        self.assertIn('"display-primary-create", G_CALLBACK(on_display_primary_create)', source)

    def test_host_command_switch_does_not_leak_super_or_tab_to_guest(self):
        self.run_case("host-command")

    def test_focus_trace_only_records_system_key_categories(self):
        result = subprocess.run([str(self.binary), "focus-key-trace"],
                                env=dict(os.environ, ASAN_OPTIONS="detect_leaks=0"),
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("recovery-key=tab phase=press", result.stderr)
        self.assertIn("recovery-key=tab phase=release", result.stderr)
        self.assertIn("recovery-phase=focus-out", result.stderr)
        self.assertNotIn("recovery-key=a ", result.stderr)
        self.assertEqual(result.stderr.count("recovery-key="), 2)

    def test_focus_first_damage_redraws_once_without_changing_modes(self):
        self.run_case("focus-first-damage")

    def test_recovery_first_events_are_not_lost_to_log_throttling(self):
        self.run_case("recovery-first-events")

    def test_recovery_trace_is_opt_in_throttled_and_keeps_transition(self):
        self.run_case("recovery-trace")

    def test_recovery_trace_does_not_read_pixels_or_change_modes(self):
        source = SOURCE.read_text()
        helper = source.split("static void trace_display_recovery(", 1)[1].split(
            "static gboolean on_display_draw_trace", 1)[0]
        self.assertIn('"CTFLAB_TRACE_DISPLAY_RECOVERY"', helper)
        self.assertNotIn("spice_display_get_pixbuf", helper)
        self.assertNotIn("apply_guest_resize", helper)
        self.assertNotIn("shield_end", helper)
        self.assertIn('g_signal_connect_after(display, "draw",', source)

    def test_clipboard_and_files_are_independently_authorized(self):
        self.run_case("permissions")

    def test_geometry_and_state_file_arguments(self):
        self.run_case("args")

    def test_window_state_roundtrip_and_corruption(self):
        self.run_case("window-state")

    def test_pressed_key_tracking_and_release(self):
        self.run_case("keys")

    def test_empty_tracking_releases_base_scancodes_on_explicit_reset_and_reconnect(self):
        self.run_case("untracked-reset")

    def test_untracked_reset_never_presses_keys_or_runs_on_normal_focus_out(self):
        source = SOURCE.read_text()
        reset = source.split("static void input_reset_untracked_keys(", 1)[1].split(
            "static void on_inputs_recovery_event", 1)[0]
        self.assertIn("spice_inputs_channel_key_release", reset)
        self.assertNotIn("key_press", reset)
        self.assertNotIn("set_key_locks", reset)
        self.assertIn("g_timeout_add(30", reset)
        focus = source.split("static gboolean on_window_focus_out(", 1)[1].split(
            "static gboolean on_window_grab_broken", 1)[0]
        self.assertNotIn("input_reset_untracked_keys", focus)

    def test_quit_without_gtk_loop_is_safe_and_idempotent(self):
        self.run_case("quit-without-loop")

    def test_pointer_trace_preserves_events_and_coordinates(self):
        self.run_case("pointer-trace")

    def test_pointer_sync_keeps_spice_transform_and_mode_gates(self):
        self.run_case("pointer-sync-gates")
        source = SOURCE.read_text()
        sync = source.split("static gboolean sync_pointer_before_press(", 1)[1].split(
            "static gboolean on_display_button_press(", 1)[0]
        self.assertIn("gtk_widget_event(widget, motion)", sync)
        self.assertIn('g_getenv("CTFLAB_DIAGNOSTIC_POINTER_SYNC")', sync)
        self.assertIn("motion->motion.x = event->x", sync)
        self.assertNotIn("spice_inputs_channel_button", sync)
        self.assertNotIn("spice_inputs_channel_position", sync)
        press = source.split("static gboolean on_display_button_press(", 1)[1].split(
            "static void schedule_guest_resize", 1)[0]
        self.assertIn("sync_pointer_before_press(widget, event, context)", press)
        self.assertIn("return FALSE", press)

    def test_signal_pipe_dispatch_and_repeated_cleanup(self):
        self.run_case("signal-pipe")

    def test_focus_redraw_is_coalesced_and_keeps_transition_guard(self):
        self.run_case("redraw-coalesce")

    def test_ready_and_focus_redraw_do_not_change_guest_geometry(self):
        source = SOURCE.read_text()
        redraw = source.split("static gboolean redraw_display_idle(", 1)[1].split(
            "static void queue_display_redraw", 1)[0]
        self.assertIn("gdk_window_invalidate_rect(window, NULL, TRUE)", redraw)
        self.assertNotIn("apply_guest_resize", redraw)
        self.assertNotIn("shield_end", redraw)
        self.assertNotIn("spice_display_get_pixbuf", redraw)
        self.assertIn('"focus-in-event", G_CALLBACK(on_window_focus_in)', source)
        self.assertIn("g_source_remove(context.redraw_idle_id)", source)

    def test_window_state_releases_keys_without_consuming_event(self):
        self.run_case("window-events")

    def test_expanded_window_respects_system_workarea(self):
        source = SOURCE.read_text()
        layout = source.split("static void set_fullscreen_layout(", 1)[1].split(
            "static gboolean apply_start_fullscreen", 1)[0]
        self.assertIn("gdk_monitor_get_workarea(monitor, &geometry)", layout)
        self.assertNotIn("gdk_monitor_get_geometry", layout)
        self.assertNotIn("gtk_window_set_keep_above(GTK_WINDOW(window), TRUE)", layout)
        self.assertIn("geometry.x, geometry.y", layout)
        self.assertIn("geometry.width <= 0 || geometry.height <= 0", layout)
        self.assertIn("gdk_window_get_frame_extents(gdk_window, &frame)", layout)
        self.assertIn("geometry.height - frame_extra_h", layout)
        self.assertNotIn("gtk_window_set_decorated", layout)
        self.assertNotIn("gdk_window_resize(", layout)
        self.assertIn("gtk_window_resize(GTK_WINDOW(window), content_w, content_h)", layout)
        self.assertIn("gtk_window_resize(GTK_WINDOW(window), width, height)", layout)

    @unittest.skipUnless(sys.platform == "darwin", "仅 macOS 原生 Dock 回调")
    def test_native_reopen_is_added_without_replacing_existing_callback(self):
        self.run_case("native-reopen")
        source = SOURCE.read_text()
        self.assertIn('g_object_set(app, "register-session", TRUE, NULL)', source)
        self.assertIn('g_application_activate(G_APPLICATION(g_client_app))', source)
        self.assertNotIn("class_replaceMethod", source)

    def test_resize_uses_one_debounce_and_immediate_send(self):
        source = SOURCE.read_text()
        apply = source.split("static void apply_guest_resize(", 1)[1].split(
            "static gboolean enable_guest_resize", 1)[0]
        self.assertIn("width, height, FALSE)", apply)
        self.assertNotIn("width, height, TRUE)", apply)
        self.assertIn("spice_main_channel_send_monitor_config(context->main_channel)", apply)
        self.assertLess(apply.index("shield_begin(context, width, height)"),
                        apply.index("spice_main_channel_send_monitor_config"))
        self.assertIn("if (sent)", apply)
        self.assertIn("G_PRIORITY_DEFAULT, 180, enable_guest_resize, timer, g_free", source)

    def test_repeated_resize_cancel_and_not_ready_expiry(self):
        self.run_case("resize-cancel")

    def test_ready_still_requires_real_frame_match(self):
        source = SOURCE.read_text()
        ready = source.split("static void on_display_ready(", 1)[1].split(
            "#ifdef CTFLAB_E2E_TEST", 1)[0]
        self.assertIn("ready && context->transition_active", ready)
        self.assertIn("queue_transition_frame_check(context)", ready)
        self.assertNotIn("shield_end(context", ready)

    def test_real_paint_is_required_before_dimension_match(self):
        self.run_case("first-paint")
        source = SOURCE.read_text()
        check = source.split("static gboolean shield_check(", 1)[1].split(
            "static gboolean check_transition_frame_idle", 1)[0]
        self.assertIn("!context->display_ready || !context->transition_damage_seen", check)
        self.assertIn('"display-invalidate", G_CALLBACK(on_display_invalidate)', source)

    def test_transition_end_requests_live_canvas_redraw(self):
        source = SOURCE.read_text()
        end = source.split("static void shield_end(", 1)[1].split(
            "static GdkPixbuf *measured_frame", 1)[0]
        self.assertIn("context->display != NULL", end)
        self.assertLess(end.index("gtk_widget_hide(context->shield)"),
                        end.index("gtk_widget_queue_draw(GTK_WIDGET(context->display))"))


if __name__ == "__main__":
    unittest.main()
