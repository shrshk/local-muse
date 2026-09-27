# Sandbox image: model-generated code runs here, with no network, no secrets, no host mounts.
# sandboxd applies every runtime constraint; this image only provides the toolchain.
#
# Preinstalled because the sandbox has no network (pip/npm install cannot work inside it):
#   Python 3.12: numpy, pandas, polars, matplotlib, requests (inert), beautifulsoup4, lxml,
#                pyarrow, openpyxl
#   CLI: jq, ripgrep, git, curl (inert), coreutils `timeout`, Node.js (Debian LTS)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLCONFIGDIR=/tmp/matplotlib \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends jq ripgrep git curl nodejs \
    && rm -rf /var/lib/apt/lists/*

RUN pip install \
    "numpy>=2.3,<3" \
    "pandas>=2.3,<3" \
    "polars>=1.30,<2" \
    "matplotlib>=3.10,<4" \
    "requests>=2.32,<3" \
    "beautifulsoup4>=4.13,<5" \
    "lxml>=6,<7" \
    "pyarrow>=21,<23" \
    "openpyxl>=3.1,<4"

# uid 10001 owns /workspace; Docker copies this ownership into a new, empty named volume.
RUN useradd --uid 10001 --user-group --home-dir /workspace --no-create-home sandbox \
    && mkdir -p /workspace \
    && chown sandbox:sandbox /workspace

USER sandbox
WORKDIR /workspace
CMD ["sleep", "infinity"]
