# Agent Design — The SPECTRA Brain

The Brain is the central agent controller. It is not a chatbot wrapper, and it is not a fixed
pipeline dressed up as an agent. It is an explicit, inspectable state machine that plans, acts,
observes, revises, actively tries to *refute itself*, and knows when to stop — or when to abstain.

---

## 1. The loop

```
                 ┌───────────────────────────────────────────────┐
                 ▼                                               │
  question → understand → plan → retrieve → build claims ────────┤
                                     │                           │
                          observe; update evidence /             │
                          entities / graph                       │
                                     │                           │
                          evidence sufficient? ──────────────────┘ no
                                     │ yes
                                     ▼
      disproof the leading claim → contradiction check → verify → synthesise
```

Iteration is mandatory and real. The Brain replans based on what it actually observed: a database
hit introduces new entities, which open document and video searches, which surface a contradiction,
which changes the status of a claim and sends the Brain back for the retrieval round that settles
it.

## 2. State

Everything lives in `InvestigationState` — serialisable, persisted after every iteration, and
resumable. Transitions produce **new** objects (`model_copy(update=...)`); nothing mutates in place,
so a partially-failed iteration can never leave half-applied state.

```
goal · intent · mode · plan · entities · evidence(ledger)
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

## 5. Claims

For investigation-intent queries the `claim_builder` agent derives **claims** from the evidence that
has actually been retrieved, grounded to the investigation's focal entity. A claim is a statement
the corpus asserts about that entity, not a candidate pulled from a catalogue of plausible causes.

```
claim_id · text · confidence · status · rationale
supporting_evidence[] · contradicting_evidence[]
disproof_probe        ← what evidence would show this claim is wrong
disproof_searched · verified · verification_note
```

Ids are `C1`, `C2`, … within one investigation. `evidence_ids` is the union of the two evidence
lists; `confidence_label` bands the score. The agent's toggleable flag is `claim`
(`ENABLE_CLAIM_BUILDER=0`, setting `enable_claim_builder`); disabling it degrades the investigation
like any other missing agent rather than failing it.

Status:

| Status | Meaning |
|---|---|
| `supported` | corroborated by independent evidence, nothing credible against it |
| `weak` | some support, but thin or from a single source |
| `contradicted` | credible evidence points the other way |
| `refuted` | the disproof search returned decisive counter-evidence |
| `insufficient` | not enough evidence either way |

**Each claim is scored on its own evidence alone**: supporting weight, independent-source count and
**evidence diversity**, minus a contradiction penalty. Claims do not compete and their confidences
are not normalised, so a well-supported conclusion keeps a high confidence however many other things
the corpus also says.

That is a correction, and worth stating plainly. SPECTRA previously generated competing explanations
and normalised their confidences across the candidate set so they summed to about 1. The arithmetic
punished the case it was meant to serve: a correct conclusion sharing probability mass with six weak
alternatives peaked near 16%, fell below the sufficiency threshold, and the system abstained on
questions it had in fact answered correctly. A score divided between candidates measures how many
alternatives were imagined, not how well the evidence backs the answer. Judging each claim against
its own evidence measures the thing that matters; the guard against over-confidence is the
mandatory disconfirming search in §6, not the presence of rivals.

When no generative runtime is available, claims are mined deterministically from the retrieved
evidence — failure-reason lexicons, incident categories, error codes actually present in the corpus.
Never a hard-coded list, never an assertion the evidence does not make.

## 6. The Disproof Agent — mandatory

For the leading claim (`state.leading_claim()`) the Brain asks: **what evidence would show this is
wrong?** It records that as the `disproof_probe` and then actively searches for it: negation-expanded
queries and searches for the opposite outcome, across every enabled modality.

This is the component that separates investigation from retrieval. A support-only system finds three
documents agreeing with its first guess and reports 95% confidence. SPECTRA is required to go
looking for the document that disagrees.

`disproof_searched` records that the search ran, and a claim the probe knocks down becomes `refuted`
and is dropped from consideration: `leading_claim()` never returns a refuted claim. This is what
keeps confidence honest now that nothing else competes for it. Confidence is high because the
counter-evidence was looked for and not found, not because no alternative was offered.

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
is computed from distinct sources, distinct modalities and distinct assets, and it damps claim
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
latency, models used, GPU peak, `claims_made` / `claims_refuted`, and evidence diversity.

It exists because "the system found the right answer" is a much weaker claim than "here is exactly
what the system considered, what it discarded, and why."
