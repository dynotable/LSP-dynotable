import unittest

from dynotable.gate import app_running, gate, latches_refusal, port_file_path, recovery_step, start_command

PATH = "/home/u/.config/DynoTable/lsp-port.json"


def running(content, pid_alive=lambda pid: True):
    files = {} if content is None else {PATH: content}
    return app_running(PATH, lambda p: p in files, lambda p: files[p], pid_alive)


class AppRunningTest(unittest.TestCase):
    def test_missing_file_is_not_running(self):
        self.assertFalse(running(None))

    def test_malformed_json_is_not_running(self):
        self.assertFalse(running('{"port": 41120, "token": '))

    def test_dead_pid_is_not_running(self):
        # A killed app leaves its port file behind.
        self.assertFalse(running('{"port": 41120, "token": "t", "pid": 48213}', pid_alive=lambda pid: False))

    def test_live_pid_is_running(self):
        self.assertTrue(running('{"port": 41120, "token": "t", "pid": 48213}', pid_alive=lambda pid: pid == 48213))

    def test_file_without_pid_is_running(self):
        # An older app does not write a pid.
        self.assertTrue(running('{"port": 41120, "token": "t"}', pid_alive=lambda pid: False))


class GateTest(unittest.TestCase):
    def test_first_start_may_launch_a_closed_app(self):
        self.assertTrue(gate(first_start_pending=True, app_running=False, refused_windows=set(), window_id=1))

    def test_restart_after_a_quit_does_not_start(self):
        self.assertFalse(gate(first_start_pending=False, app_running=False, refused_windows=set(), window_id=1))

    def test_app_up_starts(self):
        self.assertTrue(gate(first_start_pending=False, app_running=True, refused_windows=set(), window_id=1))

    def test_refusal_stops_crash_restarts_in_its_window_only(self):
        # Without the latch, each refusal is a crash, and the fifth one shows a modal dialog.
        self.assertFalse(gate(first_start_pending=False, app_running=True, refused_windows={2}, window_id=2))
        # A bad `.dynotable.json` in window 2 must not stop window 1's session from taking new files.
        self.assertTrue(gate(first_start_pending=False, app_running=True, refused_windows={2}, window_id=1))


class RecoveryStepTest(unittest.TestCase):
    def test_never_checks_while_a_session_starts(self):
        # A check now starts a second session, and the first one never gets used or stopped.
        self.assertEqual(recovery_step(attached=False, refused=False, starting=True, app_running=True), "wait")

    def test_checks_when_the_app_is_back(self):
        self.assertEqual(recovery_step(attached=False, refused=False, starting=False, app_running=True), "check")

    def test_refused_window_waits_for_retry(self):
        self.assertEqual(recovery_step(attached=False, refused=True, starting=True, app_running=True), "skip")


class StartCommandTest(unittest.TestCase):
    def test_first_start_may_launch(self):
        self.assertEqual(start_command(["/bin/dynotable-lsp"], True), ["/bin/dynotable-lsp"])

    def test_later_start_adds_exactly_one_no_launch(self):
        base = ["node", "/s/dynotable-lsp.mjs"]
        self.assertEqual(start_command(base, False), ["node", "/s/dynotable-lsp.mjs", "--no-launch"])
        self.assertEqual(start_command(base, False), ["node", "/s/dynotable-lsp.mjs", "--no-launch"])


class LatchesRefusalTest(unittest.TestCase):
    def test_only_a_serving_app_refuses(self):
        self.assertTrue(latches_refusal(initialized=False, app_running=True))
        # A clean end of a working session is no refusal: reopening a file must not need Retry.
        self.assertFalse(latches_refusal(initialized=True, app_running=True))
        # The app went away during the start: when it comes back, the server must start with no command.
        self.assertFalse(latches_refusal(initialized=False, app_running=False))


class PortFilePathTest(unittest.TestCase):
    def test_linux_uses_xdg_config_home(self):
        self.assertEqual(
            port_file_path("linux", {"XDG_CONFIG_HOME": "/xdg"}, "/home/u"),
            "/xdg/DynoTable/lsp-port.json",
        )

    def test_user_data_dir_overrides_the_platform_path(self):
        # dynotable-cli reads the port file from this directory, so the gate must read the same one.
        self.assertEqual(
            port_file_path("osx", {"DYNOTABLE_USER_DATA_DIR": "/data/dt"}, "/Users/u"),
            "/data/dt/lsp-port.json",
        )

    def test_empty_user_data_dir_is_unset(self):
        # The CLI tests it with `||`, so an empty value means the platform path.
        self.assertEqual(
            port_file_path("osx", {"DYNOTABLE_USER_DATA_DIR": ""}, "/Users/u"),
            "/Users/u/Library/Application Support/DynoTable/lsp-port.json",
        )


if __name__ == "__main__":
    unittest.main()
