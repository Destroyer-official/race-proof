//! Fast Differential Analysis & SimHash Fingerprinting Kernels.
use std::collections::HashSet;

#[inline(always)]
pub fn fnv1a_64(bytes: &[u8]) -> u64 {
    let mut hash: u64 = 0xcbf29ce484222325;
    for &b in bytes {
        hash ^= b as u64;
        hash = hash.wrapping_mul(0x100000001b3);
    }
    hash
}

/// Compute 64-bit SimHash of arbitrary text.
pub fn compute_simhash(text: &str) -> u64 {
    if text.trim().is_empty() {
        return 0;
    }

    let mut v = [0i32; 64];

    // Tokenize on non-alphanumeric characters
    for token in text.split(|c: char| !c.is_alphanumeric() && c != '_' && c != '-') {
        if token.is_empty() {
            continue;
        }
        let h = fnv1a_64(token.as_bytes());
        for i in 0..64 {
            let bit = (h >> i) & 1;
            if bit == 1 {
                v[i] += 1;
            } else {
                v[i] -= 1;
            }
        }
    }

    let mut fingerprint: u64 = 0;
    for i in 0..64 {
        if v[i] > 0 {
            fingerprint |= 1 << i;
        }
    }

    fingerprint
}

/// Calculate Hamming distance between two 64-bit SimHash fingerprints.
#[inline(always)]
pub fn hamming_distance(h1: u64, h2: u64) -> u32 {
    (h1 ^ h2).count_ones()
}

/// Tokenize text into words/symbols for fast comparison.
fn tokenize(s: &str) -> Vec<&str> {
    s.split(|c: char| c.is_whitespace() || c == ',' || c == '{' || c == '}' || c == '[' || c == ']')
        .filter(|t| !t.is_empty())
        .collect()
}

/// Compute fast token-level Jaccard similarity between two response bodies.
pub fn token_similarity(a: &str, b: &str) -> f64 {
    if a == b {
        return 1.0;
    }
    if a.is_empty() || b.is_empty() {
        return 0.0;
    }

    let tokens_a: HashSet<&str> = tokenize(a).into_iter().collect();
    let tokens_b: HashSet<&str> = tokenize(b).into_iter().collect();

    let intersection_count = tokens_a.intersection(&tokens_b).count();
    let union_count = tokens_a.union(&tokens_b).count();

    if union_count == 0 {
        1.0
    } else {
        intersection_count as f64 / union_count as f64
    }
}

/// Fast line/token differential summary between baseline and race response.
pub fn fast_differential(a: &str, b: &str) -> (f64, String) {
    let sim = token_similarity(a, b);
    if sim >= 0.9999 {
        return (1.0, "Identical content".to_string());
    }

    let lines_a: Vec<&str> = a.lines().collect();
    let lines_b: Vec<&str> = b.lines().collect();

    let set_a: HashSet<&str> = lines_a.iter().copied().collect();
    let set_b: HashSet<&str> = lines_b.iter().copied().collect();

    let mut diff_lines = Vec::new();
    for line in &lines_b {
        if !set_a.contains(line) && !line.trim().is_empty() {
            diff_lines.push(format!("+ {}", line));
        }
    }
    for line in &lines_a {
        if !set_b.contains(line) && !line.trim().is_empty() {
            diff_lines.push(format!("- {}", line));
        }
    }

    let summary = if diff_lines.is_empty() {
        "Token-level variations detected within matching lines".to_string()
    } else {
        let max_lines = 20.min(diff_lines.len());
        diff_lines[..max_lines].join("\n")
    };

    (sim, summary)
}
