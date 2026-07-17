# Dream Aquarium under Wine/Linux — "monitors asleep" fix

[Dream Aquarium](https://dreamaquarium.com) (v1.x) is a legitimately-purchasable
Windows screensaver. Under Wine on Linux it installs fine, licenses fine, but
exits **instantly** every time you try to run it — no window, no error dialog,
just silence.

## Root cause

The engine runs a startup check to see if the monitor is powered on (so it
doesn't render into a blanked/DPMS'd screen). That check goes through a
Windows SetupAPI device-registry query (`GetDeviceRegData`) to look up a PnP
monitor device. Wine's monitor device enumeration doesn't create a real PnP
monitor device node, so the query fails, and the engine's own log
(`AppData/Roaming/Dream Aquarium/stdout.txt`, with `setVerbose(5, init)` set)
shows:

```
about to check if monitors are asleep
GetDeviceRegData() failed, le = 0
# Monitors = 0

GetDeviceRegData() failed, le = 0
areAsleep=1
are awake=0
*** The monitors were asleep - possible PnP-Monitor, state disabled? (fix in device manager)
```

...and it exits cleanly, having never opened a window. This is **not** a
crash, a driver bug, a config problem, or anything specific to your Wine
setup — it's a real, currently-unpatched gap in Wine's SetupAPI/monitor
device enumeration. Confirmed identical on:

- Wine 9.0 (Ubuntu/Mint distro package)
- Wine 11.0 (WineHQ's official Flatpak, `org.winehq.Wine//stable-25.08`)

So don't burn time chasing a newer Wine version — it won't help. It also
happens the same way whether run via `/s` (screensaver mode), with no
arguments (normal launch), or inside a Wine virtual desktop
(`explorer /desktop=...`) — the check runs unconditionally at startup
regardless of mode.

Build this was found/fixed against: `aqua versions: 1.2705 1.2705 build:4`
(per the app's own startup log). If your `stdout.txt` reports a different
version, check the byte offset still matches before trusting the patch (the
script verifies this for you and refuses to touch anything if it doesn't).

## The fix

One byte. Right after the internal call that performs this (broken-under-Wine)
check, there's:

```asm
419255:  call   0x418930      ; the "is monitor asleep" check
41925a:  test   eax,eax
41925c:  je     0x4192ab      ; <- if the check said "asleep", fall into the failure path
```

Flipping that `je` (`0x74 0x4d`) to an unconditional `jmp`
(`0xEB 0x4d`) — same length, so nothing else shifts — makes it always take the
"awake" path. The check still runs (nothing is removed or skipped), only the
branch decision is forced. `patch_dream_aquarium.py` does exactly this one
byte-for-byte swap, with a verify-before-write guard and an automatic backup.

**This script does not include, distribute, or require any part of the
original Dream Aquarium binary.** Point it at your own installed,
legitimately-licensed copy. You need to own the software already for this to
be useful to you.

## How to use it

1. Install Dream Aquarium normally under Wine (works fine — licensing and
   install are not the problem).
2. Find the real engine binary — **not** the small stub copy in
   `C:/windows/DreamAquarium.scr`, but the original in the install directory:
   `C:/Program Files (x86)/Dream Aquarium/Dream_Aquarium.scr` (note the
   underscore).
3. Run the patcher against *that* file:
   ```
   python3 patch_dream_aquarium.py "/path/to/wineprefix/drive_c/Program Files (x86)/Dream Aquarium/Dream_Aquarium.scr"
   ```
4. Copy the patched file over the stub, exactly like the app's own official
   troubleshooting docs already tell you to do for the "Windows on
   battery/laptop" case:
   ```
   cp "Dream_Aquarium.scr" "C:/windows/DreamAquarium.scr"
   ```
5. Run it: `wine "C:/windows/DreamAquarium.scr" /s` — it should now render
   fullscreen normally.

## Bonus: wiring it up as an actual Linux screensaver (xscreensaver)

Cinnamon (and most modern DEs) dropped support for embedding raw
xscreensaver "hacks" natively, so the practical way to get idle-triggered
behavior + locking is to let `xscreensaver` own both (disable your DE's
competing idle-activation so the two don't fight over the same X11 idle
timer). See `xscreensaver-hack-wrapper.sh` for the launch wrapper referenced
from `~/.xscreensaver`'s `programs:` list.

## Files

- `patch_dream_aquarium.py` — the patch script (verify + patch + backup)
- `xscreensaver-hack-wrapper.sh` — example wrapper for xscreensaver integration
