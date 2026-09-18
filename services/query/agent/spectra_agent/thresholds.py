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

# -- hypothesis scoring ---------------------------------------------------
# Laplace-style smoothing in the likelihood ratio so a single item cannot drive
# the posterior to 0 or 1.
SUPPORT_SMOOTHING = 0.5

# Full confidence requires at least two supporting items (see
# MIN_INDEPENDENT_SOURCES - the same corroboration argument).
MIN_SUPPORTING_ITEMS = 2

# Damping floors: a hypothesis backed by a single narrow source keeps at most
# 60% (diversity) x 50% (count) of its raw posterior.
DIVERSITY_DAMPING_FLOOR = 0.6
COUNT_DAMPING_FLOOR = 0.5

# Status machine boundaries.  0.60 is "more likely than not, with corroboration";
# 0.30 is the point where ConfidenceLabel drops to INSUFFICIENT.
HYPOTHESIS_SUPPORTED_MIN = 0.60
HYPOTHESIS_CONTRADICTED_MAX = 0.30

# Status is decided on the *balance of evidence*, not on the displayed
# confidence (which is a share across competing explanations).  Supporting
# evidence must outweigh conflicting evidence two to one before a hypothesis may
# be called supported; conflicting evidence that merely matches the support is
# already enough to call it contradicted.
SUPPORT_DOMINANCE_RATIO = 2.0
CONTRADICTED_WEIGHT_RATIO = 1.0

# Disproof: contradicting evidence must outweigh supporting evidence three to
# one, across at least two independent items, before we declare a hypothesis
# dead.  One loud contradiction is a conflict, not a disproof.
DISPROOF_WEIGHT_RATIO = 3.0
MIN_CONTRADICTING_FOR_DISPROOF = 2

# Below this the leading explanation is too weak to stop investigating.
WEAK_LEADER_CONFIDENCE = 0.35

# Competing-explanation set size: fewer than three is not a competition, more
# than six cannot be probed inside a deep-mode budget.
MIN_HYPOTHESES_DEEP = 3
MAX_HYPOTHESES = 6

# An LLM-proposed hypothesis must share at least this many content tokens with
# the retrieved corpus, otherwise it is an invention and is dropped.
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
# second, hypothesis-directed pass before it is allowed to answer.
MIN_DEEP_ITERATIONS = 2
