"""Wall-clock budgets for tools whose owners are different agents.

Every value is a ceiling enforced by :meth:`Tool.run`; a tool that overruns it
returns a degraded ``ToolResult`` rather than stalling the investigation.  The
budgets live here - not in the agent packages - because several agents must
agree on them: a claim chased across modalities has to be given the same time
whoever asks for it.  A budget used by exactly one agent stays with that agent.
"""

from __future__ import annotations

# One budget for all four modality searches, because they run one shared
# implementation and therefore have one cost profile. Splitting it gave audio
# and documents 20s and media 45s, and a real run died on that: search_images
# evicted the query-embedding model, and search_audio then spent its whole
# budget loading it back. The ceiling has to cover a cold model load, because
# sequential GPU scheduling on one card guarantees evictions between calls.
SEARCH_TIMEOUT_SECONDS = 45.0
# Opening one already-cited locator is a targeted read rather than a search.
LOCATOR_TIMEOUT_SECONDS = 15.0
# Reasoning over evidence that is already in the ledger.
EVIDENCE_TIMEOUT_SECONDS = 20.0
# A claim is chased across every enabled modality, so it gets the search budget.
CLAIM_SEARCH_TIMEOUT_SECONDS = 45.0
