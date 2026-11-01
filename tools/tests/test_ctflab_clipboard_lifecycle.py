"""直接编译并运行 macOS 剪贴板实现；替代 pasteboard 程序，不触碰用户剪贴板。"""

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
#define main ctflab_client_main
#include "SOURCE_PATH"
#undef main
#include <sys/wait.h>

static void pump(gint64 duration) {
    gint64 end = g_get_monotonic_time() + duration;
    do {
        while (g_main_context_iteration(NULL, FALSE)) {}
        g_usleep(1000);
    } while (g_get_monotonic_time() < end);
}
static void stopped(void) {
    host_clipboard_shutdown();
    g_assert_false(host_clipboard_shared.initialized);
    g_assert_null(host_clipboard_shared.thread);
    g_assert_null(host_clipboard_shared.cancel);
    g_assert_null(host_clipboard_shared.pending_host);
    g_assert_cmpuint(host_clipboard_shared.dispatch_timer_id, ==, 0);
    pump(150000); /* 原 timer 到期后也不能访问已清理的锁 */
}
static void wait_child(void) {
    gint64 end = g_get_monotonic_time() + 3 * G_USEC_PER_SEC;
    while (!g_file_test(g_getenv("CTFLAB_TEST_CHILD"), G_FILE_TEST_EXISTS) &&
           g_get_monotonic_time() < end) pump(1000);
    g_assert_true(g_file_test(g_getenv("CTFLAB_TEST_CHILD"), G_FILE_TEST_EXISTS));
}
static void child_reaped(void) {
    gchar *text = NULL;
    g_assert_true(g_file_get_contents(g_getenv("CTFLAB_TEST_CHILD"), &text, NULL, NULL));
    pid_t child = (pid_t)strtol(text, NULL, 10);
    g_free(text);
    errno = 0;
    g_assert_cmpint(kill(child, 0), ==, -1);
    g_assert_cmpint(errno, ==, ESRCH);
}
int main(int argc, char **argv) {
    g_assert_cmpint(argc, ==, 2);
    const char *mode = argv[1];
    if (strcmp(mode, "qemu-zombie") == 0) {
        g_assert_true(qemu_process_running(getpid()));
        g_assert_false(qemu_process_running(0));
        pid_t child = fork();
        g_assert_cmpint(child, >=, 0);
        if (child == 0) _exit(0);
        gint64 end = g_get_monotonic_time() + 2 * G_USEC_PER_SEC;
        while (qemu_process_running(child) && g_get_monotonic_time() < end) g_usleep(1000);
        /* 特意不先 waitpid：kill 成功，但客户端必须识别它已退出。 */
        g_assert_cmpint(kill(child, 0), ==, 0);
        g_assert_false(qemu_process_running(child));
        g_assert_cmpint(waitpid(child, NULL, 0), ==, child);
        g_assert_false(qemu_process_running(child));
    } else if (strcmp(mode, "disabled") == 0) {
        host_clipboard_stop_new_work();
        stopped();
        g_assert_false(clipboard_accepts_work(&host_clipboard_shared));
    } else if (strcmp(mode, "repeat") == 0) {
        for (int i = 0; i < 40; i++) {
            host_clipboard_start(NULL);
            pump(2000);
            host_clipboard_stop_new_work();
            host_clipboard_stop_new_work();
            stopped();
            stopped();
        }
    } else if (strcmp(mode, "pending") == 0) {
        host_clipboard_start(NULL);
        g_mutex_lock(&host_clipboard_shared.lock);
        host_clipboard_shared.pending_host = g_bytes_new_static("late", 4);
        g_mutex_unlock(&host_clipboard_shared.lock);
        stopped();
    } else if (strcmp(mode, "stable") == 0) {
        host_clipboard_start(NULL);
        pump(1300000);
        g_mutex_lock(&host_clipboard_shared.lock);
        g_assert_nonnull(host_clipboard_shared.pending_host);
        g_assert_cmpmem(g_bytes_get_data(host_clipboard_shared.pending_host, NULL), 4,
                        "HOST", 4);
        g_mutex_unlock(&host_clipboard_shared.lock);
        /* 未连 agent，持续保持最后一份缓存，不能消费后丢失。 */
        pump(300000);
        g_assert_nonnull(host_clipboard_shared.pending_host);
        stopped();
    } else if (strcmp(mode, "guest") == 0) {
        host_clipboard_start(NULL);
        const gchar *guest = "GUEST-中文\nL2";
        on_clipboard_guest_data(NULL, VD_AGENT_CLIPBOARD_SELECTION_CLIPBOARD,
            VD_AGENT_CLIPBOARD_UTF8_TEXT, (const guchar *)guest, strlen(guest),
            &host_clipboard_shared);
        pump(1300000);
        gchar *actual = NULL;
        g_assert_true(g_file_get_contents(g_getenv("CTFLAB_TEST_TEXT"), &actual, NULL, NULL));
        g_assert_cmpstr(actual, ==, guest);
        g_free(actual);
        g_mutex_lock(&host_clipboard_shared.lock);
        g_assert_null(host_clipboard_shared.pending_host); /* 回声不推回 */
        g_mutex_unlock(&host_clipboard_shared.lock);
        stopped();
        /* 拒收清理后晚到的来宾通知，不再访问同步设施。 */
        on_clipboard_guest_data(NULL, 0, VD_AGENT_CLIPBOARD_UTF8_TEXT,
            (const guchar *)"late", 4, &host_clipboard_shared);
    } else if (strcmp(mode, "blocked-read") == 0 ||
               strcmp(mode, "blocked-write") == 0) {
        host_clipboard_start(NULL);
        if (strcmp(mode, "blocked-write") == 0) {
            /* 超过 pipe 容量，验证写入等待也能取消。 */
            gchar *large = g_malloc0(1024 * 1024);
            on_clipboard_guest_data(NULL, 0, VD_AGENT_CLIPBOARD_UTF8_TEXT,
                (const guchar *)large, 1024 * 1024, &host_clipboard_shared);
            g_free(large);
        }
        wait_child();
        gint64 start = g_get_monotonic_time();
        stopped();
        g_assert_cmpint(g_get_monotonic_time() - start, <, G_USEC_PER_SEC);
        child_reaped();
    } else {
        g_assert_not_reached();
    }
    return 0;
}
"""


@unittest.skipUnless(sys.platform == "darwin", "仅 macOS 编译 pasteboard 分支")
class ClipboardLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("clang") or not shutil.which("pkg-config"):
            raise unittest.SkipTest("需要 clang 和 pkg-config")
        result = subprocess.run(
            ["pkg-config", "--cflags", "--libs", "spice-client-gtk-3.0", "gtk+-3.0"],
            capture_output=True, text=True)
        if result.returncode:
            raise unittest.SkipTest("需要本地 spice-gtk/GTK 开发依赖")
        cls.tmp = tempfile.TemporaryDirectory(prefix="ctflab-clipboard-tests-")
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.root = Path(cls.tmp.name)
        reader, writer = cls.root / "paste-read", cls.root / "paste-write"
        reader.write_text(
            '#!/bin/sh\nif [ "$CTFLAB_TEST_MODE" = blocked-read ]; then\n'
            'echo $$ > "$CTFLAB_TEST_CHILD"\nexec /bin/sleep 30\nfi\n'
            'exec /bin/cat "$CTFLAB_TEST_TEXT"\n')
        writer.write_text(
            '#!/bin/sh\nif [ "$CTFLAB_TEST_MODE" = blocked-write ]; then\n'
            'echo $$ > "$CTFLAB_TEST_CHILD"\nexec /bin/sleep 30\nfi\n'
            'exec /bin/cat > "$CTFLAB_TEST_TEXT"\n')
        reader.chmod(0o700)
        writer.chmod(0o700)
        harness = cls.root / "lifecycle.c"
        harness.write_text(HARNESS.replace("SOURCE_PATH", str(SOURCE)))
        cls.binary = cls.root / "lifecycle"
        subprocess.run(
            ["clang", "-Wall", "-Wextra", "-Werror", "-fsanitize=address,undefined",
             f'-DCTFLAB_PBPASTE="{reader}"', f'-DCTFLAB_PBCOPY="{writer}"',
             str(harness), "-o", str(cls.binary), *shlex.split(result.stdout)],
            check=True, capture_output=True, text=True)

    def run_case(self, mode):
        with tempfile.TemporaryDirectory(dir=self.root) as directory:
            root = Path(directory)
            text = root / "text"
            text.write_text("HOST")
            env = dict(os.environ, CTFLAB_TEST_MODE=mode, CTFLAB_TEST_TEXT=str(text),
                       CTFLAB_TEST_CHILD=str(root / "child"),
                       G_DEBUG="fatal-warnings", ASAN_OPTIONS="detect_leaks=0")
            result = subprocess.run([str(self.binary), mode], env=env,
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_clipboard_disabled_cleanup(self):
        self.run_case("disabled")

    def test_qemu_zombie_is_not_running(self):
        self.run_case("qemu-zombie")

    def test_repeated_shutdown_and_late_timer(self):
        self.run_case("repeat")

    def test_pending_text_is_cancelled_before_state_cleanup(self):
        self.run_case("pending")

    def test_stable_text_survives_agent_not_ready(self):
        self.run_case("stable")

    def test_guest_write_and_echo_suppression(self):
        self.run_case("guest")

    def test_blocked_read_cancel_and_child_reaping(self):
        self.run_case("blocked-read")

    def test_blocked_write_cancel_and_child_reaping(self):
        self.run_case("blocked-write")
