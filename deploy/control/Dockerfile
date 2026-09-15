ARG RUNTIME_IMAGE=intent-browser-worker:hosted-v1
FROM ${RUNTIME_IMAGE}
USER root
WORKDIR /app
COPY deploy/daylight/control-server.mjs /app/deploy/daylight/
COPY deploy/daylight/lib/sqlite-store.mjs deploy/daylight/lib/harness.mjs deploy/daylight/lib/agent.mjs deploy/daylight/lib/activity.mjs deploy/daylight/lib/manual.mjs /app/deploy/daylight/lib/
COPY scripts/manual_environment.py /app/scripts/
COPY config/team_tasks.json config/team_sites.json /app/config/
RUN mkdir -p /state /manual && chown 10001:10001 /state /manual
ENV DAYLIGHT_SQLITE_PATH=/state/state.sqlite BIND_HOST=0.0.0.0 PORT=8894
USER 10001:10001
ENTRYPOINT ["node", "deploy/daylight/control-server.mjs"]
