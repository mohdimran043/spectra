# Scaling

The development environment is small. The architecture is not.

| | Development | Production target |
|---|---|---|
| Corpus | ~100s of objects | TB–PB of documents / images / video |
| Records | ~10k rows | millions–billions |
| Users | 1 | thousands |
| GPUs | 1 × RTX 4090 | GPU inference pool |
| Indexes | SQLite + NumPy | Qdrant + OpenSearch clusters |

Nothing below changes the agent contract.

---

## 1. What makes scaling possible

**Ingestion/search separation.** Query cost is a function of index lookups, not corpus size. A TB of
video costs the same at query time as a GB, because the expensive work already happened.

**Canonical references.** Everything is `source_id` / `asset_id` / `chunk_id` / `entity_id` /
`object_uri`. No component resolves a local path, so moving from a `data/` folder to an S3 bucket is
configuration.

**Store interfaces.** Six abstract stores with swappable backends. `VECTOR_BACKEND=qdrant` is a
one-line change; no calling code is aware.

**Streaming discovery.** Connectors yield `AsyncIterator[DiscoveredItem]`. A source with a hundred
million objects is never materialised in memory.

**Batched, resumable ingestion.** Jobs carry checkpoints; the worker pulls rather than being pushed,
so horizontal scaling is adding worker processes.

---

## 2. Development topology

```
1 API process · 1 worker · SQLite · NumPy vectors · SQLite BM25 · SQLite graph · filesystem objects · in-process cache
```

`make up` brings the full distributed stack instead if you want it locally:

```
postgres · qdrant · opensearch · neo4j · redis · minio
```

## 3. Production topology

```
                         load balancer
                               │
                    ┌──────────┴──────────┐
                agent/API services   (stateless, N replicas)
                               │
                       retrieval layer
                     ┌─────────┼─────────┐
              Qdrant cluster  OpenSearch cluster
                     └─────────┼─────────┘
                        object storage (S3)
                               │
                       PostgreSQL cluster
                               │
                        Neo4j cluster
                               │
                       GPU inference pool (vLLM / TGI)
                               │
                       worker pool (ingestion)
```

Every SPECTRA process is stateless apart from the stores. Scaling reads = more API replicas.
Scaling ingestion = more workers. Scaling inference = more model-server replicas behind
`VLLM_BASE_URL` / `OPENAI_BASE_URL`.

## 4. Sharding strategy

| Dimension | Approach |
|---|---|
| Vectors | Qdrant collections sharded by `source_id`; the filter is already part of every query |
| Lexical | OpenSearch index-per-tenant or per-source-group, with aliases for cross-source search |
| Objects | Content-addressed prefixes (`objects/<aa>/…`) distribute naturally across S3 partitions |
| Relational | Read replicas for search-path queries; the control plane is small and write-light |
| Graph | Partition by entity domain; the graph is queried by bounded-depth neighbourhood, not global traversal |

## 5. Ingestion throughput

Ingestion is embarrassingly parallel per asset. The bottlenecks, in order:

1. **ASR** for video/audio — the dominant cost. Batch on the GPU pool, or use a smaller Whisper model
   for bulk and large-v3 for high-value assets.
2. **Vision captioning** of keyframes — cap keyframes per scene; not every frame needs a caption.
3. **Embedding** — batch aggressively; this is what GPU inference pools are for.
4. **Extraction** — CPU-bound and cheap; scales with worker count.

The scale benchmark in `evaluation/spectra_eval/runners/performance.py` measures each tier
(100/1 000 documents, 1 000/10 000 images, 10/100 videos, 10k/100k rows).

## 6. Query latency budget at scale

```
exact-id lookup        ~1–5 ms     (index seek)
BM25                   ~10–40 ms   (OpenSearch, sharded)
dense ANN              ~10–50 ms   (Qdrant HNSW)
filter + fusion        ~1–5 ms     (in process)
cross-encoder rerank   ~50–200 ms  (top-K only, GPU pool)
generation             dominant when used
```

This is why fast mode exists and why the reranker only ever sees the top-K. The expensive stages are
bounded by K, not by N.

## 7. Multi-tenancy

`PermissionContext` is already threaded through every retrieval path and included in every cache key.
Tenant isolation is source-level access control plus per-tenant index aliases — the mechanism exists;
production only needs the identity provider wired in place of the header shim.

## 8. What would need real work

Honest limitations of the current implementation at true production scale:

- The embedded backends are development-grade by design. Brute-force cosine over a cached matrix is
  correct and fast to ~10⁵ vectors; beyond that you must use Qdrant.
- The graph's embedded backend does bounded BFS in SQLite. Fine for investigation-sized
  neighbourhoods, not for global analytics — use Neo4j.
- The worker's job claim is simple polling. At high ingest rates it should become a real queue
  (the `CacheStore` interface already fronts Redis, so a Redis stream is the natural step).
- Hypothesis generation is one deep-brain call per investigation; at thousands of concurrent
  investigations that becomes the cost centre, and would want batching at the inference pool.
