FROM python:3.11-slim-bookworm

ARG PLAYWRIGHT_CHROMIUM_MIRROR=https://storage.googleapis.com/chrome-for-testing-public

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    fonts-noto-cjk \
    unzip \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

RUN python -m playwright install-deps chromium

RUN CHROMIUM_INFO="$(python -c "import json; p='/usr/local/lib/python3.11/site-packages/playwright/driver/package/browsers.json'; b=next(x for x in json.load(open(p))['browsers'] if x['name']=='chromium'); print(b['revision'] + ' ' + b['browserVersion'])")" \
    && HEADLESS_INFO="$(python -c "import json; p='/usr/local/lib/python3.11/site-packages/playwright/driver/package/browsers.json'; b=next(x for x in json.load(open(p))['browsers'] if x['name']=='chromium-headless-shell'); print(b['revision'] + ' ' + b['browserVersion'])")" \
    && CHROMIUM_REVISION="${CHROMIUM_INFO%% *}" \
    && CHROMIUM_VERSION="${CHROMIUM_INFO#* }" \
    && HEADLESS_REVISION="${HEADLESS_INFO%% *}" \
    && HEADLESS_VERSION="${HEADLESS_INFO#* }" \
    && curl -fL --retry 5 --retry-delay 3 --connect-timeout 30 \
        "${PLAYWRIGHT_CHROMIUM_MIRROR}/${CHROMIUM_VERSION}/linux64/chrome-linux64.zip" \
        -o /tmp/chrome-linux64.zip \
    && curl -fL --retry 5 --retry-delay 3 --connect-timeout 30 \
        "${PLAYWRIGHT_CHROMIUM_MIRROR}/${HEADLESS_VERSION}/linux64/chrome-headless-shell-linux64.zip" \
        -o /tmp/chrome-headless-shell-linux64.zip \
    && mkdir -p "/ms-playwright/chromium-${CHROMIUM_REVISION}" \
        "/ms-playwright/chromium_headless_shell-${HEADLESS_REVISION}" \
    && unzip -q /tmp/chrome-linux64.zip -d "/ms-playwright/chromium-${CHROMIUM_REVISION}" \
    && unzip -q /tmp/chrome-headless-shell-linux64.zip -d "/ms-playwright/chromium_headless_shell-${HEADLESS_REVISION}" \
    && chmod +x "/ms-playwright/chromium-${CHROMIUM_REVISION}/chrome-linux64/chrome" \
        "/ms-playwright/chromium_headless_shell-${HEADLESS_REVISION}/chrome-headless-shell-linux64/chrome-headless-shell" \
    && touch "/ms-playwright/chromium-${CHROMIUM_REVISION}/INSTALLATION_COMPLETE" \
        "/ms-playwright/chromium-${CHROMIUM_REVISION}/DEPENDENCIES_VALIDATED" \
        "/ms-playwright/chromium_headless_shell-${HEADLESS_REVISION}/INSTALLATION_COMPLETE" \
        "/ms-playwright/chromium_headless_shell-${HEADLESS_REVISION}/DEPENDENCIES_VALIDATED" \
    && rm -f /tmp/chrome-linux64.zip /tmp/chrome-headless-shell-linux64.zip

COPY app ./app
COPY config ./config
COPY data ./data
COPY scripts ./scripts

RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p /app/uploads /app/reports /app/logs \
    && chown -R appuser:appuser /app /ms-playwright

USER appuser

EXPOSE 8100

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8100/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]
