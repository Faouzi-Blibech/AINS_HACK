# docker/agent-runner.Dockerfile
# Generic runner: records an imported agent in isolation. mitmproxy generates &
# trusts its own CA in-container; the agent_shim adds Python certifi trust + SDK wrap.
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/cassette
# Recorder-side packages only — no cassette/ package.
COPY recorder/ ./recorder/
COPY trace_store/ ./trace_store/
COPY replay_engine/ ./replay_engine/
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# agent_shim must be importable as top-level `sitecustomize` via PYTHONPATH.
ENV PYTHONPATH=/opt/cassette:/opt/cassette/recorder/agent_shim
WORKDIR /workspace
ENTRYPOINT ["python", "-m", "recorder.import_agent.driver"]
