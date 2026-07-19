#!/bin/bash
# Dream Aquarium as an xscreensaver "hack".
#
# Wine .scr cannot draw into $XSCREENSAVER_WINDOW (it always creates its own
# window). We launch the scr, find its window, reparent into the saver window.
#
# Do NOT use `wine explorer /desktop=...` — that paints a solid Windows-blue
# desktop for a few seconds before the fish appear.

export WINEPREFIX="${WINEPREFIX:-$HOME/.wine}"
export WINEDEBUG="${WINEDEBUG:--all}"
export DISPLAY="${DISPLAY:-:0}"
export XCURSOR_SIZE="${XCURSOR_SIZE:-72}"

# Resolve companion scripts next to this file (repo install) or ~/scripts fallback.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUTH_HIDE_PY="${AUTH_HIDE_PY:-}"
if [ -z "$AUTH_HIDE_PY" ]; then
  if [ -f "$SCRIPT_DIR/xss-auth-hide-until-input.py" ]; then
    AUTH_HIDE_PY="$SCRIPT_DIR/xss-auth-hide-until-input.py"
  elif [ -f "$HOME/scripts/xss-auth-hide-until-input.py" ]; then
    AUTH_HIDE_PY="$HOME/scripts/xss-auth-hide-until-input.py"
  else
    AUTH_HIDE_PY="$SCRIPT_DIR/xss-auth-hide-until-input.py"
  fi
fi

LOG="${DREAM_AQUARIUM_LOG:-/tmp/dream-aquarium-hack.log}"
SCR='C:\windows\DreamAquarium.scr'
TARGET="${XSCREENSAVER_WINDOW:-}"

# Tank SFX ON by default. Set DREAM_AQUARIUM_SOUND=0 to mute.
DREAM_AQUARIUM_SOUND="${DREAM_AQUARIUM_SOUND:-1}"

log() { printf '%s %s\n' "$(date '+%H:%M:%S')" "$*" >>"$LOG"; }

geom_of() {
  xwininfo -id "$1" 2>/dev/null | awk '
    /Absolute upper-left X/ {x=$NF}
    /Absolute upper-left Y/ {y=$NF}
    /^ *Width:/  {w=$NF}
    /^ *Height:/ {h=$NF}
    END { if (w>0 && h>0) printf "%d %d %d %d\n", x+0, y+0, w, h }
  '
}

ensure_silent_sink() {
  command -v pactl >/dev/null 2>&1 || return 1
  if ! pactl list short sinks 2>/dev/null | grep -q $'^[^[:space:]]\+[[:space:]]\+aquarium_silent[[:space:]]'; then
    pactl load-module module-null-sink \
      sink_name=aquarium_silent \
      sink_properties=device.description="Dream_Aquarium_silent" \
      >/dev/null 2>&1 || return 1
  fi
  export PULSE_SINK=aquarium_silent
  export PIPEWIRE_NODE=aquarium_silent
  return 0
}

kill_old_aquarium() {
  local pids
  pids=$(ps -eo pid=,args= | awk '
    BEGIN{IGNORECASE=1}
    /DreamAquarium\.scr|Dream_Aquarium\.scr|explorer.*DreamAq|desktop=DreamAq/ {print $1}
  ')
  if [ -n "$pids" ]; then
    log "killing prior aquarium pids: $pids"
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null || true
    sleep 0.25
  fi
}

# Prefer real tank window over tiny helper / wine dialogs
pick_best_window() {
  local best="" best_area=0 id ww hh area
  for id in "$@"; do
    [ -n "$id" ] || continue
    wh=$(xwininfo -id "$id" 2>/dev/null | awk '/^ *Width:/ {w=$NF} /^ *Height:/ {h=$NF} END {print w+0, h+0}')
    read -r ww hh <<<"$wh"
    [ "${ww:-0}" -ge 200 ] && [ "${hh:-0}" -ge 200 ] || continue
    area=$((ww * hh))
    if [ "$area" -gt "$best_area" ]; then
      best=$id
      best_area=$area
    fi
  done
  echo "$best"
}

: >"$LOG"
log "start DISPLAY=$DISPLAY TARGET=${TARGET:-none} SOUND=$DREAM_AQUARIUM_SOUND"

kill_old_aquarium
rm -f /tmp/dream-aquarium-show-auth

if [ "$DREAM_AQUARIUM_SOUND" = "0" ]; then
  if ensure_silent_sink; then
    log "audio muted"
  else
    log "WARN: mute failed"
  fi
else
  unset PULSE_SINK PIPEWIRE_NODE
  log "audio ENABLED"
fi

if [ -n "$TARGET" ]; then
  read -r SX SY SW SH <<<"$(geom_of "$TARGET")"
  if [ -z "${SW:-}" ] || [ -z "${SH:-}" ]; then
    read -r SW SH <<<"$(xdpyinfo 2>/dev/null | awk '/dimensions:/ {split($2,a,"x"); print a[1], a[2]}')"
    SX=0; SY=0
  fi
else
  read -r SW SH <<<"$(xdpyinfo 2>/dev/null | awk '/dimensions:/ {split($2,a,"x"); print a[1], a[2]}')"
  SX=0; SY=0
fi
SW=${SW:-3840}
SH=${SH:-2160}
log "geom ${SX:-0},${SY:-0} ${SW}x${SH}"

# Direct screensaver mode — no explorer desktop (avoids blue flash).
log "launch wine $SCR /s"
# Don't capture Wine stdout — the engine spams single-char noise into the log.
wine "$SCR" /s >/dev/null 2>&1 &
WPID=$!
log "wine pid=$WPID"

AUTH_HIDE_PID=""

cleanup() {
  log "cleanup"
  [ -n "${AUTH_HIDE_PID:-}" ] && kill "$AUTH_HIDE_PID" 2>/dev/null || true
  # also kill any leftover hide helpers
  pkill -f 'xss-auth-hide-until-input.py' 2>/dev/null || true
  kill "$WPID" 2>/dev/null || true
  pkill -P "$WPID" 2>/dev/null || true
  # leftover scr if wine parent already gone
  pids=$(ps -eo pid=,args= | awk 'BEGIN{IGNORECASE=1} /DreamAquarium\.scr|Dream_Aquarium\.scr/ {print $1}')
  # shellcheck disable=SC2086
  [ -n "$pids" ] && kill $pids 2>/dev/null || true
}
trap cleanup EXIT INT TERM HUP

# Start hide ASAP — reparent/xdotool uses XTEST and used to unpark the dialog.
# Grace ignores synthetic + settle noise; only real key/click after grace shows box.
# Pure-Xlib unmap park (no xdotool) so self-generated XTEST cannot unpark.
# Requires: python3-xlib, xinput, xdotool. See README.
if [ -f "$AUTH_HIDE_PY" ]; then
  log "auth-hide: starting $AUTH_HIDE_PY (grace=${AUTH_HIDE_GRACE:-8.0}s)"
  export AQUARIUM_WINE_PID="$WPID"
  export AUTH_HIDE_GRACE="${AUTH_HIDE_GRACE:-8.0}"
  python3 "$AUTH_HIDE_PY" >>"$LOG" 2>&1 &
  AUTH_HIDE_PID=$!
  log "auth-hide: py pid=$AUTH_HIDE_PID"
else
  log "WARN: auth-hide missing at $AUTH_HIDE_PY — password dialog may cover tank immediately"
fi

FOUND=""
REPARENTED=0
deadline=$((SECONDS + 40))
while [ "$SECONDS" -lt "$deadline" ]; do
  ids=$(xdotool search --pid "$WPID" 2>/dev/null || true)
  # Also catch child scr process windows
  for cpid in $(pgrep -P "$WPID" 2>/dev/null); do
    ids="$ids $(xdotool search --pid "$cpid" 2>/dev/null || true)"
  done
  # Name hints used by the aquarium / wine
  ids="$ids $(xdotool search --name 'Dream' 2>/dev/null || true)"
  ids="$ids $(xdotool search --name 'Aquarium' 2>/dev/null || true)"

  FOUND=$(pick_best_window $ids)
  if [ -n "$FOUND" ]; then
    wh=$(xwininfo -id "$FOUND" 2>/dev/null | awk '/^ *Width:/ {w=$NF} /^ *Height:/ {h=$NF} END {print w+0, h+0}')
    log "found window id=$FOUND size=$wh"
    if [ -n "$TARGET" ]; then
      if xdotool windowreparent "$FOUND" "$TARGET" 2>>"$LOG"; then
        log "reparented $FOUND -> $TARGET"
        REPARENTED=1
      else
        log "reparent failed; raise/move fallback"
        xdotool windowmove "$FOUND" "${SX:-0}" "${SY:-0}" 2>>"$LOG" || true
      fi
      xdotool windowmove "$FOUND" 0 0 2>>"$LOG" || true
      xdotool windowsize "$FOUND" "$SW" "$SH" 2>>"$LOG" || true
      xdotool windowmap "$FOUND" 2>>"$LOG" || true
      xdotool windowraise "$FOUND" 2>>"$LOG" || true
    else
      xdotool windowmove "$FOUND" 0 0 2>>"$LOG" || true
      xdotool windowsize "$FOUND" "$SW" "$SH" 2>>"$LOG" || true
      xdotool windowraise "$FOUND" 2>>"$LOG" || true
    fi
    break
  fi
  if ! kill -0 "$WPID" 2>/dev/null; then
    log "wine exited before window appeared"
    break
  fi
  sleep 0.15
done

if [ -z "$FOUND" ]; then
  log "ERROR: no Wine window found"
fi

# Keep surface above black blanker if we could not reparent.
# Do NOT raise fish over auth once user has revealed the dialog
# (hide script owns auth stacking after real key/click).
if [ "$REPARENTED" -eq 0 ] && [ -n "$FOUND" ]; then
  while kill -0 "$WPID" 2>/dev/null; do
    xdotool windowraise "$FOUND" 2>/dev/null || true
    sleep 2
  done
fi

wait "$WPID" 2>/dev/null || true
log "exit"
