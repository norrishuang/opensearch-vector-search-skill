# Guided Capacity-Planning Intake

Use this reference when a user wants cluster sizing, resource estimation, or cost
comparison but has not supplied a complete workload description.

The goal is to make the conversation easy for users who do not know OpenSearch
vector-search terminology. Present choices, accept free-form values, and explain
only the terms needed for the current decision.

## Interaction Pattern

Start with the four-item form below. Adapt it to facts already provided and omit
answered fields. The user may reply with option numbers, labels, custom values, or
"not sure". Do not show the advanced form in the same message unless the user asks
for all parameters or has already supplied most basic inputs.

```text
为了先做一版 OpenSearch 向量集群评估，请告诉我：

1. 向量数量（必填）
   例如：1,000 万；或 500 万文档 × 每篇 3 个向量

2. 向量维度（必填）
   例如：384 / 768 / 1024 / 1536；不知道可填写 embedding 模型名称

3. 环境
   A. 开发/测试
   B. 生产
   C. 不确定

4. 优先目标
   A. 搜索质量和低延迟
   B. 成本
   C. 两者平衡
   D. 请比较多个方案

你只回答前两项也可以；算法、压缩和集群配置可以由我推荐。
```

After the user answers, ask only the advanced inputs that materially distinguish
the candidate configurations. Present this expanded menu when useful:

```text
可选的进一步信息：

1. 搜索方案
   A. HNSW + FAISS（推荐默认，适合大多数近似搜索）
   B. HNSW + Lucene
   C. 精确搜索
   D. 不确定，请推荐

2. 运行模式
   A. 内存模式（低延迟、成本较高）
   B. on-disk 模式（节省内存、依赖存储性能）
   C. 两种都比较
   D. 不确定，请推荐

3. 压缩/量化
   A. 不压缩 FP32（质量优先）
   B. FP16，2x
   C. Byte/Int8，4x（稳妥的成本优化起点）
   D. 4-bit，8x
   E. 2-bit，16x
   F. 1-bit SQ，32x（成本优先，需验证召回率）
   G. 比较多个方案
   H. 不确定，请推荐

4. 性能目标
   峰值 QPS、P95/P99 延迟、top-k、目标 Recall

5. 可用性与数据增长
   副本数：0 / 1（生产常用）/ 2 / 不确定
   未来 12 个月增长：例如 30%

6. 部署信息
   AWS Region、OpenSearch 版本、预算或已有实例限制
```

Do not expose every choice when a shorter question is enough. For example, if the
user has already selected on-disk 32x, do not ask the generic compression menu
again; ask for version, latency tolerance, and storage performance instead.

## Required and Derived Inputs

The initial minimum is:

- vector count at the planning horizon
- vector dimension

Help derive them when necessary:

```text
planning_vectors =
  current_items * vectors_per_item * (1 + growth_rate)
```

If vectors are added and deleted over time, ask whether the supplied count means
currently searchable live vectors or cumulative indexed vectors. Use live vectors
for steady-state capacity and discuss merge/indexing headroom separately.

Derive dimension from the embedding model only when the model and selected output
dimension are unambiguous. Otherwise ask the user to confirm it.

## Normalize Ambiguous Terms

Users may use "algorithm" to mean different things. Normalize it into:

- ANN method: HNSW or exact search
- engine: FAISS or Lucene
- similarity metric: cosine, inner product, or L2
- storage mode: in-memory or on-disk
- quantization/compression: FP32, FP16/2x, byte/4x, 4-bit/8x,
  2-bit/16x, or 1-bit/32x

Do not force a similarity choice if the embedding model defines it. Use cosine as
the provisional default only when vectors are normalized or the model recommends
cosine; otherwise state that the metric must match model training.

## Recommendation Defaults

Use defaults as starting points, not hidden decisions:

- ANN: HNSW
- engine: FAISS
- `m`: 16
- replicas: 1 for a production estimate, 0 for a development estimate
- compare these candidates when mode/compression is unknown:
  - quality-first: in-memory FP32 or FP16/2x
  - balanced: in-memory byte/4x
  - cost-first for latency-tolerant workloads: on-disk 16x or 32x

Do not recommend on-disk based only on vector count. QPS, tail latency, recall,
EBS IOPS/throughput, page cache, and OpenSearch version materially affect it.

For 1-bit SQ/32x, require OpenSearch 3.6+ and prefer 3.7+; read
`quantization-1bit-32x.md`. If the version is unknown, label the option
version-dependent.

## Handling Missing Optional Inputs

If the user supplies only count and dimension, do not block. Produce a preliminary
comparison using clearly labeled scenarios:

1. development: 0 replicas
2. production baseline: 1 replica
3. balanced compression: byte/4x
4. cost-first candidate: on-disk 32x only when version and latency constraints
   make it plausible

State that the result is memory-capacity sizing, not a QPS guarantee. Request the
following next because they commonly change node count or architecture:

- peak QPS and concurrency
- P95/P99 latency target
- `k` and recall target
- indexing/update rate
- filter selectivity and hybrid-search use
- availability target and AZ topology
- OpenSearch version and Region

## Confirmation Before Calculation

Before calculating, summarize normalized values in a compact table:

| Input | Value | Status |
|---|---|---|
| Planning vector count | ... | provided/derived/assumed |
| Dimension | ... | provided/derived |
| Method and engine | ... | selected/recommended |
| Mode and compression | ... | selected/scenario |
| HNSW `m` | ... | selected/default |
| Replicas | ... | selected/scenario |
| QPS and latency | ... | provided/unknown |
| Version and Region | ... | provided/unknown |

Ask for correction only when a required or high-impact interpretation is
ambiguous. Otherwise proceed and keep assumptions visible in the result.

## Example Replies the Agent Must Accept

Minimal:

```text
1 亿条，768 维，其余你推荐，生产环境。
```

Choice-based:

```text
1) 100M
2) 768
3) B（生产）
4) D（比较多个方案）
高级选项：HNSW + FAISS；内存和 on-disk 都比较；压缩选 G；
500 QPS，P95 50ms，top-k 10；1 个副本，年增长 40%；
us-east-1，OpenSearch 3.7。
```

Free-form:

```text
现在有 2000 万商品，每个商品两个向量，预计一年增长 50%。
模型输出 1024 维。延迟最好 30ms 内，不清楚该选什么压缩。
```

Normalize all three into the same capacity-planning workflow.
