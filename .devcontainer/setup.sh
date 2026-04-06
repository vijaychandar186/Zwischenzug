#!/usr/bin/env bash
set -euo pipefail

# Install project deps plus browser runtime required by browser-use/Playwright.
pip install -e '.[browser,dev]'

# Install Chromium and its system dependencies.
# `install-deps` auto-detects the distro and installs the right packages.
python -m playwright install --with-deps chromium
