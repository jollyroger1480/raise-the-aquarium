#!/usr/bin/env python3
"""
Patch Dream_Aquarium.scr (v1.x) to skip its "is the monitor asleep" check,
which always fails under Wine and causes the screensaver to exit instantly
without rendering anything.

Root cause: at startup the engine calls a monitor power-state check based on
a Windows SetupAPI device-registry query (GetDeviceRegData). Wine's monitor
device enumeration doesn't populate a real PnP monitor device node, so the
query fails, the engine assumes "0 monitors / all asleep", logs:

    about to check if monitors are asleep
    GetDeviceRegData() failed, le = 0
    # Monitors = 0
    areAsleep=1
    *** The monitors were asleep - possible PnP-Monitor, state disabled? (fix in device manager)

...and exits cleanly without ever opening a window. This is a real, currently
unfixed gap in Wine's SetupAPI monitor enumeration -- confirmed unchanged
between Wine 9.0 (distro package) and Wine 11.0 (WineHQ Flatpak), so it's not
a version issue.

This script patches ONE byte: the conditional jump right after the internal
"is asleep" check call is flipped from JE (74) to an unconditional JMP (EB),
so the code always takes the "monitor is awake" branch regardless of what
the (broken, Wine-only) check actually returned. The check call itself still
runs -- no behavior is removed, only the branch decision is forced.

Usage:
    python3 patch_dream_aquarium.py /path/to/Dream_Aquarium.scr

You must own a legitimate copy of Dream Aquarium; this script does not
include, distribute, or require any part of the original binary -- point it
at your own installed copy (typically under
"Program Files (x86)/Dream Aquarium/Dream_Aquarium.scr" in your Wine prefix,
then copy the patched file over C:/windows/DreamAquarium.scr as the app's own
install already expects for screensaver registration).
"""

import sys
import shutil

# Bytes expected at the patch site: `je short +0x4d` (74 4d)
EXPECTED = bytes([0x74, 0x4D])
PATCHED = bytes([0xEB, 0x4D])  # `jmp short +0x4d`

# Located by:
#   1. `strings -a -t x Dream_Aquarium.scr` to find the file offset of the
#      string "about to check if monitors are asleep" (and neighbors).
#   2. `objdump -h` to get .rdata's VMA/file-offset, converting the string's
#      file offset to its runtime virtual address (VA).
#   3. `objdump -d -M intel` over .text, grepping for `push <that VA>` to
#      find the code that logs/uses each string.
#   4. Reading the surrounding disassembly: a `call` at 0x419255 invokes the
#      actual asleep-check function; the very next `test eax,eax; je ...`
#      (at file offset 0x1865c) is the branch that decides asleep-vs-awake.
FILE_OFFSET = 0x1865C


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} /path/to/Dream_Aquarium.scr")
        sys.exit(1)

    path = sys.argv[1]
    backup = path + ".orig-backup"
    shutil.copy2(path, backup)
    print(f"Backup written to {backup}")

    with open(path, "r+b") as f:
        f.seek(FILE_OFFSET)
        current = f.read(2)
        if current == PATCHED:
            print("Already patched -- nothing to do.")
            return
        if current != EXPECTED:
            print(
                f"Unexpected bytes at offset 0x{FILE_OFFSET:x}: "
                f"{current.hex()} (expected {EXPECTED.hex()}). "
                "This may be a different build/version -- aborting without "
                "changing anything. Restore from your own backup if needed."
            )
            sys.exit(2)
        f.seek(FILE_OFFSET)
        f.write(PATCHED)

    print(f"Patched offset 0x{FILE_OFFSET:x}: {EXPECTED.hex()} -> {PATCHED.hex()}")
    print("Done. Copy this file over C:/windows/DreamAquarium.scr in your prefix.")


if __name__ == "__main__":
    main()
