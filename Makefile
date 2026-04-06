.PHONY: install install-browser setup-browser start-vnc help

# ── Installation ─────────────────────────────────────────────────────────────

install:
	pip install '.[browser]'

## Download the Playwright Chromium binary (required for browser tools).
## Needs: pip install zwischenzug[browser]  (or `make install`)
setup-browser:
	playwright install --with-deps chromium

## Install system packages needed for VNC/noVNC visual monitoring.
## Requires apt-get (Debian/Ubuntu). Run with sudo if needed.
install-vnc:
	apt-get install -y --no-install-recommends xvfb x11vnc novnc websockify

# ── Full setup ───────────────────────────────────────────────────────────────

## One-shot: install Python deps + browser binary + VNC system packages.
## Run this once on a fresh VM before starting zwis with browser support.
setup: install setup-browser install-vnc

# ── Runtime ──────────────────────────────────────────────────────────────────

## Start Xvfb + VNC + noVNC in the background, then launch zwis.
## Access the browser at http://localhost:6080 via noVNC.
start-vnc:
	Xvfb :99 -screen 0 1280x800x24 &
	x11vnc -display :99 -forever -nopw -rfbport 5901 &
	websockify --web /usr/share/novnc 6080 localhost:5901 &
	DISPLAY=:99 zwis

# ── Help ─────────────────────────────────────────────────────────────────────

help:
	@echo ""
	@echo "Zwischenzug — browser setup targets"
	@echo ""
	@echo "  make install        Install Python package with browser extras"
	@echo "  make setup-browser  Download Playwright Chromium binary"
	@echo "  make install-vnc    Install Xvfb + VNC system packages (needs apt-get)"
	@echo "  make setup          All of the above (full fresh-VM setup)"
	@echo ""
	@echo "  make start-vnc      Start VNC stack + zwis (browser visible at :6080)"
	@echo ""
