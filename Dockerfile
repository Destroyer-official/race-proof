# Stage 1: Build native Rust core
FROM rust:1.80-slim-bullseye AS rust-builder
WORKDIR /build

RUN apt-get update && apt-get install -y python3 python3-pip python3-dev pkg-config && rm -rf /var/lib/apt/lists/*
RUN pip3 install --no-cache-dir maturin

COPY crates/ /build/crates/
RUN maturin build --release -m crates/race_proof_core/Cargo.toml --out /build/wheels

# Stage 2: Final runtime
FROM python:3.11-slim-bullseye
LABEL maintainer="RaceProof Engineering <security@race-proof.io>"
LABEL description="Definitive 2027+ Verification Standard for Web API Race Conditions"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt pyproject.toml README.md /app/
COPY --from=rust-builder /build/wheels/*.whl /app/wheels/

RUN pip install --no-cache-dir /app/wheels/*.whl && \
    pip install --no-cache-dir -r requirements.txt && \
    rm -rf /app/wheels

COPY race_proof/ /app/race_proof/
COPY race_proof_bench/ /app/race_proof_bench/
COPY examples/ /app/examples/

RUN pip install --no-cache-dir -e .

RUN useradd -m -u 10001 appuser && chown -R appuser:appuser /app
USER appuser

ENTRYPOINT ["race-proof"]
CMD ["--help"]

