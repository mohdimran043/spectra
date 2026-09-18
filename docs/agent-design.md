# Agent Design — The SPECTRA Brain

The Brain is the central agent controller. It is not a chatbot wrapper, and it is not a fixed
pipeline dressed up as an agent. It is an explicit, inspectable state machine that plans, acts,
observes, revises, actively tries to *refute itself*, and knows when to stop — or when to abstain.

---

## 1. The loop

```
                 ┌──────────────────────────────────────────────┐
                 ▼                                              │
  question → understand → plan → select tools → execute ────────┤
                                                   │            │
                                              observe            │
                                                   │            │
                                    update evidence/entities/graph
                                                   │            │
                                        evidence sufficient? ───┘ no
                                                   │ yes
                                                   ▼
              disproof search → contradiction check → verify → synthesise
```

Iteration is mandatory and real. The Brain replans based on what it actually observed: a database
hit introduces new entities, which open document and video searches, which surface a contradiction,
which spawns a new hypothesis, which triggers another retrieval round.

## 2. State

Everything lives in `InvestigationState` — serialisable, persisted after every iteration, and
resumable. Transitions produce **new** objects (`model_copy(update=...)`); nothing mutates in place,
so a partially-failed iteration can never leave half-applied state.

```
goal · intent · mode · plan · hypotheses · entities · evidence(ledger)
contradictions · timeline · verification · tool_history · trace
budget · confidence · answer · answer_status · application_links · claims
metrics · degraded + reasons · agent_availability
```

## 3. Query understanding — two tiers

A deterministic rule router runs first: enterprise-identifier grammars, temporal markers, modality
words (`video`, `screenshot`, `said`, `diagram`), aggregation words, contradiction words. It
classifies intent and complexity and extracts ids and keywords.

The fast brain then *optionally refines* that classification under a strict JSON schema. If no
generative runtime is available, the rule router alone still produces a correct classification, and
`produced_by` records which tier decided. The system never depends on a model being present in order
to route.

## 4. Tools

Twenty-two real callable tools, each with a name, description, JSON input/output schema, input
validation, timeout, telemetry and a `requires_flag`:

```
search_documents · search_images · search_videos · search_audio
query_database · get_database_schema · get_database_record
resolve_entity · search_entities
search_graph · expand_graph
get_evidence · get_source_metadata
get_document_page · get_video_timestamp · get_image
verify_claim · search_supporting_evidence · search_disconfirming_evidence
detect_contradictions · build_timeline · open_application_record
```

The Brain uses structured tool calling. Independent retrieval tools run concurrently via
`asyncio.gather`; any tool marked `gpu_heavy` is serialised through a single semaphore, because the
development target has one GPU.

## 5. Hypotheses

For investigation-intent queries the Brain generates **competing** explanations, each with:

```
hypothesis_id · description · rationale · prior · confidence · status
supporting_evidence[] · contradicting_evidence[]
predicted_signals[]   ← what evidence should exist if this is true
disproof_probe        ← what evidence would prove this wrong
verified · verification_note
```

Status lifecycle:

```
OPEN ──► SUPPORTED     strong corroborated support, no live contradiction
     ├─► WEAK          some support, thin or non-independent
     ├─► CONTRADICTED  credible conflicting evidence exists
     ├─► DISPROVED     disproof probe returned decisive counter-evidence
     └─► INSUFFICIENT  not enough evidence either way
```

Scoring is a damped Bayesian-flavoured update: prior × supporting weight against contradicting
weight, damped by **evidence diversity** and count. `predicted_signals` matter: a hypothesis that
predicts evidence which then fails to appear is penalised, which is how a plausible-but-wrong
explanation gets demoted rather than merely un-promoted.

When no generative runtime is available, hypotheses are mined deterministically from the retrieved
evidence — failure-reason lexicons, incident categories, error codes actually present in the corpus.
Never a hard-coded list, never a cause the evidence does not mention.

## 6. The Disproof Agent — mandatory

For the leading hypothesis the Brain asks: **what evidence would prove this wrong?** It then
actively searches for it — negation-expanded queries and searches for the competing outcomes, across
every enabled modality.

This is the component that separates investigation from retrieval. A support-only system finds three
documents agreeing with its first guess and reports 95% confidence. SPECTRA is required to go
looking for the document that disagrees.

"No conflicting evidence found" is recorded as a real, positive outcome — it is *why* a conclusion
earns high confidence, not an absence of work.

## 7. Contradiction radar

Contradictions are detected structurally, not guessed:

- **Value conflicts** — `(entity, attribute, value)` triples extracted with attribute lexicons;
  two different values for the same pair is a conflict.
- **Polarity conflicts** — negation-aware matching of the same predicate.
- **Temporal impossibility** — ordering that the timestamps contradict.

They are then **explained and adjudicated** using recency, version status (superseded loses),
source reliability and specificity. The resolution and its reasoning are shown. The system explains
contradictions; it never hides them.

## 8. Verification

Before an answer is emitted, the Verifier checks:

1. every entity named in the claim actually appears in cited evidence;
2. at least N *independent* sources support it;
3. no unresolved contradiction touches it;
4. evidence diversity is above threshold.

Each check is reported individually. A model cross-check is optional; if unavailable, the
deterministic checks stand and the response says so.

## 9. Evidence diversity — an explicit first-class quantity

Three paragraphs from one PDF must not outweigh one database record + one PDF + one video. Diversity
is computed from distinct sources, distinct modalities and distinct assets, and it damps hypothesis
confidence directly. Independent corroboration is the thing being measured, not volume.

## 10. Sufficiency and abstention

Sufficiency combines evidence weight, count, diversity, independent-source count and a contradiction
penalty. Below threshold, SPECTRA **abstains**:

> Insufficient evidence. I found related information but cannot establish the requested conclusion
> with sufficient support.

…followed by what *was* found and what is missing. Abstention is a first-class outcome with its own
`AnswerStatus`, and it is measured in the benchmark suite. A system that cannot say "I don't know"
is not an investigation system.

## 11. Grounded synthesis

Every sentence in the answer must be traceable to an `EvidenceItem`. With a generative model, the
prompt contains **only** evidence excerpts, inline citations are required, and each citation is
then **verified to exist** — unsupported sentences are dropped or flagged. Without one, the answer
is assembled extractively from the highest-weight evidence. There is no configuration in which
SPECTRA emits an uncited factual claim.

## 12. Budgets

```yaml
fast: { max_tool_calls: 5,  max_latency_seconds: 3,  iterations: 1 }
deep: { max_tool_calls: 30, max_latency_seconds: 60, iterations: 8 }
```

Checked before every tool call and every iteration. Exhaustion is a clean stop with
`exhausted_reason` recorded and the best-supported answer still returned — never a crash, never a
silent truncation. The Brain also stops *early* when evidence is already sufficient; the budget is a
ceiling, not a quota to spend.

## 13. Degradation

`settings.agent_flags()` plus runtime overrides from the Agent Control Center determine what exists.
A disabled agent is excluded from planning and reported honestly:

```
VISION AGENT
Status: Disabled
Reason: User disabled vision for this investigation.
Available alternatives: Documents, Videos, Database
```

The Brain plans around the gap, the investigation completes if the remaining evidence is sufficient,
and `degraded` + `degraded_reasons` say what was missing. No crashes. No fabricated substitutes.

## 14. Observability without chain-of-thought exposure

Every step emits a `TraceStep`:

```
step_id · sequence · agent · tool · status · title
input_summary · output_summary · latency_ms · evidence_ids
```

These are **action summaries**: "Searching database", "3 relevant documents", "Evidence consistent".
Internal model reasoning is never exposed. Traces stream over SSE and are persisted for replay.

## 15. Search Autopsy

After an investigation, the full forensic record: sources considered, candidates retrieved, evidence
used vs rejected (with reasons), tool-call count and breakdown, contradictions, total and per-stage
latency, models used, GPU peak, hypotheses generated and disproved, and evidence diversity.

It exists because "the system found the right answer" is a much weaker claim than "here is exactly
what the system considered, what it discarded, and why."
