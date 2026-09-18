# Demo Guide

```bash
make up          # start the stack
make seed-demo   # generate + ingest the synthetic enterprise dataset
make demo        # run the guided scenarios
```

Then open **http://localhost:3000** (SPECTRA console) and **http://localhost:3001** (the mock
enterprise application that SPECTRA's evidence links into).

---

## The dataset

A seeded synthetic enterprise with a coherent story spread deliberately across modalities: a payment
fails; an authentication-service timeout is the true root cause; three other explanations are each
plausible and each have partial support; two versions of an approval memo disagree; the evidence only
coheres once entities are resolved across documents, video, images and the database.

Ids are generated, not hard-coded — the concrete values for your seed are in
`demo-data/generated/manifest.json`. The examples below use placeholders like `<TX>` and `<C>`.

---

## Scenario 1 — Image → Database

Upload a dashboard screenshot containing a transaction id.

```
Image → (ingestion: OCR + caption + embedding) → entity extraction → resolution
      → Database Agent → the real record → application deep links
```

**Watch for:** the trace showing OCR and resolution as *ingestion-time* work, and the deep links
being generated from resolved ids, not hard-coded.

## Scenario 2 — Text → Video

> Find where the engineer discusses the authentication problem.

Returns a video with a precise timestamp. `▶ Play from 01:24:17` seeks the player directly.

**Watch for:** no video is opened at query time — transcript chunks were indexed during ingestion.

## Scenario 3 — Database → Documents

Start from the failed transaction record and pivot outward into documents, video and images via
resolved entities.

**Watch for:** each result citing an exact page or second.

## Scenario 4 — Unified Investigation

> Investigate why this transaction failed and show me the supporting evidence.

The full pipeline: plan → multi-modal retrieval → entity resolution → hypotheses → support search →
**disproof search** → contradiction check → verification → timeline → cited answer → application links.

**Watch for:** the Disproof Agent explicitly searching for evidence that would refute the leading
hypothesis, and reporting "no conflicting evidence found" as a positive result.

## Scenario 5 — Contradiction

> The sources disagree about whether the incident was approved. Investigate.

**Watch for:** `⚠ CONTRADICTION DETECTED`, then the adjudication — version status, recency, source
reliability — with the reasoning shown rather than the conflict quietly resolved.

## Scenario 6 — Timeline

> How did this incident evolve, and what happened before the failure?

Timestamps normalised from database rows, document dates, video offsets and image EXIF into one
ordered timeline.

---

## The five acceptance scenarios

| # | Scenario | Demonstrates |
|---|---|---|
| 1 | Upload a screenshot with a transaction id, then "Investigate why this transaction failed and show me the supporting evidence." | the full image→OCR→entity→DB→documents→video→hypotheses→disproof→verify→timeline→answer→links journey |
| 2 | "Find where the architecture change was discussed." | query→video→transcript→timestamp→frame→related document |
| 3 | "Which customers mentioned in the engineering meeting had more than five failed payments?" | video→entity extraction→SQL aggregation→application links |
| 4 | "The sources disagree about whether the incident was approved. Investigate." | contradiction detection, version/timestamp analysis, reliability adjudication |
| 5 | Disable the Vision Agent, then investigate. | graceful degradation — the Brain replans, still answers, and says what was unavailable |

Run them with `make test-e2e`, or interactively from `/demo`.

---

## Demonstrating the constraint

Open `/models` during a deep investigation and watch models load and unload as the Brain moves
between the deep brain, vision and the reranker. On a working 4090 this is the clearest single
picture of sequential GPU scheduling inside a 24 GB budget.

> **The GPU on this host is live** — RTX 4090, driver 580.178.04 — so what `/models` shows is real
> CUDA residency rather than a simulated swap: the deep brain takes ~20 GB of the 22 GB budget and
> evicts the fast brain to fit. This applies to host processes; the Compose stack cannot see the card
> until the NVIDIA Container Toolkit is installed. See
> [4090-deployment.md](4090-deployment.md#gpu-status-on-this-host).

---

## Things worth trying that are not in the scripted demos

- Ask something the corpus genuinely cannot answer. SPECTRA should **abstain**, not improvise.
- Turn off the Database Agent and re-run scenario 4 — the investigation should continue on
  unstructured evidence and say what it lost.
- Open the **Search Autopsy** after any investigation: what was considered, what was rejected, why.
- Switch the role to `viewer` in Settings and watch permission filtering change the results.
- Run `make benchmark` and read the "where SPECTRA loses" section of the report.
