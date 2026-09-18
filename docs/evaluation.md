# Evaluation — Research / Thesis Mode

SPECTRA is built to be *studied*, not just demonstrated. The evaluation harness exists so each
architectural claim can be measured and ablated against the same corpus.

## What is being claimed

1. cross-modal entity resolution
2. evidence-centric investigation
3. evidence-grounded claim construction
4. disconfirming-evidence search
5. evidence-based claim status assessment
6. temporal evidence reasoning
7. adaptive retrieval budgets
8. evidence sufficiency and abstention
9. latency vs accuracy trade-offs
10. multimodal vs single-modal baselines

## Baselines

Five strategies over the identical index, behind one `Baseline` interface:

| Baseline | What it does | What it deliberately lacks |
|---|---|---|
| **A — BM25** | lexical retrieval only | semantics, multimodality, agency |
| **B — Vector RAG** | dense retrieval + concatenation | lexical precision on ids, agency |
| **C — Multimodal RAG** | dense + multimodal retrieval | agency, claims, verification |
| **D — Agentic retrieval** | tool-using iterative loop | claims, disproof, verification |
| **E — SPECTRA** | full evidence-grounded investigation | — |

D→E is the interesting comparison: it isolates the contribution of evidence-grounded claims,
disconfirming search and verification from the contribution of merely being agentic.

## Benchmark categories

Three or more questions each, all with ground truth in `demo-data/expected/`:

```
single-source retrieval · cross-document retrieval · image retrieval · video retrieval
audio retrieval · database reasoning · image→DB · DB→video · video→document
entity resolution · multi-hop investigation · temporal reasoning
conflicting sources · claim verification · evidence sufficiency · abstention
```

The abstention category matters most and is the easiest to omit: questions whose *correct* answer is
"insufficient evidence". A system that always answers scores zero there, which is the point.

## Metrics

**Retrieval** — recall@k, precision@k, MRR, nDCG@k.

**Resolution** — entity-resolution precision / recall / F1 over resolved canonical ids.

**Evidence** — completeness (fraction of expected targets actually cited), claim support (fraction of
answer claims with a valid citation), evidence diversity.

**Reasoning** — investigation success (conclusion match + status match), and leading-claim accuracy:
whether the highest-confidence claim is the one the ground truth names. Because claims are scored
independently rather than against each other, this measures whether the evidence backing is right,
not whether the ranking arithmetic is.

**Calibration** — abstention correctness, split into *correctly abstained*, *wrongly abstained* and
*wrongly answered*. The last is the dangerous one.

**Cost** — latency percentiles, tool-call count, GPU compute proxy, model calls by role.

## Running it

```bash
make benchmark
# or
python -m spectra_eval.runners --suite default --baselines bm25,vector_rag,multimodal_rag,agentic,spectra
```

Also exposed over HTTP: `GET /api/eval/benchmarks`, `POST /api/eval/run`.

Reports are written to `evaluation/spectra_eval/reports/` as JSON and Markdown, with per-category
comparison tables, a baseline-vs-SPECTRA summary, latency and tool-efficiency tables, and an explicit
**"where SPECTRA loses"** section. A benchmark report that only shows wins is marketing, not research.

## Performance benchmarks

```bash
python -m spectra_eval.runners.performance --scale small|medium|large
```

Tiers: 100 / 1 000 documents · 1 000 / 10 000 images · 10 / 100 videos · 10k / 100k database rows.
Measures ingestion rate, query latency, vector latency, BM25 latency, reranking latency, model
latency, graph latency and end-to-end latency.

## Reproducibility

The dataset generator is seeded and deterministic — same seed, byte-identical structured data. Ids
are *generated*, not hard-coded, and written to `demo-data/generated/manifest.json`; every benchmark
question resolves through that manifest. Re-running with a different seed produces a different world
in which every question still has a correct answer, which is the check that the benchmark tests the
system rather than memorised constants.

## Interpreting results across hardware tiers

Benchmark runs on this host are now **full-capability GPU runs**: the RTX 4090 is usable, generation
is genuinely generative, and investigation-success and claim-support numbers are directly meaningful.
Runs recorded before 2026-09-18 were CPU/extractive and are not comparable on those two metrics.

The distinction still matters for anyone running the harness elsewhere, so it stays labelled:

- **No generative runtime** — synthesis is extractive and every answer is flagged degraded.
  Retrieval, entity-resolution, and abstention metrics remain meaningful, because those
  paths do not depend on generation. Investigation-success and claim-support are **not** comparable to
  a GPU run, and the report labels them accordingly.
- **GPU present** — all sixteen categories are comparable across the five baselines.

Always report which tier a run came from; the report header records the resolved profile, runtime and
`degraded_reasons` so this is not a matter of memory.
