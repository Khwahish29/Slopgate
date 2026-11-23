# SlopGate reproduction sandbox. Build:  docker build -t slopgate-sandbox sandbox/
# Run through sandbox/launcher.py, which adds the isolation flags (no network, read-only root, no capabilities).
FROM debian:12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends gcc g++ clang make cmake libc6-dev python3 valgrind xxd ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --uid 10001 --create-home --shell /usr/sbin/nologin sandbox \
 && mkdir -p /work /repo && chown sandbox /work

COPY runner.py /opt/slopgate/runner.py

USER sandbox
WORKDIR /work
ENV SLOPGATE_WORK=/work PYTHONDONTWRITEBYTECODE=1
ENTRYPOINT ["python3", "/opt/slopgate/runner.py"]
