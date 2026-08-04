---
name: opensearch-vector-benchmark
description: Plan, run, and interpret reproducible OpenSearch vector performance benchmarks with zilliztech/VectorDBBench. Use for OpenSearch benchmark design, QPS/latency/recall testing, indexing throughput, workload matrices, in-memory or on-disk mode, fp32/fp16/binary quantization comparisons, oversample-factor tuning, managed OpenSearch domains, OpenSearch Serverless, the OpenSearch s3vector engine, benchmark client sizing, or VectorDBBench result diagnosis. Do not use for general vector index design without a benchmark objective.
---

# OpenSearch Vector Benchmark

Build a reproducible experiment before running VectorDBBench. Treat every run as a
write-heavy, potentially destructive workload and every result as valid only with its
deployment and test context.

Run commands from this skill directory so relative `scripts/` and `references/` paths resolve.

## Safety

- Use a dedicated benchmark cluster or collection. Never benchmark production.
- Obtain explicit confirmation before running a command that creates, loads, force-merges,
  or drops an index.
- Confirm the account, region, endpoint, and test window before any run.
- Keep credentials in environment variables or the AWS credential chain. Never put secrets
  in notes, generated artifacts, source control, or chat output.
- Estimate dataset download, cluster, EBS, Serverless OCU, S3, and network costs first.
- Generate and inspect a dry-run command before generating the executable run command.

## Workflow

### 1. Define the experiment

Collect these inputs:

- deployment: managed domain, OpenSearch Serverless, or OpenSearch `s3vector` engine
- OpenSearch version and endpoint region
- dataset case, dimensions, vector count, metric, and `k`
- client EC2 type, region/AZ, network path, and Python/VectorDBBench version
- data-node type/count, storage type/size/IOPS/throughput, shards, and replicas
- engine, HNSW parameters, quantization, mode, and oversampling
- load-only, query-only, or full workflow
- target recall, latency percentile, QPS, and indexing-time objective

If the user has not selected a dataset or matrix, read
[references/scenario-matrix.md](references/scenario-matrix.md).

### 2. Check capability and version drift

Require Python 3.11 or newer. Install the OpenSearch extra in an isolated environment:

```bash
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install 'vectordb-bench[opensearch]'
vectordbbench awsopensearch --help
```

Verify the installed CLI exposes every planned flag. Pin the resulting package version for
the experiment and record `python --version`, `pip freeze`, and the help output. VectorDBBench
changes independently of this skill; installed CLI help is authoritative.

For prerequisites, permissions, observability, and cluster checks, read
[references/runbook.md](references/runbook.md).

### 3. Select deployment semantics

Keep these modes distinct:

| Deployment | VectorDBBench form | Important behavior |
|---|---|---|
| Managed domain | `awsopensearch` with basic auth | Supports FAISS/Lucene tuning and the normal write defaults |
| OpenSearch Serverless | `awsopensearch --serverless` with SigV4 | Do not pass basic auth; service-managed settings are ignored; default to one indexing client |
| OpenSearch `s3vector` engine | `awsopensearch --engine s3vector` | HNSW and quantization flags do not describe this engine and must not be compared as if they do |

Amazon S3 Vectors is also a separate VectorDBBench backend. Do not substitute its `s3vectors`
command for the OpenSearch `s3vector` engine.

### 4. Generate a command

Use the generator instead of hand-assembling a long command:

```bash
python3 scripts/generate_benchmark_plan.py \
  --deployment managed \
  --host search-example.us-east-1.es.amazonaws.com \
  --case-type Performance768D1M \
  --db-label r7g-4xl-fp32 \
  --shards 4 \
  --workflow full
```

Defaults for a managed domain are `NUM_PER_BATCH=20000`, 40 indexing clients, cosine,
FAISS, `m=16`, `ef_construction=200`, `ef_search=100`, no replicas, one segment, and a
4xlarge-class benchmark client. These are starting points, not universal best settings.

The generator emits a dry-run command by default. After inspecting it, regenerate with
`--phase run`. Use `--format json` when another agent or automation will consume the plan.

For on-disk mode, always set `--oversample-factor` explicitly. Start with 20 for a
recall-oriented baseline, then sweep lower values such as 1, 2, 5, and 10 to measure the
recall/QPS/IOPS tradeoff:

```bash
python3 scripts/generate_benchmark_plan.py \
  --deployment managed \
  --host search-example.us-east-1.es.amazonaws.com \
  --case-type Performance768D10M \
  --db-label ondisk-32x-os20 \
  --on-disk \
  --oversample-factor 20
```

### 5. Execute in controlled phases

1. Capture the run manifest and idle cluster metrics.
2. Run load-only when comparing ingestion settings.
3. Wait for indexing and merge activity to settle.
4. Warm up consistently, or label the test explicitly as cold.
5. Run serial search for recall and latency.
6. Run the same ordered concurrency sweep for every candidate.
7. Capture client utilization, cluster metrics, storage metrics, and result JSON.
8. Repeat each candidate at least three times and report median plus variation.

For query-only runs, require `--skip-drop-old`, `--skip-load`, and force merge disabled; otherwise
an existing benchmark index can be destroyed, replaced, or modified. The generator applies all
three safeguards.

### 6. Interpret and report

Read [references/result-analysis.md](references/result-analysis.md). Do not rank configurations
by peak QPS alone. Gate on recall, compare latency distributions, verify the client is not the
bottleneck, and reject comparisons that changed dataset, network, shard topology, warmup,
payload, or concurrency methodology.

For on-disk results, correlate latency with read IOPS and page-cache capacity. Rescoring reads
full-precision vectors; `oversample_factor=1.0` still rescores. A large QPS collapse with low
CPU and high random reads is an I/O or cache-capacity signal, not proof that HNSW search is slow.

## Resources

- [references/scenario-matrix.md](references/scenario-matrix.md): experiment variants and
  deployment-specific constraints
- [references/runbook.md](references/runbook.md): setup, preflight, execution, and cleanup
- [references/result-analysis.md](references/result-analysis.md): metrics, validity checks,
  on-disk diagnosis, and report format
- `scripts/generate_benchmark_plan.py`: deterministic VectorDBBench command and manifest generator
