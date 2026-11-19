#!/bin/bash
# Scripted reproduction of xscreensaver's cycle restart (cycle: 0:10:00).
#
# Every `cycle` xscreensaver sends SIGTERM to the running hack and starts a
# fresh copy straight away. This test does the same with stubbed wine / X
# tools, so nothing touches the real display:
#   1. start hack A, let it settle
#   2. SIGTERM A and start hack B at once (what xscreensaver does)
#   3. A must exit, and B's tank must still be running afterwards
#   4. unblank: B must exit and leave no tank behind
#
# Usage: tests/test_cycle_restart.sh [path/to/hack.sh]
# Exit 0 = pass. Refuses to run while a real Dream Aquarium tank is up.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
HACK="${1:-$HERE/../xscreensaver-hack-wrapper.sh}"
HACK="$(readlink -f "$HACK")"
TAG="aquatest$$"

if ps -eo args= | grep -E '[D]reamAquarium\.scr|[D]ream_Aquarium\.scr' | grep -q .; then
  echo "SKIP: a real Dream Aquarium tank is running"; exit 77
fi

W="$(mktemp -d)"
trap 'rm -rf "$W"' EXIT
mkdir -p "$W/bin"
STATE="$W/xss_state"; echo blanked >"$STATE"

# wine: become a long-lived process whose argv matches the tank pattern.
cat >"$W/bin/wine" <<EOF
#!/bin/bash
exec -a "C:\\\\windows\\\\DreamAquarium.scr-$TAG" sleep 600
EOF
cat >"$W/bin/xdotool" <<'EOF'
#!/bin/bash
[ "$1" = search ] && echo 0x4000001
exit 0
EOF
cat >"$W/bin/xwininfo" <<'EOF'
#!/bin/bash
printf '  Absolute upper-left X:  0\n  Absolute upper-left Y:  0\n  Width: 3840\n  Height: 2160\n'
EOF
cat >"$W/bin/xdpyinfo" <<'EOF'
#!/bin/bash
echo '  dimensions:    3840x2160 pixels'
EOF
cat >"$W/bin/xscreensaver-command" <<EOF
#!/bin/bash
case "\$1" in
  -time) echo "XScreenSaver 6.08: screen \$(cat "$STATE") since now (hack #1)";;
esac
exit 0
EOF
printf '#!/bin/bash\nexit 0\n' >"$W/bin/pactl"
printf 'import time\ntime.sleep(600)\n' >"$W/auth.py"
chmod +x "$W/bin/"*

export PATH="$W/bin:$PATH" AUTH_HIDE_PY="$W/auth.py" XSCREENSAVER_WINDOW=0x1
export DREAM_AQUARIUM_LOG="$W/hack.log" DISPLAY=:99

# Tag goes in via ENVIRON and the regex is bracketed so awk never matches itself.
tank() { ps -eo pid=,args= | T="$TAG" awk 'index($0,ENVIRON["T"]) && /[D]reamAquarium/ {print $1}'; }
alive() { kill -0 "$1" 2>/dev/null; }

fail=0
"$HACK" & A=$!
sleep 3
TA=$(tank)
echo "A=$A tank=$TA"

# xscreensaver cycle: TERM the old hack, start the new one immediately.
kill -TERM "$A"
"$HACK" & B=$!
sleep 6
TB=$(tank)
echo "B=$B tank=${TB:-none}"

if alive "$A"; then echo "FAIL: hack A ignored SIGTERM (still running 6s later)"; fail=1
else echo "ok: hack A exited on SIGTERM"; fi
if [ -z "$TB" ]; then echo "FAIL: new hack B has no tank (fish gone after cycle)"; fail=1
else echo "ok: hack B tank alive ($TB)"; fi

echo non-blanked >"$STATE"
sleep 4
if alive "$B"; then echo "FAIL: hack B still running after unblank"; fail=1
else echo "ok: hack B exited on unblank"; fi
LEFT=$(tank)
if [ -n "$LEFT" ]; then echo "FAIL: leftover tank $LEFT"; fail=1
else echo "ok: no leftover tank"; fi

# clean up anything this test started
for p in $A $B $(tank); do kill -KILL "$p" 2>/dev/null; done
wait 2>/dev/null
echo "--- hack log (last run)"; tail -n 15 "$DREAM_AQUARIUM_LOG"
[ "$fail" -eq 0 ] && echo PASS || echo FAIL
exit "$fail"
