FROM node:22-bookworm-slim AS node-runtime
FROM python:3.12-slim-bookworm

# The optional, separately mounted Chaos build needs Node but no npm installer.
COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright \
    HARNESS_DATA_DIR=/data

WORKDIR /app
COPY deploy/worker/requirements.txt /tmp/worker-requirements.txt
RUN python -m pip install --no-cache-dir -r /tmp/worker-requirements.txt \
    && python -m playwright install --with-deps chromium \
    && apt-get update \
    && apt-get install -y --no-install-recommends iproute2 libstdc++6 \
    && chmod -R a+rX /opt/playwright \
    && rm -rf /var/lib/apt/lists/* /tmp/worker-requirements.txt

# Deliberate COPY allowlist: never copy .env, .local, runs or the research corpus.
COPY pyproject.toml /app/pyproject.toml
COPY intent_browser /app/intent_browser
COPY environments/demo /app/environments/demo
COPY config/chaos_verifier.json config/team_tasks.json /app/config/
COPY scripts/start_chaos_repair.py scripts/inspect_chaos.mjs /app/scripts/
RUN python -m pip install --no-cache-dir --no-deps -e /app \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin worker \
    && mkdir -p /data \
    && chown worker:worker /data

USER 10001:10001
CMD ["python", "-m", "intent_browser.team_worker"]
