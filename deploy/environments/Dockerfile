# Preparation is separate from rollouts. This existing image already contains
# Python, Node, Chromium and BrowserGym; no package installation at startup.
ARG RUNTIME_IMAGE=intent-browser-worker:hosted-v1
FROM ${RUNTIME_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/package/runtime
WORKDIR /tmp
USER 10001:10001
ENTRYPOINT ["python", "-m", "intent_browser.environment_runtime", "--package", "/package"]
