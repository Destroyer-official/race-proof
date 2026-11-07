# RaceProof — Automation Makefile

PYTHON ?= python
PIP ?= pip
MATURIN ?= maturin
PYTEST ?= pytest

.PHONY: all help install build test bench tui lint clean

all: build test

help:
	@echo "RaceProof 2027+ Build Targets:"
	@echo "  make install  - Install Python dependencies and editable package"
	@echo "  make build    - Compile native Rust core (race_proof_core via maturin)"
	@echo "  make test     - Run full test suite with pytest"
	@echo "  make bench    - Run ground-truth benchmark suite and emit scorecard"
	@echo "  make tui      - Launch interactive Terminal User Interface"
	@echo "  make clean    - Remove build artifacts, pycache, and temporary findings"

install:
	$(PIP) install -r requirements.txt
	$(PIP) install -e .

build:
	$(MATURIN) develop -m crates/race_proof_core/Cargo.toml

test:
	$(PYTEST) -v

bench:
	$(PYTHON) -m race_proof.cli bench -v

tui:
	$(PYTHON) -m race_proof.cli tui

clean:
	rm -rf build/ dist/ *.egg-info .pytest_cache/ .hypothesis/ __pycache__
	rm -rf crates/race_proof_core/target/
	rm -rf race_proof_findings/ *.sarif WebApiRaceModel.*

