# RaceProof — Automation Makefile

PYTHON ?= python
PIP ?= pip
MATURIN ?= maturin
PYTEST ?= pytest

.PHONY: all help install build test bench tui lint docs release clean

all: build test

help:
	@echo "RaceProof Automation Targets:"
	@echo "  make install  - Install Python dependencies and editable package"
	@echo "  make build    - Compile native Rust core (race_proof_core via maturin)"
	@echo "  make test     - Run full test suite with pytest"
	@echo "  make bench    - Run ground-truth benchmark suite and emit scorecard"
	@echo "  make lint     - Run static analysis, ruff check, and type checks"
	@echo "  make docs     - Build and preview markdown documentation"
	@echo "  make release  - Build wheels, generate SBOM, and prepare release bundle"
	@echo "  make tui      - Launch interactive Terminal User Interface"
	@echo "  make clean    - Remove build artifacts, pycache, and temporary findings"

install:
	$(PIP) install -r requirements.txt
	$(PIP) install -e .

build:
	$(MATURIN) develop -m crates/race_proof_core/Cargo.toml

test:
	$(PYTEST) -v --cov=race_proof --cov=race_oracle --cov-report=term-missing

bench:
	$(PYTHON) -m race_proof.cli bench -v

lint:
	$(PYTHON) -m ruff check . || true
	$(PYTHON) -m mypy race_proof race_oracle || true

docs:
	@echo "Documentation located in docs/ directory. Previewing architecture..."
	@head -n 20 docs/architecture.md

release: build
	$(MATURIN) build --release -m crates/race_proof_core/Cargo.toml --out dist/
	$(PYTHON) -m pip install cyclonedx-bom || true
	cyclonedx-py environment -o sbom.json || true
	@echo "Release assets generated in dist/ and sbom.json"

tui:
	$(PYTHON) -m race_proof.cli tui


clean:
	rm -rf build/ dist/ *.egg-info .pytest_cache/ .hypothesis/ __pycache__
	rm -rf crates/race_proof_core/target/
	rm -rf race_proof_findings/ *.sarif WebApiRaceModel.*

