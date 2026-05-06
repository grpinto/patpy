# syntax=docker/dockerfile:1.7
# Slim image that installs patpy-analysis-mcp from this monorepo and runs the
# stdio server. Build from the repository root so that the shared `LICENSE`
# file (referenced from `mcp-analysis/pyproject.toml`) is part of the build
# context:
#
#     docker build -t patpy-analysis-mcp -f mcp-analysis/Dockerfile .
#
# NOTE: this image is large (~3 GB) because patpy pulls scanpy, anndata,
# matplotlib, scikit-learn, etc. If you only need dataset discovery, use the
# much lighter mcp/Dockerfile (patpy-mcp) instead.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PATPY_MCP_CACHE=/data/cache \
    MPLBACKEND=agg

# scanpy / anndata / matplotlib transitive C-extensions need a few build deps;
# install them, then strip in the same layer to keep the image small.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libhdf5-dev \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash patpy

WORKDIR /app

# Bring in the LICENSE first so it lives at /app/LICENSE — mcp-analysis/
# pyproject.toml references it as `../LICENSE` relative to /app/mcp-analysis/.
COPY LICENSE ./LICENSE

# Then copy the patpy-analysis-mcp sub-project itself.
COPY mcp-analysis/ ./mcp-analysis/

RUN pip install --upgrade pip \
    && pip install ./mcp-analysis

USER patpy
RUN mkdir -p "${PATPY_MCP_CACHE}"
VOLUME ["/data/cache"]

# patpy-analysis-mcp speaks MCP over stdio by default.
ENTRYPOINT ["patpy-analysis-mcp"]
