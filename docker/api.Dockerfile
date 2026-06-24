# Cassette - Agent Execution Tracer & Deterministic Replay Engine
# Backend image: FastAPI served by uvicorn on port 8000.
#
# No API key is needed for replay/analysis demo. A key is only required for
# recording fresh runs and can be supplied at runtime via the environment.
#
# Build context is the repo root (see docker-compose.yml: context: .).

FROM python:3.12-slim

WORKDIR /app

# git: clone imported agents. ca-certificates: TLS roots for the recording proxy.
# build-essential: compiler toolchain for mitmproxy's C extensions (Brotli,
# zstandard) which build from source on the slim image.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install API runtime dependencies first for better layer caching.
# Upgrade pip so it selects modern manylinux wheels (the bundled 25.0.1 pulled an
# unbuildable old zstandard sdist on Python 3.12).
COPY requirements-api.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements-api.txt

# Copy the rest of the project (see .dockerignore for exclusions).
COPY . .

EXPOSE 8000

CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8000"]
