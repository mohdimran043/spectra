# Search Architecture

The search pipeline is designed around one constraint: **query cost must not grow with corpus size.**
Everything expensive happened at ingestion. Search reads indexes.

---

## Staged retrieval

```
Stage 1  Candidate generation   exact IDs ∥ BM25 ∥ dense ANN ∥ multimodal ANN
Stage 2  Filtering              source · time · entity · type · media · PERMISSIONS
Stage 3  Fusion + reranking     reciprocal rank fusion, then cross-encoder on the top-K
Stage 4  Scoring                unified multi-signal score
Stage 5  Assembly               snippets, provenance, score breakdown
```

Only stage 3's reranker and (in the agent) stage 5's consumers touch a model, and only over a few
dozen candidates — never over the corpus.

### Stage 1 — candidate generation

Four generators run concurrently (`asyncio.gather`):

- **Exact identifier lookup.** If the query contains an enterprise identifier, it is looked up
  directly in the lexical index and the entity index. This is near-free and is why
  `Find transaction TX82931` answers in milliseconds without a model.
- **Lexical (BM25).** A real BM25 implementation (k₁ = 1.5, b = 0.75) over an inverted index, with a
  tokeniser that deliberately keeps alphanumeric identifiers like `TX82931` intact rather than
  splitting them — a subtle but decisive detail for enterprise retrieval.
- **Dense ANN.** Query embedded once, cosine ANN over the text collection.
- **Multimodal ANN.** For image queries: text→image via the shared CLIP-style space, image→image via
  the uploaded image's embedding.

Each generator returns an independently ranked list. None of them is trusted alone.

### Stage 2 — filtering

Metadata filters plus, critically, **permission filtering**. Every hit is checked against the
caller's `PermissionContext` (source access, denied sources, role vs the chunk's permission list).
This is a correctness requirement: it runs before ranking, and the cache key includes the role so
one role can never be served another's cached results.

### Stage 3 — fusion and reranking

Lexical and dense lists are fused with **Reciprocal Rank Fusion** (k = 60) rather than by
normalising incompatible score scales. RRF is robust when one retriever is confidently wrong, which
is exactly the failure mode of pure vector search on identifier queries.

The top `rerank_top_k` fused candidates then go to a cross-encoder. If no reranker is available the
pipeline degrades to fused order and **says so** in `degraded_reasons` — it does not silently return
worse results.

### Stage 4 — unified scoring

Ranking is explicitly **not** cosine similarity. Seven signals, each kept separately on every hit so
the UI can show the breakdown and a researcher can ablate them:

| Signal | What it captures |
|---|---|
| `lexical` | BM25 term evidence |
| `semantic` | dense similarity |
| `rerank` | cross-encoder relevance |
| `entity_match` | does the chunk actually name the target entity |
| `metadata_match` | source/type/time alignment with the query |
| `source_reliability` | configurable authority of the source |
| `freshness` | exponential decay on recency |

Signals are min-max normalised *within the result set* before weighting, so a weak absolute score
does not drag a result down when everything scored weakly.

### Stage 5 — assembly

Snippets are windowed around the best matching term, with matches marked `«like this»` so the UI
highlights exactly what matched. Provenance is reconstructed into a typed locator, so every hit is
openable at its exact page / second / row.

---

## Search directions

All of these are implemented, and all read indexes only:

| Direction | Mechanism |
|---|---|
| Text → document/audio/video | BM25 + dense over text chunks (transcripts are text chunks) |
| Text → image | query embedded into the multimodal space vs stored image embeddings |
| Image → image | uploaded image embedded once, multimodal ANN |
| Image → video | image embedding vs stored keyframe embeddings |
| Image → database | OCR at ingestion → entity extraction → resolution → SQL lookup |
| Database → multimodal | record's entities → cross-modal links → documents/video/images |
| Video → document | transcript entities → resolution → document retrieval |

Image→database deserves a note, because it is the demo everyone remembers: the image is *ingested*
(OCR, caption, embedding), then its extracted identifiers are resolved to canonical entities, then
the database agent looks those entities up. At no point is a model run over a corpus.

---

## Caching

Redis (or the in-process map) caches query embeddings, repeated retrievals, entity resolutions,
database schemas and source metadata. Cache keys include:

```
query · mode · filters · top_k · role/permission fingerprint · index_version · embedding model identity
```

Omitting any of these produces either stale results after a reindex or a cross-role data leak. All
five are included.

---

## Fast mode vs deep mode

| | Fast | Deep |
|---|---|---|
| Reranker | no | yes |
| Latency target | ~1 s | ~3 s |
| Typical path | ID detect → exact + BM25 → answer | full hybrid + cross-encoder |

Fast mode exists because `TX82931` should not cost a cross-encoder pass over the whole candidate
set. Both modes run the same five stages; deep mode simply widens the candidate pool and reranks.

---

## Why not just rank by vector similarity

Three concrete failure modes this architecture is built to avoid:

1. **Identifier queries.** Embeddings treat `TX82931` and `TX82930` as nearly identical. Exact
   lookup and BM25 do not.
2. **Corroboration blindness.** Three paragraphs of one PDF look like three pieces of evidence to a
   similarity ranker. Evidence diversity (see [agent-design.md](agent-design.md)) makes independence
   explicit.
3. **Stale authority.** A superseded document can be the most semantically similar text in the
   corpus. Source reliability and version status demote it, and the reason is inspectable.
