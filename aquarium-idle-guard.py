#!/usr/bin/python3
"""Keep xscreensaver honest on KDE Plasma Wayland.

Why this exists
---------------
xscreensaver runs under XWayland. Its idle timer only sees X input, and it
cannot hear "don't blank" requests: video players and browsers send those to
org.freedesktop.ScreenSaver (owned by KWin, not xscreensaver) or hold a
Wayland idle inhibitor (only the compositor sees it). So the saver started on
top of mpv / Plex / YouTube.

What it does
------------
Every POLL seconds it decides whether the session is busy:
  * a screen inhibitor is held  (KDE PolicyAgent ChangeScreenSettings - this is
    where org.freedesktop.ScreenSaver.Inhibit calls land - or a logind
    "idle" block inhibitor)
  * the compositor is not idle  (ext-idle-notify via aquarium-wl-idle: real
    Wayland input in the last WL_TIMEOUT seconds OR a Wayland idle inhibitor)
  * fallback for players that set nothing: a PipeWire output stream is
    running AND the active window is fullscreen
While busy and the saver is not up, it pokes `xscreensaver-command -deactivate`
(resets xscreensaver's idle timer). If an inhibitor appears while the saver is
up, it deactivates the saver.

Log: /tmp/aquarium-idle-guard.log (state changes only).
"""
import fcntl
import json
import os
import subprocess
import sys
import threading
import time

POLL = float(os.environ.get("AQUARIUM_GUARD_POLL", "10"))
WL_TIMEOUT_MS = int(os.environ.get("AQUARIUM_GUARD_WL_TIMEOUT_MS", "30000"))
LOG = os.environ.get("AQUARIUM_GUARD_LOG", "/tmp/aquarium-idle-guard.log")
HERE = os.path.dirname(os.path.abspath(__file__))
WL_HELPER = os.environ.get("AQUARIUM_WL_IDLE",
                           os.path.join(HERE, "aquarium-wl-idle"))
CHANGE_SCREEN_SETTINGS = 4  # PowerDevil PolicyAgent policy bit


def log(msg):
    with open(LOG, "a") as f:
        f.write(time.strftime("%H:%M:%S ") + msg + "\n")


# ---------------------------------------------------------------- decision
def decide(blanked, screen_inhibitors, wl_active, audio_playing, fullscreen):
    """Return (action, reason). action: 'heartbeat', 'stop' or None.

    Pure function - no I/O - so tests can drive it.
    """
    if screen_inhibitors:
        reason = "inhibitor: " + ", ".join(screen_inhibitors)
        return ("stop" if blanked else "heartbeat"), reason
    if blanked:
        # The tank itself is fullscreen with sound and Wayland input while it
        # is up is handled by xscreensaver's own unlock path; only a real
        # inhibitor ends a running show.
        return None, "saver up, no inhibitor"
    if wl_active:
        return "heartbeat", "compositor not idle (input or Wayland inhibitor)"
    if audio_playing and fullscreen:
        return "heartbeat", "fullscreen window with audio playing"
    return None, "idle"


# ---------------------------------------------------------------- probes
def xss_blanked():
    try:
        out = subprocess.run(["xscreensaver-command", "-time"],
                             capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return False
    return "blanked" in out and "non-blanked" not in out


def xss_deactivate():
    subprocess.run(["xscreensaver-command", "-deactivate"],
                   capture_output=True, timeout=5)


class Inhibitors:
    def __init__(self):
        import dbus
        self.dbus = dbus
        self.sess = dbus.SessionBus()
        try:
            self.sys = dbus.SystemBus()
        except Exception:
            self.sys = None

    def screen(self):
        """Names of apps holding a screen/idle inhibitor."""
        names = []
        d = self.dbus
        try:
            pa = self.sess.get_object("org.kde.Solid.PowerManagement",
                                      "/org/kde/Solid/PowerManagement/PolicyAgent")
            iface = "org.kde.Solid.PowerManagement.PolicyAgent"
            if pa.HasInhibition(d.UInt32(CHANGE_SCREEN_SETTINGS),
                                dbus_interface=iface):
                lst = pa.ListInhibitions(dbus_interface=iface)
                names += [str(a) for a, _r in lst] or ["kde-screen-inhibit"]
        except Exception:
            pass
        if self.sys is not None:
            try:
                lg = self.sys.get_object("org.freedesktop.login1",
                                         "/org/freedesktop/login1")
                for what, who, _why, mode, uid, _pid in lg.ListInhibitors(
                        dbus_interface="org.freedesktop.login1.Manager"):
                    if mode == "block" and "idle" in str(what).split(":") \
                            and int(uid) == os.getuid():
                        names.append(str(who))
            except Exception:
                pass
        return sorted(set(names))


def audio_playing():
    """True if any PipeWire output stream node is in state 'running'.

    Not "uncorked": speech-dispatcher keeps an uncorked but idle stream open
    all day, which would count as playing forever.
    """
    try:
        out = subprocess.run(["pw-dump"], capture_output=True, text=True,
                             timeout=10).stdout
        objs = json.loads(out or "[]")
    except Exception:
        return False
    return any(running_output_stream(o) for o in objs)


def running_output_stream(obj):
    info = obj.get("info") or {}
    props = info.get("props") or {}
    return (props.get("media.class") == "Stream/Output/Audio"
            and info.get("state") == "running")


def fullscreen_active():
    """True if the active (XWayland) window is fullscreen.

    Native Wayland windows are not visible here; players of that kind hold a
    Wayland idle inhibitor, which aquarium-wl-idle already reports.
    """
    try:
        out = subprocess.run(["xprop", "-root", "_NET_ACTIVE_WINDOW"],
                             capture_output=True, text=True, timeout=5).stdout
        wid = out.strip().split()[-1]
        if not wid.startswith("0x") or int(wid, 16) == 0:
            return False
        st = subprocess.run(["xprop", "-id", wid, "_NET_WM_STATE"],
                            capture_output=True, text=True, timeout=5).stdout
        return "_NET_WM_STATE_FULLSCREEN" in st
    except Exception:
        return False


class WaylandIdle:
    """Track compositor idle state from aquarium-wl-idle's stdout."""

    def __init__(self, helper, timeout_ms):
        self.active = True  # until the compositor says otherwise
        self.ok = False
        try:
            self.proc = subprocess.Popen([helper, str(timeout_ms)],
                                         stdout=subprocess.PIPE, text=True)
        except Exception as e:
            log(f"wl-idle helper not started ({e}); Wayland inhibitors unseen")
            self.proc = None
            return
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.proc.stdout:
            line = line.strip()
            if line == "ready":
                self.ok = True
            elif line == "idle":
                self.active = False
            elif line == "active":
                self.active = True
        self.ok = False
        log(f"wl-idle helper exited rc={self.proc.wait()}")


def main():
    lock_path = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"),
                             "aquarium-idle-guard.lock")
    lock = open(lock_path, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("aquarium-idle-guard already running", file=sys.stderr)
        return 0
    log(f"start pid={os.getpid()} poll={POLL}s wl_timeout={WL_TIMEOUT_MS}ms")
    inh = Inhibitors()
    wl = WaylandIdle(WL_HELPER, WL_TIMEOUT_MS)
    last = None
    while True:
        if wl.proc is not None and wl.proc.poll() is not None:
            time.sleep(POLL)
            wl = WaylandIdle(WL_HELPER, WL_TIMEOUT_MS)
        blanked = xss_blanked()
        screen = inh.screen()
        audio = fs = False
        if not blanked and not screen and not wl.active:
            audio = audio_playing()
            fs = audio and fullscreen_active()
        action, reason = decide(blanked, screen, wl.active, audio, fs)
        state = (blanked, action, reason)
        if state != last:
            log(f"blanked={blanked} action={action} ({reason})")
            last = state
        if action:
            xss_deactivate()
            if action == "stop":
                log("deactivated running saver: " + reason)
        time.sleep(POLL)


if __name__ == "__main__":
    sys.exit(main())
