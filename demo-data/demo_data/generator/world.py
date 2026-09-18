"""The generated world: seed, scale, cast, records and the surface forms.

Every writer downstream reads this object.  In particular the *variant surface
forms* live here, so a document, a transcript and an OCR overlay all spell the
same entity in the several ways a real corpus would.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from .constants import ScaleProfile
from .enterprise import build_enterprise
from .records import EnterpriseData
from .rng import IdFactory, digits_of, make_rng
from .story import Cast, build_cast

#: Streams are named so adding a stage never shifts an earlier stage's draws.
STREAM_CAST: Final[str] = "cast"
STREAM_IDS: Final[str] = "ids"
STREAM_RECORDS: Final[str] = "records"
STREAM_DOCUMENTS: Final[str] = "documents"
STREAM_IMAGES: Final[str] = "images"
STREAM_AUDIO: Final[str] = "audio"
STREAM_VIDEO: Final[str] = "video"
STREAM_FILLER: Final[str] = "filler"


@dataclass(frozen=True)
class World:
    """Everything the writers need, fully determined by ``seed`` and ``scale``."""

    seed: int
    scale: ScaleProfile
    cast: Cast
    data: EnterpriseData
    ids: IdFactory

    # -- primary identifiers ---------------------------------------------
    @property
    def transaction_id(self) -> str:
        return self.data.focus_transaction.transaction_id

    @property
    def customer_id(self) -> str:
        return self.data.focus_customer.customer_id

    @property
    def incident_id(self) -> str:
        return self.data.root_incident.incident_id

    @property
    def fraud_incident_id(self) -> str:
        return self.data.fraud_incident.incident_id

    @property
    def network_incident_id(self) -> str:
        return self.data.network_incident.incident_id

    @property
    def customer_name(self) -> str:
        return self.data.focus_customer.name

    # -- variant surface forms -------------------------------------------
    @property
    def transaction_variants(self) -> tuple[str, ...]:
        digits = digits_of(self.transaction_id)
        return (
            self.transaction_id,
            f"Txn {digits}",
            f"Transaction #{digits}",
            f"payment reference {digits}",
        )

    @property
    def customer_variants(self) -> tuple[str, ...]:
        digits = digits_of(self.customer_id)
        return (self.customer_id, f"Customer {digits}", f"client {digits}")

    @property
    def incident_variants(self) -> tuple[str, ...]:
        digits = digits_of(self.incident_id)
        return (self.incident_id, f"Incident #{digits}", f"ticket {digits}")

    def variant(self, family: str, index: int) -> str:
        """Pick one surface form by position - writers rotate through these."""
        table = {
            "transaction": self.transaction_variants,
            "customer": self.customer_variants,
            "incident": self.incident_variants,
        }
        options = table[family]
        return options[index % len(options)]

    @property
    def amount_text(self) -> str:
        transaction = self.data.focus_transaction
        return f"{transaction.amount:,.2f} {transaction.currency}"

    @property
    def key_finding(self) -> str:
        """The single sentence the late incident-report page exists to carry."""
        return (
            f"Root cause confirmed: {self.cast.root_cause}. "
            f"{self.transaction_id} was declined with {self.data.focus_transaction.failure_reason} "
            f"because the authorisation call never returned, not because of fraud scoring, "
            f"network loss or an insufficient balance."
        )


def build_world(seed: int, scale: ScaleProfile) -> World:
    """Deterministically construct the whole world from a seed and a tier."""
    cast = build_cast(make_rng(seed, STREAM_CAST))
    ids = IdFactory.create(make_rng(seed, STREAM_IDS))
    data = build_enterprise(make_rng(seed, STREAM_RECORDS), ids, cast, scale.database_records)
    return World(seed=seed, scale=scale, cast=cast, data=data, ids=ids)
