"""Live check: a player-style org.freedesktop.ScreenSaver.Inhibit is seen.

Holds a real inhibit (as mpv/Chrome/Firefox do), waits for KDE's PolicyAgent
to register it (~5 s delay), and checks the guard's probe reports it, then
releases it and checks it is gone. Touches nothing on screen.
Run: python3 tests/test_dbus_inhibit_seen.py
"""
import importlib.util, os, sys, time
import dbus
HERE = os.path.dirname(os.path.abspath(__file__))
s = importlib.util.spec_from_file_location("g", os.path.join(HERE, "..", "aquarium-idle-guard.py"))
g = importlib.util.module_from_spec(s); s.loader.exec_module(g)
bus = dbus.SessionBus()
ss = dbus.Interface(bus.get_object("org.freedesktop.ScreenSaver", "/org/freedesktop/ScreenSaver"),
                    "org.freedesktop.ScreenSaver")
probe = g.Inhibitors()
before = probe.screen()
cookie = ss.Inhibit("aquarium-test-player", "Playing video")
seen = []
for _ in range(15):
    time.sleep(1)
    seen = probe.screen()
    if "aquarium-test-player" in seen:
        break
held_action = g.decide(False, seen, False, False, False)[0]
ss.UnInhibit(cookie)
gone = None
for _ in range(15):
    time.sleep(1)
    gone = probe.screen()
    if "aquarium-test-player" not in gone:
        break
ok = "aquarium-test-player" in seen and held_action == "heartbeat" \
    and "aquarium-test-player" not in gone
print("before", before, "| held", seen, "->", held_action, "| released", gone)
print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
