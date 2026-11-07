//! High-Performance Interval Overlap & Concurrency Graph Engine.
use rayon::prelude::*;

/// Compute all overlapping index pairs (i, j) where i < j and intervals overlap.
pub fn find_overlapping_intervals(starts: &[f64], ends: &[f64]) -> Vec<(usize, usize)> {
    let n = starts.len();
    if n < 2 || ends.len() != n {
        return Vec::new();
    }

    // Parallel pairwise overlap check
    (0..n)
        .into_par_iter()
        .flat_map(|i| {
            let s_i = starts[i];
            let e_i = ends[i];
            let mut local_pairs = Vec::new();
            for j in (i + 1)..n {
                let s_j = starts[j];
                let e_j = ends[j];
                // Overlap condition: start_i <= end_j && start_j <= end_i
                if s_i <= e_j && s_j <= e_i {
                    local_pairs.push((i, j));
                }
            }
            local_pairs
        })
        .collect()
}

/// Compute peak concurrency (maximum number of simultaneously active requests) via sweep-line.
pub fn compute_peak_concurrency(starts: &[f64], ends: &[f64]) -> usize {
    let n = starts.len();
    if n == 0 || ends.len() != n {
        return 0;
    }

    // Events: (timestamp, type: +1 for start, -1 for end)
    let mut events = Vec::with_capacity(2 * n);
    for i in 0..n {
        events.push((starts[i], 1i32));
        events.push((ends[i], -1i32));
    }

    // Sort events by timestamp; on tie, end (-1) precedes start (+1)
    events.sort_by(|a, b| {
        a.0.partial_cmp(&b.0)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| a.1.cmp(&b.1))
    });

    let mut current = 0;
    let mut peak = 0;

    for (_, event_type) in events {
        current += event_type;
        if current > peak {
            peak = current;
        }
    }

    peak.max(0) as usize
}

/// Compute concurrency density: (overlapping pairs) / (total pairs)
pub fn compute_concurrency_density(starts: &[f64], ends: &[f64]) -> f64 {
    let n = starts.len();
    if n < 2 {
        return 0.0;
    }
    let total_pairs = (n * (n - 1)) / 2;
    let overlapping_pairs = find_overlapping_intervals(starts, ends).len();
    overlapping_pairs as f64 / total_pairs as f64
}

