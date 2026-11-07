//! race_proof_core — High-Performance Native Rust Kernels for RaceProof.
use pyo3::prelude::*;

mod differ;
mod intervals;
mod minhash;

#[pyfunction]
fn rust_core_version() -> &'static str {
    "0.2.0"
}

/// Cluster response bodies using parallel MinHash + Banded LSH ($B=32, R=4$).
#[pyfunction]
fn minhash_lsh_cluster(bodies: Vec<String>) -> Vec<usize> {
    minhash::cluster_responses_lsh(&bodies)
}

/// Compute 64-bit SimHash of text.
#[pyfunction]
fn fast_simhash(text: &str) -> u64 {
    differ::compute_simhash(text)
}

/// Compute Hamming distance between two 64-bit fingerprints.
#[pyfunction]
fn fast_hamming_distance(h1: u64, h2: u64) -> u32 {
    differ::hamming_distance(h1, h2)
}

/// Fast token Jaccard similarity between two strings.
#[pyfunction]
fn fast_token_similarity(a: &str, b: &str) -> f64 {
    differ::token_similarity(a, b)
}

/// Fast differential comparison returning (similarity_ratio, diff_summary).
#[pyfunction]
fn fast_differential(a: &str, b: &str) -> (f64, String) {
    differ::fast_differential(a, b)
}

/// Compute all overlapping interval index pairs (i, j).
#[pyfunction]
fn find_overlapping_intervals(starts: Vec<f64>, ends: Vec<f64>) -> Vec<(usize, usize)> {
    intervals::find_overlapping_intervals(&starts, &ends)
}

/// Compute peak simultaneous request concurrency via sweep-line.
#[pyfunction]
fn compute_peak_concurrency(starts: Vec<f64>, ends: Vec<f64>) -> usize {
    intervals::compute_peak_concurrency(&starts, &ends)
}

/// Compute concurrency density (overlapping pairs / total pairs).
#[pyfunction]
fn compute_concurrency_density(starts: Vec<f64>, ends: Vec<f64>) -> f64 {
    intervals::compute_concurrency_density(&starts, &ends)
}

#[pymodule]
fn race_proof_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(rust_core_version, m)?)?;
    m.add_function(wrap_pyfunction!(minhash_lsh_cluster, m)?)?;
    m.add_function(wrap_pyfunction!(fast_simhash, m)?)?;
    m.add_function(wrap_pyfunction!(fast_hamming_distance, m)?)?;
    m.add_function(wrap_pyfunction!(fast_token_similarity, m)?)?;
    m.add_function(wrap_pyfunction!(fast_differential, m)?)?;
    m.add_function(wrap_pyfunction!(find_overlapping_intervals, m)?)?;
    m.add_function(wrap_pyfunction!(compute_peak_concurrency, m)?)?;
    m.add_function(wrap_pyfunction!(compute_concurrency_density, m)?)?;
    Ok(())
}
