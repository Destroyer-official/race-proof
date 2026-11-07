//! MinHash + Banded LSH Clustering Kernel for High-Throughput Response Diffing.
use std::collections::HashMap;
use rayon::prelude::*;
use crate::differ::fnv1a_64;

const NUM_HASHES: usize = 128;
const NUM_BANDS: usize = 32;
const ROWS_PER_BAND: usize = 4; // 32 * 4 = 128
const PRIME: u64 = 4_294_967_311; // 2^32 - 5

/// Precomputed hash parameters for universal hashing: (a * x + b) % PRIME
struct HashParams {
    a: Vec<u64>,
    b: Vec<u64>,
}

impl HashParams {
    fn new(n: usize) -> Self {
        let mut a = Vec::with_capacity(n);
        let mut b = Vec::with_capacity(n);
        let mut seed: u64 = 133742;
        for _ in 0..n {
            seed = seed.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
            let a_val = (seed % (PRIME - 1)) + 1;
            seed = seed.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
            let b_val = seed % PRIME;
            a.push(a_val);
            b.push(b_val);
        }
        Self { a, b }
    }
}

/// Tokenize input into 4-character shingles.
fn extract_shingle_hashes(text: &str) -> Vec<u64> {
    if text.is_empty() {
        return vec![0];
    }
    let chars: Vec<char> = text.chars().collect();
    if chars.len() < 4 {
        let h = fnv1a_64(text.as_bytes());
        return vec![h];
    }
    let mut shingles = Vec::with_capacity(chars.len() - 3);
    for window in chars.windows(4) {
        let s: String = window.iter().collect();
        let h = fnv1a_64(s.as_bytes());
        shingles.push(h);
    }
    shingles
}

/// Compute 128-dim MinHash signature for a text.
fn compute_minhash_signature(shingle_hashes: &[u64], params: &HashParams) -> Vec<u32> {
    let mut sig = vec![u32::MAX; NUM_HASHES];
    for &sh in shingle_hashes {
        let x = (sh % PRIME) as u64;
        for i in 0..NUM_HASHES {
            let h = ((params.a[i].wrapping_mul(x).wrapping_add(params.b[i])) % PRIME) as u32;
            if h < sig[i] {
                sig[i] = h;
            }
        }
    }
    sig
}

/// Disjoint-Set Union (Union-Find) for cluster assignment.
struct Dsu {
    parent: Vec<usize>,
}

impl Dsu {
    fn new(n: usize) -> Self {
        Self {
            parent: (0..n).collect(),
        }
    }

    fn find(&mut self, i: usize) -> usize {
        if self.parent[i] == i {
            i
        } else {
            let p = self.parent[i];
            self.parent[i] = self.find(p);
            self.parent[i]
        }
    }

    fn union(&mut self, i: usize, j: usize) {
        let root_i = self.find(i);
        let root_j = self.find(j);
        if root_i != root_j {
            self.parent[root_i] = root_j;
        }
    }
}

/// Cluster a collection of response body strings using parallel MinHash + Banded LSH.
/// Returns cluster labels for each item (0, 1, 2, ...).
pub fn cluster_responses_lsh(bodies: &[String]) -> Vec<usize> {
    let n = bodies.len();
    if n == 0 {
        return Vec::new();
    }
    if n == 1 {
        return vec![0];
    }

    let params = HashParams::new(NUM_HASHES);

    // 1. Parallel signature generation
    let signatures: Vec<Vec<u32>> = bodies
        .par_iter()
        .map(|body| {
            let shingles = extract_shingle_hashes(body);
            compute_minhash_signature(&shingles, &params)
        })
        .collect();

    // 2. Banded LSH bucketing
    let mut dsu = Dsu::new(n);

    for band in 0..NUM_BANDS {
        let mut bucket_map: HashMap<u64, Vec<usize>> = HashMap::new();
        let start_row = band * ROWS_PER_BAND;

        for (item_idx, sig) in signatures.iter().enumerate() {
            let mut h: u64 = 17;
            for r in 0..ROWS_PER_BAND {
                h = h.wrapping_mul(31).wrapping_add(sig[start_row + r] as u64);
            }
            bucket_map.entry(h).or_default().push(item_idx);
        }

        for items in bucket_map.values() {
            if items.len() > 1 {
                let first = items[0];
                for &other in &items[1..] {
                    dsu.union(first, other);
                }
            }
        }
    }

    // 3. Normalize cluster IDs to 0..C
    let mut root_to_cluster: HashMap<usize, usize> = HashMap::new();
    let mut clusters = Vec::with_capacity(n);
    let mut next_cluster = 0;

    for i in 0..n {
        let root = dsu.find(i);
        let c_id = *root_to_cluster.entry(root).or_insert_with(|| {
            let id = next_cluster;
            next_cluster += 1;
            id
        });
        clusters.push(c_id);
    }

    clusters
}
