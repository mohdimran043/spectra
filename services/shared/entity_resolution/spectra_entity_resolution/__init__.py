"""SPECTRA entity resolution: surface forms -> canonical, cross-modal entities."""

from __future__ import annotations

from .canonical import create_entity, entity_from_row, extend_entity, keys_for_mention
from .extractor import EntityExtractor
from .matching import best_fuzzy_match, cosine_similarity
from .normalize import EnterpriseId, PersonKeys, enterprise_ids, normalize_surface, person_keys
from .patterns import ALL_PATTERNS, ID_PATTERNS, EntityPattern
from .resolver import DbLookup, EntityResolver
from .service import EntityResolutionService
from .verification import verify_candidates

__all__ = [
    "ALL_PATTERNS",
    "DbLookup",
    "EnterpriseId",
    "EntityExtractor",
    "EntityPattern",
    "EntityResolutionService",
    "EntityResolver",
    "ID_PATTERNS",
    "PersonKeys",
    "best_fuzzy_match",
    "cosine_similarity",
    "create_entity",
    "enterprise_ids",
    "entity_from_row",
    "extend_entity",
    "keys_for_mention",
    "normalize_surface",
    "person_keys",
    "verify_candidates",
]
