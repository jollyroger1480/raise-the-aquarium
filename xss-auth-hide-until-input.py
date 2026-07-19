#!/usr/bin/env python3
"""Park xscreensaver unlock dialog until a REAL keypress or mouse click.

Screen stays locked (xscreensaver grab). The password box is unmapped,
moved off-screen, and made fully transparent until the user deliberately
tries to log in (physical keyboard key or mouse button 1/2/3).

Critical: ignore XTEST (xdotool/Xlib synthetic events from aquarium
reparent/move). Those used to unpark the dialog ~2s after saver start.
Also ignore Consumer Control / Power / WMI / master devices.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time

from Xlib import X, display
from Xlib.error import BadWindow


OFF_X, OFF_Y = 200000, 200000

# Always ignore: masters + XTEST
ALWAYS_IGNORE_IDS = {2, 3, 4, 5}

# Name substrings that are never a deliberate login attempt
IGNORE_NAME_SUBSTR = (
    "xtest",
    "virtual core",
    "consumer control",
    "system control",
    "power button",
    "hotkeys",
    "wmi",
    "video bus",
    "sleep button",
)

# Name substrings that ARE real login hardware (allowlist when non-empty match).
# Defaults cover generic "mouse" / "keyboard". Add brand tokens via env:
#   AUTH_ALLOW_SUBSTR=ares,logi,razer
# (comma-separated, lowercased). Consumer Control / power keys stay blocked.
_DEFAULT_ALLOW = (
    "mouse",
    "keyboard",       # main "Usb KeyBoard …" — NOT "Consumer Control"
    "ares",           # Cooler Master ARES (example; override via env if unwanted)
    "logi",           # Logitech mice/keyboards
)
_env_allow = os.environ.get("AUTH_ALLOW_SUBSTR", "").strip()
if _env_allow:
    ALLOW_NAME_SUBSTR = tuple(s.strip().lower() for s in _env_allow.split(",") if s.strip())
else:
    ALLOW_NAME_SUBSTR = _DEFAULT_ALLOW


def log(msg: str) -> None:
    path = os.environ.get("DREAM_AQUARIUM_LOG", "/tmp/dream-aquarium-hack.log")
    try:
        with open(path, "a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} auth-hide-py: {msg}\n")
            f.flush()
    except OSError:
        pass


def device_names() -> dict[int, str]:
    """Map xinput device id -> name (lowercased)."""
    out: dict[int, str] = {}
    try:
        text = subprocess.check_output(
            ["xinput", "list", "--name-only"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
        # --name-only alone doesn't give ids; parse full list
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        text = ""
    try:
        text = subprocess.check_output(
            ["xinput", "list"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return out
    # "⎜   ↳ Logi M196 Mouse                         id=16[slave  pointer  (2)]"
    for m in re.finditer(r"↳\s+(.+?)\s+id=(\d+)", text):
        out[int(m.group(2))] = m.group(1).strip().lower()
    return out


def is_login_device(dev_id: int, names: dict[int, str]) -> bool:
    """True only for real keyboard/mouse slaves used for deliberate login."""
    if dev_id in ALWAYS_IGNORE_IDS:
        return False
    name = names.get(dev_id, "")
    if not name:
        # Unknown id — be conservative: reject (was causing false unparks)
        return False
    for bad in IGNORE_NAME_SUBSTR:
        if bad in name:
            return False
    # Require allowlist hit so Consumer Control variants never pass via "keyboard"
    # Special-case: "usb keyboard usb keyboard" without consumer/system is OK
    # via ALLOW "keyboard" only if ignore didn't fire.
    for good in ALLOW_NAME_SUBSTR:
        if good in name:
            return True
    return False


def auth_pids() -> list[int]:
    """PIDs of xscreensaver-auth (comm truncates to xscreensaver-au)."""
    pids: list[int] = []
    try:
        for ent in os.listdir("/proc"):
            if not ent.isdigit():
                continue
            try:
                with open(f"/proc/{ent}/comm") as f:
                    comm = f.read().strip()
                if comm.startswith("xscreensaver-au"):
                    pids.append(int(ent))
                    continue
                with open(f"/proc/{ent}/cmdline", "rb") as f:
                    cl = f.read().replace(b"\x00", b" ").decode("utf-8", "replace")
                if "xscreensaver-auth" in cl:
                    pids.append(int(ent))
            except OSError:
                continue
    except OSError:
        pass
    return pids


def _win_geom(d: display.Display, wid: int) -> tuple[int, int] | None:
    try:
        g = d.create_resource_object("window", wid).get_geometry()
        return int(g.width), int(g.height)
    except Exception:
        return None


def _is_daemon_or_tiny(d: display.Display, wid: int, name_s: str) -> bool:
    """Never park the xscreensaver daemon (often 1x1) or other tiny helpers."""
    if "daemon" in name_s.lower():
        return True
    geom = _win_geom(d, wid)
    if geom is not None:
        w, h = geom
        # Auth dialog is hundreds of px; daemon/splash helpers are tiny
        if w < 80 or h < 40:
            return True
    return False


def window_ids_for_auth(d: display.Display) -> list[int]:
    """Find unlock-dialog windows (auth PID first; never the daemon)."""
    root = d.screen().root
    found: set[int] = set()
    pids = set(auth_pids())

    try:
        kids = list(root.query_tree().children)
    except Exception:
        kids = []

    all_wins = list(kids)
    for w in kids:
        try:
            all_wins.extend(w.query_tree().children)
        except Exception:
            pass
        try:
            for gc in w.query_tree().children:
                try:
                    all_wins.extend(gc.query_tree().children)
                except Exception:
                    pass
        except Exception:
            pass

    for w in all_wins:
        try:
            pid_a = w.get_full_property(d.get_atom("_NET_WM_PID"), X.AnyPropertyType)
            pid = int(pid_a.value[0]) if pid_a else None
            cls = w.get_wm_class()
            name = w.get_wm_name()
            name_s = str(name) if name else ""

            if _is_daemon_or_tiny(d, w.id, name_s):
                continue

            is_auth = False
            # Primary: window owned by xscreensaver-auth
            if pid is not None and pid in pids:
                is_auth = True
            # Title heuristics (password / authentication dialogs only)
            if name_s and (
                "assword" in name_s
                or "uthentication" in name_s
                or "enter password" in name_s.lower()
            ):
                is_auth = True
            if is_auth:
                found.add(w.id)
        except BadWindow:
            continue
        except Exception:
            continue

    # Fallback: xdotool by auth PID only (never broad name "XScreenSaver" —
    # that matches the 1x1 daemon and would unmap it).
    for pid in pids:
        try:
            out = subprocess.check_output(
                ["xdotool", "search", "--pid", str(pid)],
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=1,
            )
            for line in out.split():
                try:
                    wid = int(line.strip())
                except ValueError:
                    continue
                # re-check size/name
                try:
                    wobj = d.create_resource_object("window", wid)
                    name = wobj.get_wm_name() or ""
                except Exception:
                    name = ""
                if _is_daemon_or_tiny(d, wid, str(name)):
                    continue
                found.add(wid)
        except (subprocess.SubprocessError, FileNotFoundError, OSError):
            pass

    for pat in ("assword", "uthenticat", "Enter password"):
        try:
            out = subprocess.check_output(
                ["xdotool", "search", "--name", pat],
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=1,
            )
            for line in out.split():
                try:
                    wid = int(line.strip())
                except ValueError:
                    continue
                try:
                    wobj = d.create_resource_object("window", wid)
                    name = wobj.get_wm_name() or ""
                except Exception:
                    name = ""
                if _is_daemon_or_tiny(d, wid, str(name)):
                    continue
                found.add(wid)
        except (subprocess.SubprocessError, FileNotFoundError, OSError):
            pass

    return list(found)


def set_opacity(d: display.Display, wid: int, opacity_0_1: float) -> None:
    try:
        w = d.create_resource_object("window", wid)
        atom = d.get_atom("_NET_WM_WINDOW_OPACITY")
        val = int(max(0.0, min(1.0, opacity_0_1)) * 0xFFFFFFFF)
        w.change_property(atom, X.CARDINAL, 32, [val])
        d.sync()
    except Exception:
        pass


def move_win_xlib(d: display.Display, wid: int, x: int, y: int) -> None:
    """Pure Xlib move — no xdotool, no XTEST events."""
    try:
        w = d.create_resource_object("window", wid)
        w.configure(x=x, y=y)
        d.sync()
    except Exception:
        pass


def unmap_win(d: display.Display, wid: int) -> None:
    try:
        w = d.create_resource_object("window", wid)
        w.unmap()
        d.sync()
    except Exception:
        pass


def map_win(d: display.Display, wid: int) -> None:
    try:
        w = d.create_resource_object("window", wid)
        w.map()
        d.sync()
    except Exception:
        pass


def park(d: display.Display, wids: list[int]) -> None:
    """Hide as hard as possible: opacity 0 + off-screen + unmap.

    Pure Xlib only — never xdotool (avoids XTEST self-noise).
    """
    for wid in wids:
        set_opacity(d, wid, 0.0)
        move_win_xlib(d, wid, OFF_X, OFF_Y)
        unmap_win(d, wid)


def show_centered(d: display.Display, sw: int, sh: int, wids: list[int]) -> None:
    cx = max(0, sw // 2 - 280)
    cy = max(0, sh // 2 - 160)
    for wid in wids:
        map_win(d, wid)
        set_opacity(d, wid, 1.0)
        move_win_xlib(d, wid, cx, cy)
        try:
            w = d.create_resource_object("window", wid)
            w.configure(stack_mode=X.Above)
            d.sync()
        except Exception:
            pass
        # xdotool raise only on SHOW (user is logging in; XTEST OK now)
        try:
            subprocess.run(
                ["xdotool", "windowmap", str(wid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=1,
            )
            subprocess.run(
                ["xdotool", "windowmove", str(wid), str(cx), str(cy)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=1,
            )
            subprocess.run(
                ["xdotool", "windowraise", str(wid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=1,
            )
        except Exception:
            pass


def wine_alive() -> bool:
    wine_pid = os.environ.get("AQUARIUM_WINE_PID")
    if not wine_pid:
        return True
    try:
        os.kill(int(wine_pid), 0)
        return True
    except OSError:
        return False


def wait_real_login_input(grace: float, stop: threading.Event, names: dict[int, str]) -> str | None:
    """Block until real login device RawKeyPress or RawButtonPress after grace.

    Uses xinput test-xi2 so we see events even when xscreensaver has the grab.
    """
    t0 = time.time()
    try:
        proc = subprocess.Popen(
            ["xinput", "test-xi2", "--root"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError:
        log("xinput missing — fallback pointer-button poll")
        return wait_fallback_click(grace, stop)

    # XI2: "device: 2 (16)" → master 2, source slave 16 — use source in parens
    device_re = re.compile(r"device:\s*(\d+)(?:\s*\((\d+)\))?")
    detail_re = re.compile(r"detail:\s*(\d+)")
    last_event: str | None = None
    pending_source: int | None = None
    rejects = 0
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            if stop.is_set() or not wine_alive():
                break
            line = line.strip()
            if "EVENT type" in line:
                last_event = None
                pending_source = None
                if "RawKeyPress" in line:
                    last_event = "key"
                elif "RawButtonPress" in line:
                    last_event = "button"
                # deliberately ignore RawMotion, RawKeyRelease, RawButtonRelease,
                # KeyPress/ButtonPress (cooked — often XTEST after inject)
                continue
            if not last_event:
                continue
            if line.startswith("device:"):
                m = device_re.search(line)
                if not m:
                    last_event = None
                    continue
                source = int(m.group(2)) if m.group(2) else int(m.group(1))
                if not is_login_device(source, names):
                    rejects += 1
                    if rejects <= 8 or rejects % 50 == 0:
                        log(
                            f"ignore {last_event} source={source} "
                            f"name={names.get(source, '?')!r} (reject#{rejects})"
                        )
                    last_event = None
                    pending_source = None
                    continue
                pending_source = source
                if last_event == "key":
                    if time.time() - t0 < grace:
                        log(f"grace-drop key source={source} name={names.get(source)!r}")
                        last_event = None
                        pending_source = None
                        continue
                    kind = last_event
                    last_event = None
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                    return f"{kind} source={source} name={names.get(source)!r}"
                continue
            if last_event == "button" and pending_source is not None and line.startswith("detail:"):
                dm = detail_re.search(line)
                btn = int(dm.group(1)) if dm else 0
                # Only primary mouse buttons — never wheel / extra side noise
                if btn not in (1, 2, 3):
                    last_event = None
                    pending_source = None
                    continue
                if time.time() - t0 < grace:
                    log(f"grace-drop button={btn} source={pending_source}")
                    last_event = None
                    pending_source = None
                    continue
                kind = last_event
                src = pending_source
                last_event = None
                pending_source = None
                try:
                    proc.terminate()
                except Exception:
                    pass
                return f"{kind} source={src} button={btn} name={names.get(src)!r}"
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=1)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    return None


def wait_fallback_click(grace: float, stop: threading.Event) -> str | None:
    """If xinput unavailable: require a held mouse button after grace (no motion)."""
    d = display.Display(os.environ.get("DISPLAY", ":0"))
    root = d.screen().root
    t0 = time.time()
    while not stop.is_set() and wine_alive():
        if time.time() - t0 < grace:
            time.sleep(0.05)
            continue
        try:
            ptr = root.query_pointer()
            if ptr.mask & 0x700:  # any button
                return f"button-mask={ptr.mask:#x}"
        except Exception:
            pass
        time.sleep(0.05)
    return None


def main() -> int:
    dpy_name = os.environ.get("DISPLAY", ":0")
    d = display.Display(dpy_name)
    sw = d.screen().width_in_pixels
    sh = d.screen().height_in_pixels
    # Default 8s: covers wine launch + reparent + xss lock settle
    grace = float(os.environ.get("AUTH_HIDE_GRACE", "8.0"))

    names = device_names()
    login_devs = {i: n for i, n in names.items() if is_login_device(i, names)}
    log(
        f"start DISPLAY={dpy_name} screen={sw}x{sh} grace={grace}s "
        f"login_devs={login_devs}"
    )

    stop = threading.Event()
    revealed = threading.Event()
    park_count = {"n": 0}

    def parker() -> None:
        """Continuously unmap/park auth dialogs until revealed or stop."""
        last_ids: list[int] = []
        while not stop.is_set() and wine_alive() and not revealed.is_set():
            ids = window_ids_for_auth(d)
            if ids:
                if ids != last_ids:
                    log(f"parking auth windows: {[hex(i) for i in ids]}")
                    last_ids = ids
                park(d, ids)
                park_count["n"] += 1
                if park_count["n"] == 1:
                    log("first park done (unmap+opacity0+offscreen)")
            time.sleep(0.03)

    park_thread = threading.Thread(target=parker, name="auth-parker", daemon=True)
    park_thread.start()

    reason = wait_real_login_input(grace, stop, names)
    if not wine_alive():
        log("wine gone — exit before show")
        stop.set()
        return 0

    if reason:
        log(f"REAL input {reason} — show unlock dialog (parks={park_count['n']})")
        revealed.set()
        time.sleep(0.1)
        for _ in range(16):
            ids = window_ids_for_auth(d)
            if ids:
                show_centered(d, sw, sh, ids)
            time.sleep(0.06)
        while wine_alive():
            ids = window_ids_for_auth(d)
            if ids:
                show_centered(d, sw, sh, ids)
            time.sleep(0.25)
    else:
        log("input wait ended without press")

    stop.set()
    log("exit")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
