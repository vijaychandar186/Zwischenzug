#!/usr/bin/env bash
# Start Xvfb + fluxbox + x11vnc + noVNC so you can watch the browser agent live.
# Access via: https://<codespace>-6080.app.github.dev/vnc.html
set -euo pipefail

DISPLAY_NUM="${DISPLAY_NUM:-99}"
VNC_PORT="${VNC_PORT:-5901}"
NOVNC_PORT="${NOVNC_PORT:-6080}"

export DISPLAY=":${DISPLAY_NUM}"

# Clean up stale processes and lock files from previous runs
pkill -f "Xvfb :${DISPLAY_NUM}" 2>/dev/null || true
pkill x11vnc 2>/dev/null || true
pkill websockify 2>/dev/null || true
pkill fluxbox 2>/dev/null || true
sleep 1
rm -f "/tmp/.X${DISPLAY_NUM}-lock" "/tmp/.X11-unix/X${DISPLAY_NUM}"

echo "Starting virtual display :${DISPLAY_NUM}..."
Xvfb "${DISPLAY}" -screen 0 3840x2160x24 -ac &
sleep 1

echo "Starting window manager..."
fluxbox &
sleep 0.5

echo "Starting VNC server on port ${VNC_PORT}..."
x11vnc -display "${DISPLAY}" -forever -nopw -rfbport "${VNC_PORT}" -shared -bg -o /tmp/x11vnc.log

echo "Starting noVNC web client on port ${NOVNC_PORT}..."
websockify --web /usr/share/novnc "${NOVNC_PORT}" "localhost:${VNC_PORT}" &

echo ""
echo "=========================================="
echo "  Browser Agent Viewer is ready!"
echo "  Open port ${NOVNC_PORT} in your browser"
echo "  (Codespaces will auto-forward it)"
echo "=========================================="
echo ""
echo "DISPLAY=${DISPLAY} is set. Run the browser agent now."

# Keep running
wait
