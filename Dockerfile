FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps: Xvfb + noVNC for browser visibility, and Chromium system libs.
RUN apt-get update -qq && apt-get install -y --no-install-recommends \
    xvfb \
    x11vnc \
    novnc \
    websockify \
    && rm -rf /var/lib/apt/lists/*

# Install project + browser extras.
COPY pyproject.toml README.md /app/
COPY src /app/src

RUN pip install --upgrade pip && pip install '.[browser]'

# Install Playwright's Chromium binary to a shared path accessible by all users.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN playwright install --with-deps chromium && chmod -R 755 /ms-playwright

# Optional runtime config file.
COPY .env.example /app/.env.example

# Non-root runtime user.
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

# noVNC on 6080, VNC on 5901
EXPOSE 6080 5901

# Start Xvfb + noVNC, then zwis.
CMD ["sh", "-c", "\
    Xvfb :99 -screen 0 1280x800x24 >/dev/null 2>&1 & \
    x11vnc -display :99 -forever -nopw -rfbport 5901 >/dev/null 2>&1 & \
    websockify --web /usr/share/novnc 6080 localhost:5901 >/dev/null 2>&1 & \
    DISPLAY=:99 zwischenzug"]
