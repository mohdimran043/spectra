"""Pure, dependency-free text maths shared by the deterministic providers.

Everything here is reproducible: the same input always yields the same numbers
on any machine, which is what makes the deterministic tier a defensible last
resort rather than a stub.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from collections.abc import Iterable, Sequence

# -- tokenisation ---------------------------------------------------------
WORD_PATTERN = re.compile(r"[a-z0-9]+")
SENTENCE_PATTERN = re.compile(r"(?<=[.!?])\s+|\n+")
IDENTIFIER_PATTERN = re.compile(r"^(?=.*[a-z])(?=.*\d)[a-z0-9]{4,}$")
# Identifier-shaped spans in the *original* text, so casing and hyphens survive.
IDENTIFIER_SPAN = re.compile(r"\b(?=[A-Za-z0-9._-]*[A-Za-z])(?=[A-Za-z0-9._-]*\d)[A-Za-z0-9][A-Za-z0-9._-]{3,}\b")
NUMBER_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")

# -- feature weighting ----------------------------------------------------
UNIGRAM_WEIGHT = 1.0
BIGRAM_WEIGHT = 0.5
NGRAM_WEIGHT = 0.35
MIN_CHAR_NGRAM = 3
MAX_CHAR_NGRAM = 5
NGRAM_MIN_TOKEN_LENGTH = 4
HASH_DIGEST_BYTES = 8
SIGN_BIT_SHIFT = 63
IDENTIFIER_MATCH_BONUS = 0.35
EPSILON = 1e-12


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens.  Identifiers such as ``TX82931`` survive intact."""
    return WORD_PATTERN.findall(text.lower())


def split_sentences(text: str) -> list[str]:
    """Split into sentence-ish spans, preserving the original casing."""
    return [part.strip() for part in SENTENCE_PATTERN.split(text) if part.strip()]


def char_ngrams(token: str) -> list[str]:
    """Padded character n-grams, giving the hashed space sub-word robustness."""
    if len(token) < NGRAM_MIN_TOKEN_LENGTH:
        return []
    padded = f"^{token}$"
    grams: list[str] = []
    for size in range(MIN_CHAR_NGRAM, MAX_CHAR_NGRAM + 1):
        grams.extend(padded[i : i + size] for i in range(len(padded) - size + 1))
    return grams


def feature_weights(text: str) -> dict[str, float]:
    """Weighted, sublinear-tf feature map: word unigrams, bigrams and char n-grams."""
    tokens = tokenize(text)
    if not tokens:
        return {}
    counts: Counter[str] = Counter()
    base: dict[str, float] = {}
    for token in tokens:
        key = f"w:{token}"
        counts[key] += 1
        base[key] = UNIGRAM_WEIGHT
    for left, right in zip(tokens, tokens[1:], strict=False):
        key = f"b:{left}_{right}"
        counts[key] += 1
        base[key] = BIGRAM_WEIGHT
    for token in tokens:
        for gram in char_ngrams(token):
            key = f"c:{gram}"
            counts[key] += 1
            base[key] = NGRAM_WEIGHT
    return {key: base[key] * (1.0 + math.log(count)) for key, count in counts.items()}


def hash_bucket(feature: str, dimension: int) -> tuple[int, float]:
    """Map a feature to a (bucket, sign) pair.  The sign halves collision bias."""
    digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=HASH_DIGEST_BYTES).digest()
    value = int.from_bytes(digest, "big")
    sign = 1.0 if (value >> SIGN_BIT_SHIFT) & 1 else -1.0
    return value % dimension, sign


def hash_vector(text: str, dimension: int) -> list[float]:
    """Feature-hash ``text`` into ``dimension`` buckets and L2-normalise."""
    vector = [0.0] * dimension
    for feature, weight in feature_weights(text).items():
        bucket, sign = hash_bucket(feature, dimension)
        vector[bucket] += sign * weight
    return l2_normalise(vector)


def l2_normalise(vector: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm < EPSILON:
        return list(vector)
    return [value / norm for value in vector]


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError(f"dimension mismatch: {len(left)} vs {len(right)}")
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    norms = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return 0.0 if norms < EPSILON else dot / norms


def idf_weights(documents: Sequence[Sequence[str]]) -> dict[str, float]:
    """Smoothed inverse document frequency over the supplied corpus."""
    total = len(documents)
    if not total:
        return {}
    seen: Counter[str] = Counter()
    for tokens in documents:
        seen.update(set(tokens))
    return {token: math.log(1.0 + total / (1.0 + count)) for token, count in seen.items()}


def identifiers(tokens: Iterable[str]) -> set[str]:
    """Tokens that look like record identifiers (mixed letters and digits)."""
    return {token for token in tokens if IDENTIFIER_PATTERN.match(token)}


def find_identifiers(text: str) -> list[str]:
    """Identifier-shaped substrings copied verbatim, e.g. ``TX82931`` or ``ACC-5510``."""
    return IDENTIFIER_SPAN.findall(text)


def weighted_overlap(query_tokens: Sequence[str], doc_tokens: Sequence[str], idf: dict[str, float]) -> float:
    """IDF-weighted Jaccard in [0, 1] plus an exact-identifier bonus, clamped."""
    query_set, doc_set = set(query_tokens), set(doc_tokens)
    if not query_set or not doc_set:
        return 0.0
    intersection = sum(idf.get(token, 1.0) for token in query_set & doc_set)
    union = sum(idf.get(token, 1.0) for token in query_set | doc_set)
    score = intersection / union if union > EPSILON else 0.0
    shared_ids = identifiers(query_set & doc_set)
    return min(1.0, score + IDENTIFIER_MATCH_BONUS * len(shared_ids))
