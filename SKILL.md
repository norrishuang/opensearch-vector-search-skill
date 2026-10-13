---
name: opensearch-vector-search
version: 1.7.0
repository: https://github.com/norrishuang/opensearch-vector-search-skill
description: |
  Amazon OpenSearch vector search expert knowledge base. Comprehensive guidance on vector search configuration, cluster tuning, quantization, cost optimization, instance sizing, and pricing estimation.

  **Use this Skill when**:
  (1) User asks about OpenSearch vector search (k-NN) configuration, HNSW parameter tuning, disk mode
  (2) User needs vector search cluster sizing, capacity planning, instance recommendations
  (3) User asks about quantization techniques (Binary/Byte/FP16/Product Quantization)
  (4) User needs to estimate OpenSearch vector search costs or query pricing
  (5) User asks about OpenSearch indexing strategies, shard planning, query optimization
  (6) User mentions "vector database", "vector search", "k-NN", "knn_vector", "embedding search", "HNSW"
  (7) User mentions data scale (e.g. "100M vectors", "1 billion vectors") and needs cluster configuration advice
  (8) User asks about OpenSearch cluster JVM, memory, or thread pool configuration
  (9) Involves Amazon OpenSearch Service pricing, cost calculation, or instance comparison
  (10) User provides an OpenSearch cluster URL/credentials and wants vector configuration analysis or health check
  (11) For executing reproducible VectorDBBench performance tests, route to the bundled opensearch-vector-benchmark skill
requirements:
  env:
    - name: AWS_ACCESS_KEY_ID
      description: AWS credentials for pricing API (boto3). Only needed when running the pricing script.
      optional: true
    - name: AWS_SECRET_ACCESS_KEY
      description: AWS secret key. Only needed when running the pricing script.
      optional: true
  tools:
    - python3
    - boto3
    - opensearch-py
---

# OpenSearch Vector Search Expert

> **GitHub**: [norrishuang/opensearch-vector-search-skill](https://github.com/norrishuang/opensearch-vector-search-skill)
> — Issues, PRs, and new reference contributions are welcome!

## Safety Notes

- **Pricing script** (`scripts/get_opensearch_pricing.py`): Makes outbound HTTPS requests to the AWS Pricing API (`pricing.us-east-1.amazonaws.com`). Requires `boto3` and valid AWS credentials. The script is **read-only** (fetches public pricing data) and does not modify any AWS resources. Only run it when the user explicitly requests cost estimation.
- **Reference examples**: Code snippets in `references/` contain example API calls to `localhost:9200` (standard OpenSearch endpoint). These are **documentation examples only** — do NOT execute them automatically. Present them to the user as configuration references.
- **Cluster analyzer** (`scripts/analyze_cluster.py`): Connects to a user-provided OpenSearch cluster and performs **read-only** analysis. It NEVER creates, modifies, or deletes any indices or data. Only run it when the user explicitly provides cluster credentials (URL + username/password).
- **Vector benchmark skill** (`opensearch-vector-benchmark/SKILL.md`): VectorDBBench creates, loads, force-merges, and may drop benchmark indices. Use only with a dedicated benchmark target and explicit user confirmation.

## Knowledge Base Structure

Read the corresponding reference file based on the question type:

| Question Type | Reference File | Keywords |
|--------------|----------------|----------|
| Vector search, k-NN, HNSW, disk mode | `references/vector-search.md` | vector, knn, hnsw, warmup, disk mode, on_disk |
| 1-bit SQ, 32x on-disk tuning and cost | `references/quantization-1bit-32x.md` | 1-bit, scalar quantization, SQ, 32x, on_disk, oversample, cost |
| Other quantization techniques | `references/quantization-techniques.md` | quantization, binary, byte, fp16, product quantization |
| Guided capacity-planning intake | `references/capacity-planning-intake.md` | size cluster, estimate resources, not sure, options, questionnaire |
| Cost optimization, instance sizing, memory calc | `references/cost-optimization.md` | cost, pricing, instance, memory calculation, cluster sizing, budget |
| Cluster tuning, JVM, thread pools | `references/cluster-tuning.md` | JVM, heap, thread pool, node role, shard allocation |
| Performance benchmarks, dataset sizing | `references/performance-benchmarks.md` | benchmark, QPS, latency, recall, dataset size |
| Indexing strategies, mapping | `references/indexing-strategies.md` | index, mapping, shard, replica, lifecycle |
| Query optimization | `references/query-optimization.md` | query, filter, aggregation, cache, pagination |
| Optimized instances (OR1/OR2/OM2/OI2) | `references/optimized-instances.md` | optimized, OR1, OR2, OM2, OI2, S3 durability, indexing throughput |
| Live cluster analysis | `scripts/analyze_cluster.py` | analyze cluster, connect, diagnose, review config, health check |
| Execute a vector benchmark | `opensearch-vector-benchmark/SKILL.md` | VectorDBBench, benchmark, QPS, latency, recall, indexing throughput |

## Core Workflows

### 0. Guide Users Who Have Not Supplied Enough Context

Do not expect the user to know OpenSearch terminology or to compose a complete
capacity-planning prompt.

When the request is broad, such as "help me design vector search", "estimate a
vector database cluster", or "what information do you need?", first offer this
short task menu:

1. Cluster resource and cost estimate
2. Vector index and algorithm design
3. Quantization/compression selection
4. Existing cluster review
5. Performance benchmark planning

Ask the user to reply with a number or describe the desired outcome. If their
intent is already clear, skip the menu and continue directly.

For resource estimates, read
`references/capacity-planning-intake.md` and present its guided input form. Accept
option numbers, labels, natural-language answers, or pasted values. Do not require
the user to understand the difference between engine, ANN method, similarity
metric, mode, and quantization before continuing.

Interaction rules:

- Ask for missing inputs in one compact round instead of one question per turn.
- Mark only vector count and dimension as initially required. If either is unknown,
  help derive it from documents/items × vectors per item or from the embedding model.
- Offer recommended defaults and an "unsure—recommend for me" choice.
- Never silently choose a lossy compression level, zero replicas, or an availability
  target. State the assumption and show at least one alternative.
- If the user cannot provide QPS, latency, growth, or recall targets, produce a
  preliminary range with explicit assumptions and list which inputs most affect it.
- Confirm the normalized inputs before presenting the final sizing calculation.
- Do not repeat the full form when the user has already supplied most fields; ask only
  for the material gaps and preserve all prior answers.

### 1. Answering Vector Search Configuration Questions

1. Read `references/vector-search.md`
2. Recommend in-memory mode or disk mode based on user scenario (latency requirements, data scale, QPS)
3. Provide specific mapping JSON configuration
4. Use FAISS as the general engine starting point. Select the similarity metric
   from the embedding model's requirements; do not default to cosine when that is
   unknown. Treat all choices as candidates until the user confirms them.

### 2. Capacity Planning & Instance Sizing (Most Common Scenario)

After collecting and confirming inputs with
`references/capacity-planning-intake.md`:

1. Read `references/cost-optimization.md` for memory calculation formulas and examples
2. Calculate vector KNN memory using the standard HNSW memory formula:
   ```
   Unquantized (float32):
     Memory = 1.1 × (4 × d + 8 × m) × num_vectors × (replicas + 1) bytes
   
   Quantized (FAISS engine, compressed vectors in memory):
     FP16 (2x):    Memory = 1.1 × (2 × d + 8 × m) × num_vectors × (replicas + 1)
     Byte (4x):    Memory = 1.1 × (1 × d + 8 × m) × num_vectors × (replicas + 1)
     Binary 4-bit: Memory = 1.1 × (d/2 + 8 × m) × num_vectors × (replicas + 1)
     Binary 2-bit: Memory = 1.1 × (d/4 + 8 × m) × num_vectors × (replicas + 1)
     Scalar 1-bit (32x): Memory = 1.1 × (d/8 + 8 × m) × num_vectors × (replicas + 1)
   
   Where: d=vector dimensions, m=HNSW connections (default 16), num_vectors=total vector count
   ```
3. Calculate primary disk footprint and the shard/vCPU floor:
   ```
   Primary vector disk GiB =
     vector_count × dimension × bytes_per_dimension
     ÷ disk_compression_ratio ÷ 1024^3

   Primary index GiB =
     (primary_vector_disk_GiB + primary_non_vector_GiB)
     × storage_overhead_factor

   Primary shards = ceil(primary_index_GiB / target_primary_shard_GiB)
   Active shards = primary_shards × (replicas + 1)
   Required vCPU = ceil(active_shards / active_shards_per_vCPU)
   ```
   Use a user-selected target primary shard size in the 25-50 GiB range;
   default to 50 GiB. Default to one active shard per vCPU.
4. Apply OpenSearch node memory allocation rules:
   ```
   JVM Heap = min(node_memory × 50%, 32GB)
   Remaining memory = node_memory - JVM Heap
   KNN available memory = remaining × 75%  (with knn.memory.circuit_breaker.limit=70%, ~35% of node memory)
   ```
5. Select three different candidate instance types and calculate independent
   node-count floors for each:
   ```
   Nodes by memory = ceil(total KNN memory / KNN memory available per node)
   Nodes by CPU = ceil(required vCPU / instance vCPU)
   Nodes by storage = ceil(total provisioned storage / EBS GiB per node)
   Final data nodes = max(memory floor, CPU floor, storage floor, HA floor)
   ```
   Do not select an instance from memory alone. Report which constraint wins.
6. Keep workload, compression, shard, replica, and availability inputs identical
   across the three candidates so the instance comparison is fair.
7. Prefer `scripts/estimate_vector_resources.py` for deterministic calculations.
8. Run the pricing script for current prices when cost is requested. Include only
   candidates that satisfy all resource floors, then sort the three valid options
   by estimated monthly total cost from highest to lowest.

### 3. Cost Estimation (with Real-Time Pricing)

When user needs cost estimation:

1. Complete capacity planning above
2. Run pricing script for real-time prices:
   ```bash
   python3 scripts/get_opensearch_pricing.py --region <region> --instance-type <type>
   ```
3. Calculate monthly cost:
   ```
   Instance cost = unit_price × final_data_node_count
   EBS cost = total provisioned EBS GiB × unit storage price + IOPS/throughput
   Total cost = Instance cost + EBS cost
   ```
   Replica copies are already included in active shards, KNN memory, storage, and
   final node count. Never multiply instance cost by `(replicas + 1)` again.
4. Present exactly three valid instance-type options when enough current pricing
   and instance specification data is available:
   - Option 1: highest estimated monthly cost
   - Option 2: middle estimated monthly cost
   - Option 3: lowest estimated monthly cost
5. Recommend one option separately; do not assume the cheapest is best. Explain
   the performance, node-count, operational, and growth-headroom tradeoff.
   If QPS/latency/recall evidence is missing, state that the recommendation is
   provisional and identify which option should be benchmarked first.
6. If current pricing is unavailable, show three resource-valid candidates but
   label their cost order unverified. Do not invent prices or claim high-to-low order.

For 1-bit or 32x on-disk questions, read
`references/quantization-1bit-32x.md` before estimating capacity or cost. Treat
its 100M benchmark as a versioned reference point, not a portable guarantee.
Refresh current instance and EBS prices before quoting a present-day total.

### 4. Live Cluster Analysis (When User Provides Cluster Credentials)

When the user provides an OpenSearch cluster URL and credentials, use the cluster analyzer to
connect and review their vector search configuration. This is **read-only** — never modify the cluster.

**Prerequisites**: User must explicitly provide:
- Cluster URL (e.g., `https://my-cluster.us-east-1.es.amazonaws.com`)
- Username and password (basic auth), OR `--no-auth` for clusters without authentication

**Workflow**:

1. **Ask for credentials** if not provided: URL, username, password
2. **Run cluster overview** to get health, nodes, and k-NN index list:
   ```bash
   python3 scripts/analyze_cluster.py --url <url> -u <user> -p <pass> --action cluster-overview -f pretty
   ```
3. **Analyze specific index** if user specifies one, or pick the most important k-NN index:
   ```bash
   python3 scripts/analyze_cluster.py --url <url> -u <user> -p <pass> --action index-detail --index <index_name> -f pretty
   ```
4. **Analyze shard distribution** for the target index:
   ```bash
   python3 scripts/analyze_cluster.py --url <url> -u <user> -p <pass> --action shard-analysis --index <index_name> -f pretty
   ```
5. **Run all analyses at once** (for a comprehensive report):
   ```bash
   python3 scripts/analyze_cluster.py --url <url> -u <user> -p <pass> --action all --index <index_name> -f pretty
   ```
6. **Interpret the JSON output** and present findings to the user:
   - Cluster health status and node resource utilization
   - Vector field configurations (engine, dimensions, HNSW params, quantization)
   - Memory estimates vs actual cluster capacity
   - Auto-generated recommendations (from the script)
7. **Provide actionable advice** based on findings:
   - Suggest better engine/quantization if needed (provide example mapping JSON)
   - Suggest instance resizing if memory is over/under-provisioned
   - Suggest shard rebalancing if distribution is uneven
   - **NEVER execute write operations** — only provide example configurations for the user to apply

**Cluster Analyzer Script Reference**:
```
Usage:
  python3 scripts/analyze_cluster.py --url <url> -u <user> -p <pass> [options]

Actions:
  --action cluster-overview   Cluster health, nodes, k-NN stats, and all k-NN index summary (default)
  --action index-detail       Deep dive into a specific index's vector config + memory estimates
  --action shard-analysis     Shard distribution and sizing for a specific index
  --action all                Run all analyses

Options:
  --index <name>     Target a specific index (required for index-detail and shard-analysis)
  --no-auth          Connect without authentication
  --verify-ssl       Verify SSL certificates (default: skip)
  --format pretty    Human-readable JSON output

Output: JSON with these top-level keys:
  - cluster_overview: health, version, nodes (memory/CPU/JVM), knn_stats
  - knn_indices: list of all k-NN enabled indices with vector field summaries
  - index_detail/index_details: vector field configs, memory estimates, search stats
  - shard_analysis/shard_analyses: shard distribution across nodes
  - recommendations: auto-generated optimization suggestions with severity levels
```

**Safety constraints for live cluster analysis**:
- The script is strictly **read-only** (uses only GET/CAT APIs)
- **NEVER** create, update, or delete indices on the user's cluster
- **NEVER** change cluster settings or mappings
- Only provide example JSON configurations for the user to review and apply themselves
- If the user asks to apply changes, provide the exact API calls/JSON but let the user execute them

### Pricing Script Usage

```bash
# Query all instance prices for a region
python3 scripts/get_opensearch_pricing.py --region us-east-1

# Query specific instance type (no .search suffix needed)
python3 scripts/get_opensearch_pricing.py --region us-east-1 --instance-type r7g.xlarge

# JSON format output (for calculations)
python3 scripts/get_opensearch_pricing.py --region us-east-1 --instance-type r7g.xlarge --format json
```

Output fields: instance_type, vcpu, memory_gib, price_per_hour_usd, price_per_month_usd, network

## Recommended Defaults

Use these as visible starting candidates when the user has not made a choice.
Confirm them or compare alternatives before a final recommendation:

- **Engine candidate**: FAISS for most ANN workloads
- **Similarity**: Match the embedding model; use cosine only when the model or
  vector normalization supports it
- **Instance family** (Gen 7+ only, never recommend older generations):
  - **Vector search (k-NN)**: r7g/r8g/r8gd (memory-optimized, lowest search latency; r8g Graviton4 ~30% faster than r7g)
  - **Indexing-heavy + vector**: OR2 (optimized, S3 durability, good memory-to-price ratio)
  - **Indexing-heavy (no vector)**: OM2 (highest indexing throughput, 15% faster than OR1)
  - **Large dataset with NVMe**: OI2 (storage-optimized, no EBS needed)
  - Do NOT recommend: r6g, r5, m5, c5, i3, or any older instance families
- **HNSW parameters**: ef_construction=512, m=16
- **Quantization candidates**: Compare FP32/FP16 for quality-first, Byte (4x) for
  balanced cost, and 1-bit SQ (32x) for aggressive cost optimization on
  OpenSearch 3.6+, preferably 3.7+. Do not silently select a lossy option.
- **Disk mode candidate**: Consider for memory-constrained, latency-tolerant
  workloads after checking QPS, tail latency, recall, storage performance, and
  OpenSearch version. Vector count alone is not a selection threshold.

### Instance Selection Decision Tree

```
Is this primarily a vector search (k-NN) workload?
├─ YES → r7g/r8g/r8gd (best search latency, standard EBS; prefer r8g for Graviton4)
│        └─ Need S3 durability? → OR2 (accept 10s refresh interval tradeoff)
├─ Mixed (logs + vectors) → OR2 for log nodes, r7g/r8g for vector nodes
└─ NO (logs/observability/analytics)
   ├─ Write-heavy → OM2 (highest ingest throughput)
   ├─ Balanced → OR2 (good all-around with S3 durability)
   └─ Need NVMe IOPS → OI2
```

## Response Template

Organize cost/sizing answers in this structure:

1. **Normalized inputs and assumptions**: Vector count, dimensions, growth horizon,
   algorithm/mode, compression, QPS, latency, recall, replicas, region
2. **Storage and shard calculation**: Vector disk + non-vector disk → primary
   index size → primary shards → active shards
3. **Resource constraints**: Nodes required by KNN memory, shard/vCPU, storage,
   and availability; identify the winning constraint
4. **Three instance options, cost high to low**: For each option show instance
   type × final node count, per-node vCPU/RAM, winning constraint, and EBS per node
5. **Cost estimation**: For each option show instance cost + EBS cost = monthly
   total; identify whether prices are current or unverified
6. **Alternatives and sensitivity**: Compare at least a quality-first and cost-first
   option when the user did not explicitly select compression/mode
7. **Next validation step**: Identify assumptions that require a benchmark or live
   measurement before production
