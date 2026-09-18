"""The enterprise business dataset: customers, transactions, incidents, assets.

These records are the ground truth every other modality is written against: a
PDF that names a transaction names one that exists here, with the amount and
the failure code that this table holds.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from .constants import (
    STORY_ASSETS,
    STORY_CUSTOMERS,
    STORY_INCIDENTS,
    STORY_TRANSACTIONS,
)
from .rng import IdFactory, pick
from .story import (
    AUTH_SERVICE,
    FRAUD_SERVICE,
    GATEWAY_SERVICE,
    LEDGER_SERVICE,
    NOTIFICATION_SERVICE,
    SESSION_DB,
    Cast,
)

SEGMENTS: Final[tuple[str, ...]] = ("enterprise", "mid_market", "smb", "public_sector")
COUNTRIES: Final[tuple[str, ...]] = ("DE", "NL", "SE", "FR", "IE", "ES", "PL", "GB", "IT", "PT")
CUSTOMER_STATUSES: Final[tuple[str, ...]] = ("active", "active", "active", "suspended", "closed")
COMPANY_SUFFIXES: Final[tuple[str, ...]] = ("GmbH", "BV", "AB", "SAS", "Ltd", "Holdings", "Group", "NV")
COMPANY_STEMS: Final[tuple[str, ...]] = (
    "Northgate", "Vantis", "Clearharbor", "Merridian", "Kestrel", "Blauwater", "Solstice",
    "Ironvale", "Larkfield", "Pontus", "Sableton", "Alderkraft", "Verdemar", "Quillon",
)
METHODS: Final[tuple[str, ...]] = ("card", "sepa_direct_debit", "wire", "wallet")
SETTLED: Final[str] = "settled"
FAILED: Final[str] = "failed"
PENDING: Final[str] = "pending"
REFUNDED: Final[str] = "refunded"
NON_FAILED_STATUSES: Final[tuple[str, ...]] = (SETTLED, SETTLED, SETTLED, PENDING, REFUNDED)

SEVERITIES: Final[tuple[str, ...]] = ("critical", "high", "medium", "low")
INCIDENT_CATEGORIES: Final[tuple[str, ...]] = ("availability", "latency", "data_quality", "security", "capacity")
ASSET_KINDS: Final[tuple[str, ...]] = ("service", "database", "queue", "gateway", "cache", "job")
ENVIRONMENTS: Final[tuple[str, ...]] = ("production", "staging", "production", "production")

#: How many *other* transactions fail inside the incident window with the same
#: upstream code, so the incident linkage is a real aggregate and not one row.
COLLATERAL_FAILURES: Final[int] = 12
FRAUD_FAILURES: Final[int] = 9
NETWORK_FAILURES: Final[int] = 7
BALANCE_FAILURES: Final[int] = 8
#: Customers named out loud in the engineering meeting recording.
MEETING_CUSTOMERS: Final[int] = 3
#: The focus customer's balance, used to disprove "insufficient funds".
FOCUS_AVAILABLE_BALANCE: Final[float] = 18_400.00
FOCUS_AMOUNT_MIN: Final[float] = 3_800.00
FOCUS_AMOUNT_MAX: Final[float] = 5_400.00


@dataclass(frozen=True)
class CustomerRecord:
    customer_id: str
    name: str
    email: str
    segment: str
    country: str
    risk_score: float
    created_at: datetime
    status: str


@dataclass(frozen=True)
class TransactionRecord:
    transaction_id: str
    customer_id: str
    amount: float
    currency: str
    status: str
    method: str
    failure_reason: str | None
    created_at: datetime
    updated_at: datetime
    incident_id: str | None


@dataclass(frozen=True)
class IncidentRecord:
    incident_id: str
    title: str
    severity: str
    status: str
    category: str
    root_cause: str
    service: str
    opened_at: datetime
    resolved_at: datetime | None
    approved: bool
    approved_by: str | None


@dataclass(frozen=True)
class AssetRecord:
    asset_id: str
    name: str
    kind: str
    owner: str
    environment: str
    service: str
    status: str
    created_at: datetime


@dataclass(frozen=True)
class EnterpriseData:
    """All four tables plus the pointers the narrative turns on."""

    customers: tuple[CustomerRecord, ...]
    transactions: tuple[TransactionRecord, ...]
    incidents: tuple[IncidentRecord, ...]
    assets: tuple[AssetRecord, ...]
    focus_customer: CustomerRecord
    focus_transaction: TransactionRecord
    root_incident: IncidentRecord
    fraud_incident: IncidentRecord
    network_incident: IncidentRecord
    auth_asset: AssetRecord
    gateway_asset: AssetRecord
    database_assets: tuple[AssetRecord, ...]
    high_failure_customers: tuple[str, ...]
    meeting_customers: tuple[str, ...]
    focus_available_balance: float

    @property
    def counts(self) -> dict[str, int]:
        return {
            "customers": len(self.customers),
            "transactions": len(self.transactions),
            "incidents": len(self.incidents),
            "assets": len(self.assets),
        }

    def failed_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for transaction in self.transactions:
            if transaction.status == FAILED:
                counts[transaction.customer_id] = counts.get(transaction.customer_id, 0) + 1
        return counts


@dataclass(frozen=True)
class RecordVolumes:
    customers: int
    transactions: int
    incidents: int
    assets: int


#: Record budget of the narrative tier: below this, the story volumes are used verbatim.
STORY_TOTAL: Final[int] = STORY_CUSTOMERS + STORY_TRANSACTIONS + STORY_INCIDENTS + STORY_ASSETS


def volumes_for(total_records: int) -> RecordVolumes:
    """Split a record budget across the four tables, never below story scale."""
    if total_records <= STORY_TOTAL:
        return RecordVolumes(
            customers=STORY_CUSTOMERS,
            transactions=STORY_TRANSACTIONS,
            incidents=STORY_INCIDENTS,
            assets=STORY_ASSETS,
        )
    customers = max(STORY_CUSTOMERS, total_records // 8)
    incidents = max(STORY_INCIDENTS, total_records // 500)
    assets = max(STORY_ASSETS, total_records // 800)
    transactions = max(STORY_TRANSACTIONS, total_records - customers - incidents - assets)
    return RecordVolumes(customers=customers, transactions=transactions, incidents=incidents, assets=assets)


def _customer(rng: random.Random, ids: IdFactory, cast: Cast, index: int) -> CustomerRecord:
    stem = pick(rng, COMPANY_STEMS)
    suffix = pick(rng, COMPANY_SUFFIXES)
    name = f"{stem} {suffix}"
    created = cast.timeline.deploy_at - timedelta(days=rng.randint(60, 2_400))
    return CustomerRecord(
        customer_id=ids.customer(),
        name=name,
        email=f"ops{index}@{stem.lower()}.example",
        segment=pick(rng, SEGMENTS),
        country=pick(rng, COUNTRIES),
        risk_score=round(rng.uniform(0.02, 0.94), 3),
        created_at=created,
        status=pick(rng, CUSTOMER_STATUSES),
    )


def build_customers(rng: random.Random, ids: IdFactory, cast: Cast, count: int) -> tuple[CustomerRecord, ...]:
    return tuple(_customer(rng, ids, cast, index) for index in range(count))


def build_assets(
    rng: random.Random, ids: IdFactory, cast: Cast, count: int
) -> tuple[tuple[AssetRecord, ...], AssetRecord, AssetRecord, tuple[AssetRecord, ...]]:
    """Return (all assets, auth asset, gateway asset, the three database nodes)."""
    owners = [person.name for person in cast.people]
    named: list[AssetRecord] = []
    base_created = cast.timeline.deploy_at - timedelta(days=420)

    def make(name: str, kind: str, service: str, offset_days: int) -> AssetRecord:
        return AssetRecord(
            asset_id=ids.asset(),
            name=name,
            kind=kind,
            owner=pick(rng, owners),
            environment="production",
            service=service,
            status="operational",
            created_at=base_created + timedelta(days=offset_days),
        )

    auth_asset = make(f"{AUTH_SERVICE}-node-01", "service", AUTH_SERVICE, 0)
    gateway_asset = make(f"{GATEWAY_SERVICE}-edge-01", "gateway", GATEWAY_SERVICE, 11)
    database_assets = (
        make(f"{SESSION_DB}-primary", "database", SESSION_DB, 22),
        make(f"{SESSION_DB}-replica", "database", SESSION_DB, 23),
        make("ledger-db-analytics", "database", LEDGER_SERVICE, 24),
    )
    named.extend([auth_asset, gateway_asset, *database_assets])
    named.append(make(f"{FRAUD_SERVICE}-scoring-01", "service", FRAUD_SERVICE, 31))
    named.append(make(f"{NOTIFICATION_SERVICE}-worker-01", "job", NOTIFICATION_SERVICE, 37))

    services = (AUTH_SERVICE, GATEWAY_SERVICE, FRAUD_SERVICE, LEDGER_SERVICE, NOTIFICATION_SERVICE)
    filler = []
    for index in range(max(0, count - len(named))):
        service = pick(rng, services)
        filler.append(
            AssetRecord(
                asset_id=ids.asset(),
                name=f"{service}-{pick(rng, ASSET_KINDS)}-{index + 2:02d}",
                kind=pick(rng, ASSET_KINDS),
                owner=pick(rng, owners),
                environment=pick(rng, ENVIRONMENTS),
                service=service,
                status="operational" if rng.random() > 0.12 else "degraded",
                created_at=base_created + timedelta(days=rng.randint(0, 400)),
            )
        )
    return tuple(named + filler), auth_asset, gateway_asset, database_assets
