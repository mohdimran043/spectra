"""SPECTRA evidence layer.

Evidence ledger, evidence graph, timeline, contradiction radar, source
reliability and enterprise application resolution - the components that make
SPECTRA an investigation platform: every claim is citable, every ranking is
explainable, and every disagreement is surfaced rather than smoothed over.
"""

from .application_resolver import (
    ApplicationConfigError,
    ApplicationResolver,
    ApplicationTemplate,
    VerifyCallable,
    load_application_templates,
)
from .builder import EvidenceBuilder
from .contradiction import (
    KIND_POLARITY_CONFLICT,
    KIND_TEMPORAL_IMPOSSIBILITY,
    KIND_VALUE_CONFLICT,
    RESOLUTION_WEIGHTS,
    ContradictionRadar,
)
from .graph import EDGE_TYPES, NODE_LABELS, EvidenceGraph, GraphVocabularyError
from .ledger import SUFFICIENCY_WEIGHTS, LedgerService
from .lexicons import ATTRIBUTE_LEXICON, PRECEDENCE_RULES
from .reliability import (
    ReliabilityConfig,
    ReliabilityConfigError,
    ReliabilityScorer,
    kind_for_provenance,
    load_reliability_config,
)
from .service import EvidenceService, build_evidence_service
from .timeline import (
    PRECISION_DAY,
    PRECISION_EXACT,
    PRECISION_MINUTE,
    PRECISION_RELATIVE,
    TimelineBuilder,
)
from .triples import AttributeClaim, extract_claims

__all__ = [
    "ATTRIBUTE_LEXICON",
    "EDGE_TYPES",
    "KIND_POLARITY_CONFLICT",
    "KIND_TEMPORAL_IMPOSSIBILITY",
    "KIND_VALUE_CONFLICT",
    "NODE_LABELS",
    "PRECEDENCE_RULES",
    "PRECISION_DAY",
    "PRECISION_EXACT",
    "PRECISION_MINUTE",
    "PRECISION_RELATIVE",
    "RESOLUTION_WEIGHTS",
    "SUFFICIENCY_WEIGHTS",
    "ApplicationConfigError",
    "ApplicationResolver",
    "ApplicationTemplate",
    "AttributeClaim",
    "ContradictionRadar",
    "EvidenceBuilder",
    "EvidenceGraph",
    "EvidenceService",
    "GraphVocabularyError",
    "LedgerService",
    "ReliabilityConfig",
    "ReliabilityConfigError",
    "ReliabilityScorer",
    "TimelineBuilder",
    "VerifyCallable",
    "build_evidence_service",
    "extract_claims",
    "kind_for_provenance",
    "load_application_templates",
    "load_reliability_config",
]
