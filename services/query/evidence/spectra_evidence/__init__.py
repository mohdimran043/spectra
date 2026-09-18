"""SPECTRA evidence layer.

Evidence ledger, evidence graph, timeline, source reliability and
enterprise application resolution - the components that make SPECTRA an
investigation platform: every claim is citable and every ranking is
explainable.
"""

from .application_resolver import (
    ApplicationConfigError,
    ApplicationResolver,
    ApplicationTemplate,
    VerifyCallable,
    load_application_templates,
)
from .builder import EvidenceBuilder
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
    "NODE_LABELS",
    "PRECEDENCE_RULES",
    "PRECISION_DAY",
    "PRECISION_EXACT",
    "PRECISION_MINUTE",
    "PRECISION_RELATIVE",
    "SUFFICIENCY_WEIGHTS",
    "ApplicationConfigError",
    "ApplicationResolver",
    "ApplicationTemplate",
    "AttributeClaim",
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
