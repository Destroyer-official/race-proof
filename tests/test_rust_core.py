"""Tests for Native Rust Core (race_proof_core via PyO3)."""
from __future__ import annotations

import pytest
import race_proof_core


def test_rust_core_version():
    ver = race_proof_core.rust_core_version()
    assert ver == "0.2.0"


def test_rust_simhash_and_hamming():
    # Identical texts must have hamming distance 0
    h1 = race_proof_core.fast_simhash("Transfer 100 USD to user 42")
    h2 = race_proof_core.fast_simhash("Transfer 100 USD to user 42")
    assert race_proof_core.fast_hamming_distance(h1, h2) == 0

    # Slight variation should have small distance
    h3 = race_proof_core.fast_simhash("Transfer 100 USD to user 43")
    dist = race_proof_core.fast_hamming_distance(h1, h3)
    assert 0 < dist < 20

    # Totally different text should have large distance
    h4 = race_proof_core.fast_simhash("completely unrelated image payload binary buffer")
    dist_unrelated = race_proof_core.fast_hamming_distance(h1, h4)
    assert dist_unrelated > 15


def test_rust_minhash_lsh_clustering():
    # Group A
    group_a = ["status: ok, balance: 100", "status: ok, balance: 100", "status: ok, balance: 100"]
    # Group B
    group_b = ["fatal database error 500", "fatal database error 500"]

    all_bodies = group_a + group_b
    clusters = race_proof_core.minhash_lsh_cluster(all_bodies)

    assert len(clusters) == 5
    # All of group A should share the same cluster
    assert clusters[0] == clusters[1] == clusters[2]
    # All of group B should share the same cluster
    assert clusters[3] == clusters[4]
    # Group A and Group B should be distinct clusters
    assert clusters[0] != clusters[3]


def test_rust_intervals_and_concurrency():
    # 3 intervals:
    # 0: [10.0, 25.0]
    # 1: [20.0, 35.0]  (overlaps with 0 from 20 to 25, overlaps with 2 from 30 to 35)
    # 2: [30.0, 40.0]  (overlaps with 1)
    starts = [10.0, 20.0, 30.0]
    ends = [25.0, 35.0, 40.0]

    overlaps = race_proof_core.find_overlapping_intervals(starts, ends)
    assert (0, 1) in overlaps
    assert (1, 2) in overlaps
    assert (0, 2) not in overlaps

    peak = race_proof_core.compute_peak_concurrency(starts, ends)
    assert peak == 2

    density = race_proof_core.compute_concurrency_density(starts, ends)
    # Total pairs: 3. Overlapping pairs: 2. Density: 2/3 = 0.666...
    assert 0.66 < density < 0.67


def test_rust_fast_differential():
    a = "line 1\nline 2\nline 3"
    b = "line 1\nline modified\nline 3"

    sim, diff = race_proof_core.fast_differential(a, b)
    assert 0.5 < sim < 1.0
    assert "+ line modified" in diff
    assert "- line 2" in diff

