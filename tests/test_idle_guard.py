"""Unit tests for aquarium-idle-guard's decision rule.

Run: python3 -m unittest discover -s tests -p 'test_*.py'
"""
import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
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


if __name__ == "__main__":
    unittest.main()
