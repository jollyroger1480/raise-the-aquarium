"""Unit tests for aquarium-idle-guard's decision rule.

Run: python3 tests/test_idle_guard.py -v
"""
import importlib.util
import os
import stat
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp(prefix="guardtest")
os.environ["AQUARIUM_GUARD_LOG"] = os.path.join(TMP, "guard.log")
spec = importlib.util.spec_from_file_location(
    "guard", os.path.join(HERE, "..", "aquarium-idle-guard.py"))
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
decide = guard.decide


class Decide(unittest.TestCase):
    def test_dbus_inhibitor_blocks_start(self):
        # browser / Plex web / player called org.freedesktop.ScreenSaver.Inhibit
        a, _ = decide(False, ["Google Chrome"], False, False, False)
        self.assertEqual(a, "heartbeat")

    def test_inhibitor_stops_running_saver(self):
        a, _ = decide(True, ["mpv"], False, False, False)
        self.assertEqual(a, "stop")

    def test_wayland_inhibitor_or_input_blocks_start(self):
        # compositor not idle: Wayland idle inhibitor (mpv) or real input
        a, _ = decide(False, [], True, False, False)
        self.assertEqual(a, "heartbeat")

    def test_fallback_fullscreen_with_audio(self):
        a, _ = decide(False, [], False, True, True)
        self.assertEqual(a, "heartbeat")

    def test_music_in_a_window_does_not_block(self):
        a, _ = decide(False, [], False, True, False)
        self.assertIsNone(a)

    def test_fullscreen_silent_does_not_block(self):
        a, _ = decide(False, [], False, False, True)
        self.assertIsNone(a)

    def test_truly_idle_lets_saver_start(self):
        a, _ = decide(False, [], False, False, False)
        self.assertIsNone(a)

    def test_saver_own_audio_and_fullscreen_do_not_stop_it(self):
        # the tank is fullscreen with bubbles; that must not end the show
        a, _ = decide(True, [], True, True, True)
        self.assertIsNone(a)


def fake_helper(name, body):
    p = os.path.join(TMP, name)
    with open(p, "w") as f:
        f.write("#!/bin/bash\n" + body + "\n")
    os.chmod(p, 0o755)
    return p


def wait_for(cond, secs=5.0):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


class WaylandHelper(unittest.TestCase):
    def test_helper_missing_saver_still_starts(self):
        wl = guard.WaylandIdle(os.path.join(TMP, "no-such-helper"), 1000)
        self.assertFalse(wl.busy())
        a, _ = decide(False, [], wl.busy(), False, False)
        self.assertIsNone(a)

    def test_helper_that_never_reports_is_not_busy(self):
        wl = guard.WaylandIdle(fake_helper("silent", "exec sleep 30"), 1000)
        try:
            time.sleep(0.5)
            self.assertFalse(wl.busy())
        finally:
            wl.stop()

    def test_helper_exit_drops_busy(self):
        wl = guard.WaylandIdle(fake_helper("dies", "echo ready; sleep 0.5"),
                               1000)
        self.assertTrue(wait_for(wl.busy, 3))
        self.assertTrue(wait_for(lambda: not wl.alive(), 3))
        self.assertTrue(wait_for(lambda: not wl.busy(), 3))
        a, _ = decide(False, [], wl.busy(), False, False)
        self.assertIsNone(a)

    def test_helper_killed_drops_busy(self):
        wl = guard.WaylandIdle(fake_helper("live", "echo ready; exec sleep 30"),
                               1000)
        self.assertTrue(wait_for(wl.busy, 3))
        wl.stop()
        self.assertTrue(wait_for(lambda: not wl.busy(), 3))

    def test_helper_idle_line(self):
        wl = guard.WaylandIdle(
            fake_helper("idler", "echo ready; echo idle; exec sleep 30"), 1000)
        try:
            self.assertTrue(wait_for(lambda: wl.ok and not wl.active, 3))
            self.assertFalse(wl.busy())
        finally:
            wl.stop()


class LogSafety(unittest.TestCase):
    def test_names_cannot_inject_lines(self):
        self.assertNotIn("\n", guard.clean("evil\nFAKE 12:00 line\r"))
        a, reason = decide(False, [guard.clean("x\ny", 80)], False, False,
                           False)
        self.assertNotIn("\n", reason)

    def test_log_is_private_and_single_line(self):
        guard.log("hello\nforged")
        st = os.stat(guard.LOG)
        self.assertEqual(stat.S_IMODE(st.st_mode), 0o600)
        with open(guard.LOG) as f:
            lines = f.read().splitlines()
        self.assertTrue(lines[-1].endswith("hello?forged"))

    def test_log_does_not_follow_symlink(self):
        target = os.path.join(TMP, "victim")
        with open(target, "w") as f:
            f.write("keep\n")
        link = os.path.join(TMP, "link.log")
        os.symlink(target, link)
        old = guard.LOG
        guard.LOG = link
        try:
            guard.log("should not land")
        finally:
            guard.LOG = old
        with open(target) as f:
            self.assertEqual(f.read(), "keep\n")


if __name__ == "__main__":
    unittest.main()
