ARG RUNTIME_IMAGE=intent-browser-worker:hosted-v1
FROM ${RUNTIME_IMAGE}
USER root
WORKDIR /app
COPY deploy/daylight/control-server.mjs /app/deploy/daylight/
COPY deploy/daylight/lib/sqlite-store.mjs deploy/daylight/lib/harness.mjs deploy/daylight/lib/agent.mjs deploy/daylight/lib/activity.mjs deploy/daylight/lib/manual.mjs deploy/daylight/lib/browse-pool.mjs deploy/daylight/lib/manual-agent.mjs deploy/daylight/lib/library.mjs deploy/daylight/lib/worker-replay.mjs /app/deploy/daylight/lib/
COPY deploy/daylight/vendor/agent_trace /app/deploy/daylight/vendor/agent_trace
COPY scripts/project_worker_trace.py /app/scripts/
COPY scripts/manual_environment.py scripts/manual_browse_runtime.py scripts/shared_browser_policy.py /app/scripts/
COPY config/team_tasks.json config/team_sites.json config/expanded_team_tasks.json /app/config/
RUN mkdir -p /state /manual && chown 10001:10001 /state /manual
ENV DAYLIGHT_SQLITE_PATH=/state/state.sqlite BIND_HOST=0.0.0.0 PORT=8894
USER 10001:10001
ENTRYPOINT ["node", "deploy/daylight/control-server.mjs"]
