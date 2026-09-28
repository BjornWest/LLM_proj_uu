# Optional standalone calculation image. Build explicitly; runtime never pulls.
# Pin the resulting immutable image ID in evidence and freeze it for evaluations.
FROM python:3.11-slim-bookworm
USER 65534:65534
WORKDIR /tmp
ENTRYPOINT ["python3", "-I", "-S", "-u"]
