#!/bin/sh
# HELP: RadioMuos
# ICON: radiomuos
# GRID: Radio

. /opt/muos/script/var/func.sh

APP_BIN="python3"
SETUP_APP "$APP_BIN" ""

# -----------------------------------------------------------------------------

APPDIR="$1"
cd "$APPDIR" || exit

LOG="/tmp/radiomuos.log"
echo "=== RadioMuos run at $(date) ===" > "$LOG"
echo "APPDIR: $APPDIR" >> "$LOG"

# Kill any leftover mpv
pkill -9 mpv 2>/dev/null
pkill -9 ffmpeg 2>/dev/null
rm -f /tmp/radiomuos_mpv.sock

PM_DIR="$(GET_VAR "device" "storage/rom/mount")/MUOS/PortMaster"
"$PM_DIR"/gptokeyb2 "$APP_BIN" &

python3 "$APPDIR/radio.py" >> "$LOG" 2>&1
EXIT_CODE=$?

kill -9 "$(pidof gptokeyb2)" 2>/dev/null
pkill -9 mpv 2>/dev/null
pkill -9 ffmpeg 2>/dev/null
rm -f /tmp/radiomuos_mpv.sock

echo "Exit code: $EXIT_CODE" >> "$LOG"
exit $EXIT_CODE
