"""End-to-End Production Verification Suite for RaceProof 2027+.

Exhaustively verifies every ingestion format, analysis engine, formal bridge,
cryptographic attestation, SARIF 2.1.0 export, and benchmark execution.
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from race_proof.ingestion import auto_detect
from race_proof.verdict import VerdictEngine
from race_proof.evidence.packager import EvidencePackager
from race_proof.evidence.sarif import SarifExporter
from race_proof.evidence.attestation import AttestationSigner
from race_proof.formal import FormalVerifier, TlaSpecificationGenerator
from race_proof.agent.synthesizer import ToolSynthesizer
from race_proof.bench.runner import BenchmarkRunner


def test_e2e_all_supported_ingestors(tmp_path):
    """Verify end-to-end ingestion and analysis across all sample input formats."""
    sample_dir = Path("examples/sample_input")
    assert sample_dir.exists(), "Sample input directory must exist"

    sample_files = [
        sample_dir / "turbo_intruder_confirmed.json",
        sample_dir / "quickdraw_h3_confirmed.jsonl",
        sample_dir / "nuclei_race_confirmed.jsonl",
        sample_dir / "har_race_confirmed.har",
        sample_dir / "burp_xml_confirmed.xml",
        sample_dir / "postman_race_confirmed.json",
        sample_dir / "mitmproxy_race_confirmed.json",
        sample_dir / "k6_race_confirmed.json",
    ]

    engine = VerdictEngine(agent=None, verbose=False)
    packager = EvidencePackager(output_dir=tmp_path / "bundles")

    for file_p in sample_files:
        assert file_p.exists(), f"Sample file missing: {file_p}"
        adapter = auto_detect(str(file_p))
        assert adapter is not None, f"Failed to detect adapter for {file_p}"

        sessions = adapter.parse(file_p)
        assert len(sessions) >= 1, f"No sessions parsed from {file_p}"

        for session in sessions:
            verdict = engine.analyse(session)
            assert verdict is not None
            assert verdict.verdict is not None
            assert 0.0 <= verdict.confidence <= 1.0

            # Package evidence bundle
            bundle_dir = packager.package(session, verdict)
            assert bundle_dir.exists()

            # Verify bundle artifacts
            assert (bundle_dir / "verdict.json").exists()
            assert (bundle_dir / "diff.html").exists()
            assert (bundle_dir / "report.md").exists()
            assert (bundle_dir / "sarif.json").exists()
            assert (bundle_dir / "attestation.sigstore.json").exists()
            assert (bundle_dir / "reproduce_race.py").exists()


def test_e2e_sarif_compliance(tmp_path):
    """Verify that SARIF output conforms to OASIS SARIF 2.1.0 specification structure."""
    sample_file = Path("examples/sample_input/turbo_intruder_confirmed.json")
    adapter = auto_detect(str(sample_file))
    session = adapter.parse(sample_file)[0]

    engine = VerdictEngine(agent=None, verbose=False)
    verdict = engine.analyse(session)

    sarif_data = SarifExporter.to_sarif_dict(session, verdict)

    assert sarif_data["version"] == "2.1.0"
    assert "$schema" in sarif_data
    assert len(sarif_data["runs"]) == 1

    run = sarif_data["runs"][0]
    assert run["tool"]["driver"]["name"] == "RaceProof"
    assert len(run["results"]) == 1

    result = run["results"][0]
    assert result["ruleId"].startswith("CONC")
    assert len(result["codeFlows"]) >= 1
    thread_flows = result["codeFlows"][0]["threadFlows"]
    assert len(thread_flows) == len(session.race_responses)


def test_e2e_signed_attestation(tmp_path):
    """Verify cryptographic in-toto DSSE attestation generation and verification."""
    sample_file = Path("examples/sample_input/turbo_intruder_confirmed.json")
    adapter = auto_detect(str(sample_file))
    session = adapter.parse(sample_file)[0]

    engine = VerdictEngine(agent=None, verbose=False)
    verdict = engine.analyse(session)

    bundle_dir = tmp_path / "test_bundle"
    bundle_dir.mkdir(parents=True)

    # Create dummy artifact files
    (bundle_dir / "verdict.json").write_text('{"verdict": "CONFIRMED"}', encoding="utf-8")
    (bundle_dir / "diff.html").write_text('<html><body>Audit</body></html>', encoding="utf-8")

    signer = AttestationSigner()
    attestation_file = signer.write_attestation(bundle_dir, session, verdict)
    assert attestation_file.exists()

    # Verify signature and file hashes
    is_valid = signer.verify_attestation(attestation_file)
    assert is_valid is True

    # Tamper test: modifying an artifact must invalidate attestation
    (bundle_dir / "verdict.json").write_text('{"verdict": "TAMPERED"}', encoding="utf-8")
    assert signer.verify_attestation(attestation_file) is False


def test_e2e_formal_verification_workflow():
    """Verify automated TLA+ spec generation and BFS state-space exploration."""
    sample_file = Path("race_proof_bench/fintech/bench_fin_001.json")
    adapter = auto_detect(str(sample_file))
    session = adapter.parse(sample_file)[0]

    # Generate TLA+ spec
    spec = TlaSpecificationGenerator.generate_spec(session)
    assert "MODULE WebApiRaceModel" in spec.tla_source
    assert "NoOverdraft" in spec.invariants

    # Verify un-isolated execution identifies counterexample
    unisolated_res = FormalVerifier.explore_state_space(
        num_threads=spec.num_threads,
        initial_balance=100,
        cost_per_action=100,
        isolated=False,
    )
    assert unisolated_res.is_safe is False
    assert len(unisolated_res.counterexample_trace) > 0

    # Verify isolated execution proves safety
    isolated_res = FormalVerifier.explore_state_space(
        num_threads=spec.num_threads,
        initial_balance=100,
        cost_per_action=100,
        isolated=True,
    )
    assert isolated_res.is_safe is True
    assert isolated_res.violated_invariant is None


def test_e2e_hunt_poc_synthesis():
    """Verify autonomous reproduction PoC synthesis with syntax validity."""
    poc_script = ToolSynthesizer.synthesize_reproduction_poc(
        target_url="https://api.fintech.test/transfer",
        method="POST",
        headers={"Authorization": "Bearer tok_123"},
        body='{"amount": 100}',
        concurrency=25,
        protocol="h2",
    )

    assert "import asyncio" in poc_script
    assert "import httpx" in poc_script
    assert "asyncio.Barrier(CONCURRENCY)" in poc_script
    assert "https://api.fintech.test/transfer" in poc_script

    # Verify script compiles without syntax errors
    compiled = compile(poc_script, "<string>", "exec")
    assert compiled is not None


def test_e2e_benchmark_suite_execution():
    """Verify that the benchmark suite runs with 100% precision and recall."""
    runner = BenchmarkRunner(verbose=False)
    scenarios = runner.discover_scenarios()
    assert len(scenarios) >= 25

    card = runner.run_all()
    summary = card.compute_summary()

    assert summary["total_scenarios"] >= 25
    assert summary["precision"] == 1.0
    assert summary["recall"] == 1.0
    assert summary["f1_score"] == 1.0
    assert summary["mcc"] == 1.0
    assert summary["false_positives"] == 0
    assert summary["false_negatives"] == 0
