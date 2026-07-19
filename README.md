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

*Salvage crew captained by **Cap'n Jules the Rustjack**.*

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

## The binary fix

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

## How to raise her (binary patch)

1. Install Dream Aquarium normally under Wine — licensing and install were
   never the problem, she'll come aboard just fine.
2. Find her true keel, not the deck copy: **not**
   `C:/windows/DreamAquarium.scr`, but the original in the install
   directory, `C:/Program Files (x86)/Dream Aquarium/Dream_Aquarium.scr`
   (note the underscore).
3. Run the patcher on *that* file:
   ```bash
   python3 patch_dream_aquarium.py "/path/to/wineprefix/drive_c/Program Files (x86)/Dream Aquarium/Dream_Aquarium.scr"
   ```
4. Copy the patched file back over the deck copy — same move the app's own
   official troubleshooting docs already tell laptop users to make for the
   battery-saver case:
   ```bash
   cp "Dream_Aquarium.scr" "$WINEPREFIX/drive_c/windows/DreamAquarium.scr"
   ```
5. Weigh anchor: `wine "C:/windows/DreamAquarium.scr" /s` — she should
   surface fullscreen, fish and all.

Configure tank options (species, sound, etc.) **while unlocked**, from Wine —
not while the screen is locked. Example:

```bash
wine 'C:\Program Files (x86)\Dream Aquarium\Dream_Aquarium.scr'
```

## Bonus: real xscreensaver duty (the part that was half-assed before)

Patch alone gets fish on screen in Wine. Making them a **locked idle
screensaver** under Linux is a second fight. Stock gotchas:

| Symptom | Real cause | Fix in this repo |
|--------|------------|------------------|
| Black screen + you hear tank SFX | Wine drew its own fullscreen window; xscreensaver's canvas stays black | Reparent fish window into `$XSCREENSAVER_WINDOW` |
| Solid Windows-blue flash then fish | `wine explorer /desktop=...` | **Don't** — launch `DreamAquarium.scr /s` directly |
| Password box covers fish at t=0 | xscreensaver always spawns auth when locked | Park/unmap dialog until real key/click |
| Dialog reappears ~2s after hide | xdotool injects XTEST → looks like "user input" | Pure Xlib park; ignore XTEST + Consumer Control |
| Can't click tank options while locked | Input grab belongs to locker | Configure tank unlocked; or delay lock (`lockTimeout`) |

### Files

| File | Role |
|------|------|
| `patch_dream_aquarium.py` | One-byte "monitors asleep" patch + backup |
| `xscreensaver-hack-wrapper.sh` | Launch Wine `/s`, reparent into xss window, optional SFX mute |
| `xss-auth-hide-until-input.py` | Hide unlock dialog until real keyboard/mouse **press** (not motion) |

### Dependencies

```bash
# Debian/Ubuntu/Mint-ish
sudo apt install xscreensaver xdotool xinput python3-xlib
```

Disable competing desktop lock/idle (Cinnamon example) so only xscreensaver
owns the wheel:

```bash
gsettings set org.cinnamon.desktop.screensaver idle-activation-enabled false
# keep a real lock policy in ~/.xscreensaver instead
```

### Wire into `~/.xscreensaver`

```
mode: one
selected: 0
lock: True
# Optional: tank only for N minutes, then require password.
# 0:00:00 = lock the instant the saver starts (password on any real input).
# 0:15:00 = mouse can dismiss without password for the first 15 minutes.
lockTimeout: 0:15:00
fade: False

programs: \
"Dream Aquarium" /path/to/raise-the-aquarium/xscreensaver-hack-wrapper.sh \n\
...
```

`xscreensaver` sets `XSCREENSAVER_WINDOW` for hacks; the wrapper reparents the
Wine window into that drawable. Logs: `/tmp/dream-aquarium-hack.log`.

### Environment knobs

| Variable | Default | Meaning |
|----------|---------|---------|
| `DREAM_AQUARIUM_SOUND` | `1` | `0` mutes tank audio via null Pulse sink |
| `DREAM_AQUARIUM_LOG` | `/tmp/dream-aquarium-hack.log` | Log path |
| `AUTH_HIDE_GRACE` | `8.0` | Seconds after start to ignore settle/XTEST noise |
| `AUTH_HIDE_PY` | auto next to wrapper | Override path to the hide helper |
| `AUTH_ALLOW_SUBSTR` | `mouse,keyboard,ares,logi` | Comma list of xinput name tokens treated as real login devices |
| `WINEPREFIX` | `$HOME/.wine` | Wine prefix |

### Auth-hide design (why not "just xdotool")

An earlier draft parked the password dialog with `xdotool windowmove` and
waited for *any* press on the XI2 stream. That failed in two ways:

1. **Self-unpark** — reparent/`windowmove`/`windowraise` synthesize XTEST
   events; the waiter treated them as "user wants to unlock" within seconds.
2. **Wrong window** — broad name match hit the xscreensaver **daemon**
   (often 1×1) instead of `xscreensaver-auth`.

Current helper:

- Parks with **pure Xlib** only (unmap + opacity 0 + off-screen)
- Accepts only **RawKeyPress / RawButtonPress** from allowlisted devices
- Ignores XTEST, Consumer Control, power/WMI, and motion
- Grace period covers Wine launch + reparent + lock settle
- Never unmaps the daemon window (size/name guards)

Screen **stays locked** the whole time; only the dialog chrome is hidden
until a deliberate press.

### Recommended lock policy

- Want **fish with delayed password**: `lock: True` + `lockTimeout: 0:15:00`
  (or whatever). First N minutes: input exits saver without password.
- Want **always password after idle**: `lockTimeout: 0:00:00` + auth-hide so
  the box doesn't cover the tank until you actually try to unlock.
- Want **no password at all**: `lock: False` (weaker; your call).

### Quick self-test

```bash
# 1) Patch + standalone fish
python3 patch_dream_aquarium.py "$WINEPREFIX/drive_c/Program Files (x86)/Dream Aquarium/Dream_Aquarium.scr"
cp "$WINEPREFIX/drive_c/Program Files (x86)/Dream Aquarium/Dream_Aquarium.scr" \
   "$WINEPREFIX/drive_c/windows/DreamAquarium.scr"
wine 'C:\windows\DreamAquarium.scr' /s

# 2) xscreensaver preview (from xscreensaver-settings → Preview)
#    Expect fish in the preview window, not a black rectangle with audio only.

# 3) Full lock cycle
xscreensaver-command -lock
#    Fish visible; no password chrome until key or click (if lockTimeout=0).
#    Check log:  grep auth-hide-py /tmp/dream-aquarium-hack.log
```

## Ship's manifest

- `patch_dream_aquarium.py` — binary fix (verify, patch, backup)
- `xscreensaver-hack-wrapper.sh` — xscreensaver hack: reparent + sound + auth-hide launch
- `xss-auth-hide-until-input.py` — lock dialog park until real input

Fair winds. 🐠
