"""Embedded lexical store: a real BM25 ranker over an inverted index in SQLite.

Semantic vectors miss exact identifiers, so lexical retrieval is not optional -
it is half of SPECTRA's hybrid recall.  This backend keeps a genuine inverted
index (postings + document frequencies + corpus totals) and scores with Okapi
BM25 (k1=1.5, b=0.75), so a laptop install ranks identically in shape to the
OpenSearch profile rather than falling back to substring matching.
"""

from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from spectra_config import Settings
from spectra_config.logging import get_logger

from .. import text_analysis
from ..filters import FilterCondition, compile_filters, matches_payload
from ..interfaces import LexicalDocument, LexicalMatch, LexicalStore
from ..sqlite_support import SqliteDatabase, fetch_all, fetch_one, safe_identifier, scalar

log = get_logger(__name__)

LEXICAL_DB_FILENAME = "lexical.db"
BM25_K1 = 1.5
BM25_B = 0.75
# The tokeniser only ever emits ``\w+`` runs, so a sentinel containing "*" can
# never collide with a real term from a document.
TOTALS_TERM = "*corpus*"
TITLE_TERM_WEIGHT = 2
DEFAULT_SEARCH_LIMIT = 50
DEFAULT_AVG_LENGTH = 1.0


@dataclass(frozen=True)
class _IndexTables:
    docs: str
    postings: str
    stats: str


@dataclass(frozen=True)
class _Corpus:
    documents: int
    average_length: float


class EmbeddedLexicalStore(LexicalStore):
    """BM25 over a SQLite-persisted inverted index."""

    backend_name = "embedded"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._db = SqliteDatabase(settings.runtime_dir / LEXICAL_DB_FILENAME)

    # -- lifecycle --------------------------------------------------------
    async def ensure_index(self, name: str) -> None:
        tables = _tables_for(name)

        def _create(connection: sqlite3.Connection) -> None:
            connection.execute(
                f"CREATE TABLE IF NOT EXISTS {tables.docs} (id TEXT PRIMARY KEY, title TEXT NOT NULL, "
                "text TEXT NOT NULL, payload TEXT NOT NULL, length INTEGER NOT NULL)"
            )
            connection.execute(
                f"CREATE TABLE IF NOT EXISTS {tables.postings} (term TEXT NOT NULL, doc_id TEXT NOT NULL, "
                "tf INTEGER NOT NULL, PRIMARY KEY(term, doc_id))"
            )
            connection.execute(f"CREATE INDEX IF NOT EXISTS {tables.postings}_doc ON {tables.postings}(doc_id)")
            connection.execute(
                f"CREATE TABLE IF NOT EXISTS {tables.stats} (term TEXT PRIMARY KEY, df INTEGER NOT NULL, "
                "total_length INTEGER NOT NULL DEFAULT 0)"
            )
            connection.execute(
                f"INSERT INTO {tables.stats}(term, df, total_length) VALUES(?, 0, 0) "
                "ON CONFLICT(term) DO NOTHING",
                (TOTALS_TERM,),
            )

        await self._db.run(_create)
        log.debug("lexical.index_ready", backend=self.backend_name, index=name)

    async def close(self) -> None:
        await self._db.close()

    # -- writes -----------------------------------------------------------
    async def index(self, index: str, documents: Sequence[LexicalDocument]) -> int:
        tables = _tables_for(index)
        if not documents:
            return 0
        analysed = [(document, _analyse(document)) for document in documents]

        def _write(connection: sqlite3.Connection) -> int:
            for document, frequencies in analysed:
                _retract(connection, tables, document.id)
                _store_document(connection, tables, document, frequencies)
            return len(analysed)

        written = await self._db.run(_write)
        log.debug("lexical.indexed", backend=self.backend_name, index=index, count=written)
        return written

    async def delete(self, index: str, ids: Sequence[str]) -> int:
        tables = _tables_for(index)
        if not ids:
            return 0

        def _delete(connection: sqlite3.Connection) -> int:
            return sum(1 for doc_id in ids if _retract(connection, tables, doc_id))

        removed = await self._db.run(_delete)
        log.debug("lexical.deleted", backend=self.backend_name, index=index, count=removed)
        return removed

    # -- reads ------------------------------------------------------------
    async def search(
        self,
        index: str,
        query: str,
        limit: int = DEFAULT_SEARCH_LIMIT,
        filters: dict[str, Any] | None = None,
    ) -> list[LexicalMatch]:
        tables = _tables_for(index)
        conditions = compile_filters(filters)
        terms = tuple(dict.fromkeys(text_analysis.tokenise(query)))
        if not terms or limit <= 0:
            return []

        def _search(connection: sqlite3.Connection) -> list[LexicalMatch]:
            corpus = _read_corpus(connection, tables)
            if corpus.documents == 0:
                return []
            scored = _score(connection, tables, terms, corpus, conditions)
            top = sorted(scored.items(), key=lambda item: (-item[1], item[0]))[:limit]
            return [_hydrate(connection, tables, doc_id, score, terms) for doc_id, score in top]

        return await self._db.run(_search)

    async def count(self, index: str) -> int:
        tables = _tables_for(index)

        def _count(connection: sqlite3.Connection) -> int:
            return scalar(connection, f"SELECT COUNT(*) FROM {tables.docs}")

        return await self._db.run(_count)

    async def health(self) -> dict[str, Any]:
        try:
            size = await self._db.file_size_bytes()
        except OSError as exc:
            log.warning("lexical.health_failed", backend=self.backend_name, error=str(exc))
            return {"backend": self.backend_name, "status": "error", "detail": str(exc)}
        return {
            "backend": self.backend_name,
            "status": "ok",
            "path": str(self._db.path),
            "size_bytes": size,
        }


# -- analysis -------------------------------------------------------------
def _analyse(document: LexicalDocument) -> dict[str, int]:
    """Term frequencies for one document, with the title weighted up."""
    counts: dict[str, int] = {}
    for term in text_analysis.tokenise(document.title or ""):
        counts[term] = counts.get(term, 0) + TITLE_TERM_WEIGHT
    for term in text_analysis.tokenise(document.text or ""):
        counts[term] = counts.get(term, 0) + 1
    return counts


def _tables_for(index: str) -> _IndexTables:
    name = safe_identifier(index)
    return _IndexTables(docs=f"{name}_docs", postings=f"{name}_postings", stats=f"{name}_stats")


# -- write helpers --------------------------------------------------------
def _retract(connection: sqlite3.Connection, tables: _IndexTables, doc_id: str) -> bool:
    """Remove a document and roll back its contribution to the corpus stats."""
    row = fetch_one(connection, f"SELECT length FROM {tables.docs} WHERE id = ?", (doc_id,))
    if row is None:
        return False
    posting_rows = fetch_all(
        connection, f"SELECT term FROM {tables.postings} WHERE doc_id = ?", (doc_id,)
    )
    terms = [r["term"] for r in posting_rows]
    connection.executemany(
        f"UPDATE {tables.stats} SET df = df - 1 WHERE term = ?", [(term,) for term in terms]
    )
    connection.execute(f"DELETE FROM {tables.stats} WHERE df <= 0 AND term != ?", (TOTALS_TERM,))
    connection.execute(f"DELETE FROM {tables.postings} WHERE doc_id = ?", (doc_id,))
    connection.execute(f"DELETE FROM {tables.docs} WHERE id = ?", (doc_id,))
    connection.execute(
        f"UPDATE {tables.stats} SET df = df - 1, total_length = total_length - ? WHERE term = ?",
        (int(row["length"]), TOTALS_TERM),
    )
    return True


def _store_document(
    connection: sqlite3.Connection,
    tables: _IndexTables,
    document: LexicalDocument,
    frequencies: dict[str, int],
) -> None:
    length = sum(frequencies.values())
    connection.execute(
        f"INSERT INTO {tables.docs}(id, title, text, payload, length) VALUES(?, ?, ?, ?, ?)",
        (document.id, document.title or "", document.text or "", json.dumps(document.payload or {}), length),
    )
    connection.executemany(
        f"INSERT INTO {tables.postings}(term, doc_id, tf) VALUES(?, ?, ?)",
        [(term, document.id, tf) for term, tf in frequencies.items()],
    )
    connection.executemany(
        f"INSERT INTO {tables.stats}(term, df, total_length) VALUES(?, 1, 0) "
        "ON CONFLICT(term) DO UPDATE SET df = df + 1",
        [(term,) for term in frequencies],
    )
    connection.execute(
        f"UPDATE {tables.stats} SET df = df + 1, total_length = total_length + ? WHERE term = ?",
        (length, TOTALS_TERM),
    )


# -- read helpers ---------------------------------------------------------
def _read_corpus(connection: sqlite3.Connection, tables: _IndexTables) -> _Corpus:
    row = fetch_one(connection, f"SELECT df, total_length FROM {tables.stats} WHERE term = ?", (TOTALS_TERM,))
    if row is None or int(row["df"]) <= 0:
        return _Corpus(documents=0, average_length=DEFAULT_AVG_LENGTH)
    documents = int(row["df"])
    total = int(row["total_length"])
    return _Corpus(documents=documents, average_length=max(total / documents, DEFAULT_AVG_LENGTH))


def _score(
    connection: sqlite3.Connection,
    tables: _IndexTables,
    terms: Sequence[str],
    corpus: _Corpus,
    conditions: Sequence[FilterCondition],
) -> dict[str, float]:
    placeholders = ",".join("?" for _ in terms)
    rows = fetch_all(
        connection,
        f"SELECT p.term AS term, p.doc_id AS doc_id, p.tf AS tf, d.length AS length, d.payload AS payload "
        f"FROM {tables.postings} p JOIN {tables.docs} d ON d.id = p.doc_id "
        f"WHERE p.term IN ({placeholders})",
        tuple(terms),
    )
    idf = _document_frequencies(connection, tables, terms, corpus)
    scores: dict[str, float] = {}
    allowed: dict[str, bool] = {}
    for row in rows:
        doc_id = row["doc_id"]
        if doc_id not in allowed:
            allowed[doc_id] = matches_payload(json.loads(row["payload"]), conditions)
        if not allowed[doc_id]:
            continue
        scores[doc_id] = scores.get(doc_id, 0.0) + _bm25(
            tf=int(row["tf"]), length=int(row["length"]), idf=idf[row["term"]], average=corpus.average_length
        )
    return scores


def _document_frequencies(
    connection: sqlite3.Connection, tables: _IndexTables, terms: Sequence[str], corpus: _Corpus
) -> dict[str, float]:
    placeholders = ",".join("?" for _ in terms)
    rows = fetch_all(
        connection, f"SELECT term, df FROM {tables.stats} WHERE term IN ({placeholders})", tuple(terms)
    )
    known = {row["term"]: int(row["df"]) for row in rows}
    return {term: _idf(known.get(term, 0), corpus.documents) for term in terms}


def _idf(df: int, documents: int) -> float:
    return math.log(1.0 + (documents - df + 0.5) / (df + 0.5))


def _bm25(tf: int, length: int, idf: float, average: float) -> float:
    denominator = tf + BM25_K1 * (1.0 - BM25_B + BM25_B * (length / average))
    if denominator <= 0:
        return 0.0
    return idf * (tf * (BM25_K1 + 1.0)) / denominator


def _hydrate(
    connection: sqlite3.Connection,
    tables: _IndexTables,
    doc_id: str,
    score: float,
    terms: Iterable[str],
) -> LexicalMatch:
    row = fetch_one(connection, f"SELECT title, text, payload FROM {tables.docs} WHERE id = ?", (doc_id,))
    if row is None:
        return LexicalMatch(id=doc_id, score=round(score, 6), payload={}, highlights=[])
    body = f"{row['title']}\n{row['text']}" if row["title"] else row["text"]
    return LexicalMatch(
        id=doc_id,
        score=round(score, 6),
        payload=json.loads(row["payload"]),
        highlights=text_analysis.highlights(body, terms),
    )
