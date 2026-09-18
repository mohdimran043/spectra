"""Named thresholds for the SPECTRA Brain.

Every constant here carries the reason it holds its value.  Nothing in the
agent may compare against a bare literal - reviewers must be able to see *why*
a boundary sits where it does.
"""

from __future__ import annotations

# -- evidence admission ---------------------------------------------------
# Retrieval returns a long tail; below this fused score a hit contributes more
# noise than signal, so it is rejected with a recorded reason instead of being
# silently dropped.
MIN_EVIDENCE_RELEVANCE = 0.12

# Corroboration target used by the sufficiency score: four independent facts is
# the point where adding another item stops changing an analyst's conclusion.
TARGET_EVIDENCE_COUNT = 4

# Sufficiency blend.  Volume alone is not sufficiency - three paragraphs of one
# PDF must not outrank a database row plus a document plus a video - so
# diversity carries the same weight as volume and quality carries the rest.
SUFFICIENCY_COUNT_WEIGHT = 0.35
SUFFICIENCY_DIVERSITY_WEIGHT = 0.35
SUFFICIENCY_QUALITY_WEIGHT = 0.30

# -- verification ---------------------------------------------------------
# A claim repeated by one source is one source's opinion; two independent
# sources is the minimum an analyst would accept as corroboration.
MIN_INDEPENDENT_SOURCES = 2

# EvidenceLedger.diversity() gives ~0.32 for a single source in a single
# modality and ~0.50 once a second independent source appears.  0.34 is
# therefore the smallest value that rejects "one source, one modality".
MIN_DIVERSITY = 0.34

# -- claim scoring --------------------------------------------------------
# A claim is scored on its OWN evidence.  Nothing here divides a probability
# mass between rival statements, so a single well-corroborated conclusion keeps
# a high confidence instead of losing most of it to the alternatives it was
# listed beside.

# Full confidence requires at least two supporting items (see
# MIN_INDEPENDENT_SOURCES - the same corroboration argument).
MIN_SUPPORTING_ITEMS = 2

# Quality is the mean weight of the strongest few supporting items: a long tail
# of weak corroboration must not dilute a claim that two strong items back.
CLAIM_QUALITY_SAMPLE = 4

# Corroboration blend.  Volume alone is not corroboration - four excerpts of one
# PDF are one source's word - so independence and diversity together outweigh
# the item count.
CLAIM_COUNT_WEIGHT = 0.40
CLAIM_SOURCE_WEIGHT = 0.35
CLAIM_DIVERSITY_WEIGHT = 0.25

# A claim backed by one narrow source keeps 55% of its evidence quality: thin
# corroboration is a discount on a real finding, not an erasure of it.
CORROBORATION_FLOOR = 0.55

# Status machine boundary.  0.60 is "more likely than not, with corroboration";
# below it a claim is reported as weak rather than supported.
CLAIM_SUPPORTED_MIN = 0.60

# Conflicting evidence worth two fifths of the support is already enough to say
# credible evidence points the other way; once it matches the support outright,
# across at least two independent items, the claim is refuted.  One loud
# contradiction is a conflict, not a refutation.
CONTRADICTED_WEIGHT_RATIO = 0.4
REFUTED_WEIGHT_RATIO = 1.0
MIN_CONTRADICTING_FOR_REFUTED = 2

# Below this the leading claim is too weak to stop investigating.
WEAK_LEADER_CONFIDENCE = 0.35

# Claim-set size: a deep investigation should state more than a single finding
# when the evidence carries one, and more than six claims cannot all be probed
# inside a deep-mode budget.
MIN_CLAIMS_DEEP = 3
MAX_CLAIMS = 6

# An LLM-proposed claim must share at least this many content tokens with the
# retrieved corpus, otherwise it is an invention and is dropped.
LLM_GROUNDING_MIN_OVERLAP = 2

# -- disproof probe -------------------------------------------------------
# Each negation query costs a tool call; four covers the claim negation plus the
# main competing outcomes without starving the rest of the budget.
MAX_NEGATION_QUERIES = 4

# -- synthesis ------------------------------------------------------------
# Answers stay auditable: every sentence is cited, and more than six cited
# sentences stops being an answer and starts being a report.
ANSWER_MAX_SENTENCES = 6

# -- streaming ------------------------------------------------------------
# A slow SSE consumer must never block the agent, so its queue is bounded and
# drops the oldest step once full.
TRACE_QUEUE_SIZE = 256

# -- orchestration --------------------------------------------------------
# One retrieval pass has tested nothing: deep mode always runs at least a
# second, claim-directed pass before it is allowed to answer.
MIN_DEEP_ITERATIONS = 2
