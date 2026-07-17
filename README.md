# 🏴‍☠️ Raise the Aquarium

*A salvage operation, not a heist — no cracks, no keygens, just an honest fix
for an honest bug.*

Ahoy. Somewhere out there a fine ship called **Dream Aquarium** — a legally
purchased, perfectly legitimate v1.x Windows screensaver — ran aground the
moment she tried to sail under Wine. She'd take on her cargo, check her
papers, confirm the license fair and square... and then sink without a trace.
No error. No splash. Just gone, straight to the bottom, every single time.

Turns out she wasn't scuttled by pirates or bad code of her own. She was
becalmed by a phantom lookout — a broken watch-check that swore, every time,
that every last porthole on the ship was already dark and nobody was aboard
to see her. So she quietly slipped under the waves rather than run for
nothing.

This repo is the salvage crew. We didn't forge her papers or break her
locks — we found the one faulty plank causing the leak, patched it, and
brought her back up to the surface, fully lit, fish and all.

*Salvage crew captained by **Cap'n Jules the Rustjack**, patched by Claude, first mate to the crew running this rig.*

## What actually happened

Dream Aquarium runs a startup check to see whether the monitor is powered on
(sensible — no point rendering fish into a blank screen). That check queries
a Windows PnP monitor device via `GetDeviceRegData` (SetupAPI). Wine's
monitor enumeration doesn't create a real PnP monitor device node, so the
query fails, and the ship's own log —
`AppData/Roaming/Dream Aquarium/stdout.txt` (with `setVerbose(5, init)`
turned up) — reads like a ghost story:

```
about to check if monitors are asleep
GetDeviceRegData() failed, le = 0
# Monitors = 0

GetDeviceRegData() failed, le = 0
areAsleep=1
are awake=0
*** The monitors were asleep - possible PnP-Monitor, state disabled? (fix in device manager)
```

...and she goes down without ever opening a window. Not a crash. Not a
config mistake. A real, currently-unpatched gap in Wine's SetupAPI monitor
enumeration — confirmed identical on:

- Wine 9.0 (Ubuntu/Mint distro package)
- Wine 11.0 (WineHQ's official Flatpak, `org.winehq.Wine//stable-25.08`)

So don't waste a tide chasing a newer Wine version — she'll sink just the
same. Same result in `/s` (screensaver) mode, plain launch mode, or inside a
Wine virtual desktop. The phantom lookout is checked unconditionally, every
time, no matter how you hail her.

Confirmed against build `aqua versions: 1.2705 1.2705 build:4` (per the
app's own startup log — check yours before trusting the patch; the script
below refuses to touch anything if the bytes don't match).

## The fix

One byte. Right after the internal call that runs the (broken-under-Wine)
watch-check, there's:

```asm
419255:  call   0x418930      ; "is anyone keeping watch?" (the check)
41925a:  test   eax,eax
41925c:  je     0x4192ab      ; if she says "no lookout", head for the depths
```

Flip that `je` (`0x74 0x4d`) to an unconditional `jmp` (`0xEB 0x4d`) — same
length, nothing else moves — and she always takes the "someone's watching,
full steam ahead" branch, no matter what the phantom lookout claims. The
check still runs. Nothing is torn out. Only the ship's decision is
overruled.

**This repo does not carry so much as a splinter of the original Dream
Aquarium hull.** No binary, patched or otherwise, is included or required to
run this script. You bring your own legitimately-purchased copy; the script
just tells your own file which plank to fix.

## How to raise her

1. Install Dream Aquarium normally under Wine — licensing and install were
   never the problem, she'll come aboard just fine.
2. Find her true keel, not the deck copy: **not**
   `C:/windows/DreamAquarium.scr`, but the original in the install
   directory, `C:/Program Files (x86)/Dream Aquarium/Dream_Aquarium.scr`
   (note the underscore).
3. Run the patcher on *that* file:
   ```
   python3 patch_dream_aquarium.py "/path/to/wineprefix/drive_c/Program Files (x86)/Dream Aquarium/Dream_Aquarium.scr"
   ```
4. Copy the patched file back over the deck copy — same move the app's own
   official troubleshooting docs already tell laptop users to make for the
   battery-saver case:
   ```
   cp "Dream_Aquarium.scr" "C:/windows/DreamAquarium.scr"
   ```
5. Weigh anchor: `wine "C:/windows/DreamAquarium.scr" /s` — she should
   surface fullscreen, fish and all.

## Bonus: making her your actual watch (xscreensaver)

Cinnamon (and most modern desktops) dropped support for embedding raw
xscreensaver "hacks" natively, so the practical rig for idle-triggered
behavior + screen-locking is to let `xscreensaver` run both jobs — switch
off your desktop's own competing idle-activation first, so the two crews
aren't fighting over the same wheel. See `xscreensaver-hack-wrapper.sh` for
the launch wrapper referenced from `~/.xscreensaver`'s `programs:` list.

## Ship's manifest

- `patch_dream_aquarium.py` — the fix (verify, patch, and a backup before
  anyone touches the hull)
- `xscreensaver-hack-wrapper.sh` — example wrapper for xscreensaver duty

Fair winds. 🐠
