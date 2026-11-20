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

If the aquarium-wl-idle helper is missing, cannot connect, or keeps dying,
its state is ignored (never treated as "busy"), so the saver and the lock
still work from the other signals.

Log: $XDG_RUNTIME_DIR/aquarium-idle-guard.log (else ~/.cache), mode 0600,
state changes only.
"""
import fcntl
import json
import os
import subprocess
import sys
import threading
import time

def private_dir():
    """$XDG_RUNTIME_DIR if it is a real dir we own, else ~/.cache."""
    xdg = os.environ.get("XDG_RUNTIME_DIR", "")
    if xdg and os.path.isdir(xdg) and not os.path.islink(xdg) \
            and os.stat(xdg).st_uid == os.getuid():
        return xdg
    d = os.path.join(os.path.expanduser("~"), ".cache")
    os.makedirs(d, mode=0o700, exist_ok=True)
    return d


POLL = float(os.environ.get("AQUARIUM_GUARD_POLL", "10"))
WL_TIMEOUT_MS = int(os.environ.get("AQUARIUM_GUARD_WL_TIMEOUT_MS", "30000"))
WL_RESPAWN = float(os.environ.get("AQUARIUM_GUARD_WL_RESPAWN", "60"))
LOG = os.environ.get("AQUARIUM_GUARD_LOG") or \
    os.path.join(private_dir(), "aquarium-idle-guard.log")
HERE = os.path.dirname(os.path.abspath(__file__))
WL_HELPER = os.environ.get("AQUARIUM_WL_IDLE",
                           os.path.join(HERE, "aquarium-wl-idle"))
CHANGE_SCREEN_SETTINGS = 4  # PowerDevil PolicyAgent policy bit


def clean(text, limit=None):
    """Printable one-line text: app-supplied names may carry newlines."""
    s = "".join(c if c.isprintable() else "?" for c in str(text))
    return s[:limit] if limit else s


def open_private(path, flags):
    """Open without following a symlink; owner-only; refuse others' files."""
    fd = os.open(path, flags | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                 0o600)
    if os.fstat(fd).st_uid != os.getuid():
        os.close(fd)
        raise PermissionError(f"{path} not owned by this user")
    os.fchmod(fd, 0o600)
    return fd


def log(msg):
    line = time.strftime("%H:%M:%S ") + clean(msg) + "\n"
    try:
        fd = open_private(LOG, os.O_WRONLY | os.O_APPEND)
    except OSError:
        return
    try:
        os.write(fd, line.encode())
    finally:
        os.close(fd)


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
                names += [clean(a, 80) for a, _r in lst] \
                    or ["kde-screen-inhibit"]
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
                        names.append(clean(who, 80))
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
    """Track compositor idle state from aquarium-wl-idle's stdout.

    Fail open toward the saver: until the helper is running AND has said
    "ready", and again as soon as it exits, busy() is False. A missing or
    crashing helper must never hold the saver (and the lock) off forever.
    """

    def __init__(self, helper, timeout_ms):
        self.active = False
        self.ok = False
        self.rc = None
        try:
            self.proc = subprocess.Popen([helper, str(timeout_ms)],
                                         stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, text=True)
        except Exception as e:
            log(f"wl-idle helper not started ({e}); using other signals only")
            self.proc = None
            return
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        for line in self.proc.stdout:
            line = line.strip()
            if line == "ready":
                self.active = True   # notification starts in the active state
                self.ok = True
            elif line == "idle":
                self.active = False
            elif line == "active":
                self.active = True
        self.ok = False
        self.active = False
        self.proc.stdout.close()
        self.rc = self.proc.wait()
        log(f"wl-idle helper exited rc={self.rc}; using other signals only")

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def busy(self):
        return self.ok and self.active and self.alive()

    def stop(self):
        if self.alive():
            self.proc.terminate()


def main():
    lock_path = os.path.join(private_dir(), "aquarium-idle-guard.lock")
    lock = os.fdopen(open_private(lock_path, os.O_WRONLY), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("aquarium-idle-guard already running", file=sys.stderr)
        return 0
    log(f"start pid={os.getpid()} poll={POLL}s wl_timeout={WL_TIMEOUT_MS}ms")
    inh = Inhibitors()
    wl = WaylandIdle(WL_HELPER, WL_TIMEOUT_MS)
    wl_started = time.monotonic()
    last = None
    while True:
        # Dead helper: retry at most every WL_RESPAWN s; exit 2 means the
        # compositor lacks the protocol, so stop retrying.
        if not wl.alive() and wl.rc != 2 \
                and time.monotonic() - wl_started >= WL_RESPAWN:
            wl = WaylandIdle(WL_HELPER, WL_TIMEOUT_MS)
            wl_started = time.monotonic()
        wl_busy = wl.busy()
        blanked = xss_blanked()
        screen = inh.screen()
        audio = fs = False
        if not blanked and not screen and not wl_busy:
            audio = audio_playing()
            fs = audio and fullscreen_active()
        action, reason = decide(blanked, screen, wl_busy, audio, fs)
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
