#!/bin/bash
# Example xscreensaver "hack" wrapper for a patched Dream Aquarium install.
# Reference this script's path from the `programs:` list in ~/.xscreensaver,
# e.g.:
#   "Dream Aquarium" /path/to/xscreensaver-hack-wrapper.sh
#
# Adjust WINEPREFIX to wherever you installed it.

export WINEPREFIX="$HOME/.wine"
exec wine "C:\\windows\\DreamAquarium.scr" /s
