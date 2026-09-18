"""Assembly of the full enterprise dataset from the cast and the id factory.

Failure counts are *computed* from the rows that were actually written rather
than asserted up front, so the aggregation ground truth ("customers with more
than five failed payments") is always exactly true of the emitted database.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Final

from .constants import (
    BASE_FAILURE_RATE,
    FAILED_PAYMENT_THRESHOLD,
    HIGH_FAILURE_CUSTOMERS,
    HIGH_FAILURE_MAX,
    HIGH_FAILURE_MIN,
)
from .records import (
    BALANCE_FAILURES,
    COLLATERAL_FAILURES,
    FAILED,
    FOCUS_AMOUNT_MAX,
    FOCUS_AMOUNT_MIN,
    FOCUS_AVAILABLE_BALANCE,
    FRAUD_FAILURES,
    INCIDENT_CATEGORIES,
    MEETING_CUSTOMERS,
    METHODS,
    NETWORK_FAILURES,
    NON_FAILED_STATUSES,
    SEVERITIES,
    CustomerRecord,
    EnterpriseData,
    IncidentRecord,
    RecordVolumes,
    TransactionRecord,
    build_assets,
    build_customers,
    volumes_for,
)
from .rng import TRANSACTION_WINDOW_DAYS, IdFactory, money, pick
from .story import (
    AUTH_SERVICE,
    BALANCE_FAILURE_REASON,
    FOCUS_FAILURE_REASON,
    FRAUD_FAILURE_REASON,
    FRAUD_SERVICE,
    GATEWAY_SERVICE,
    NETWORK_FAILURE_REASON,
    OTHER_FAILURE_REASONS,
    SERVICES,
    Cast,
)

#: Minutes either side of the focus failure that collateral failures land in.
COLLATERAL_WINDOW_MINUTES: Final[int] = 46
FILLER_INCIDENT_TITLES: Final[tuple[str, ...]] = (
    "Elevated 5xx rate on {service}",
    "{service} queue backlog above threshold",
    "Certificate rotation stalled for {service}",
    "Disk pressure on {service} nodes",
    "Slow queries degrade {service} read path",
    "Cache stampede after {service} restart",
    "Config drift detected in {service}",
    "Retry storm amplifies {service} load",
)
SETTLED_AMOUNT_MIN: Final[float] = 40.0
SETTLED_AMOUNT_MAX: Final[float] = 9_500.0


def _moment(rng: random.Random, cast: Cast) -> datetime:
    offset_minutes = rng.randint(0, TRANSACTION_WINDOW_DAYS * 24 * 60)
    return cast.timeline.deploy_at - timedelta(minutes=offset_minutes)


def _transaction(
    rng: random.Random,
    ids: IdFactory,
    cast: Cast,
    customer_id: str,
    *,
    created_at: datetime,
    status: str,
    failure_reason: str | None,
    incident_id: str | None,
    amount: float | None = None,
) -> TransactionRecord:
    value = amount if amount is not None else money(rng, SETTLED_AMOUNT_MIN, SETTLED_AMOUNT_MAX)
    return TransactionRecord(
        transaction_id=ids.transaction(),
        customer_id=customer_id,
        amount=value,
        currency=cast.currency,
        status=status,
        method=pick(rng, METHODS),
        failure_reason=failure_reason,
        created_at=created_at,
        updated_at=created_at + timedelta(seconds=rng.randint(3, 900)),
        incident_id=incident_id,
    )


def build_incidents(
    rng: random.Random, ids: IdFactory, cast: Cast, count: int
) -> tuple[tuple[IncidentRecord, ...], IncidentRecord, IncidentRecord, IncidentRecord]:
    """Return (all incidents, root cause, fraud rival, network rival)."""
    timeline = cast.timeline
    root = IncidentRecord(
        incident_id=ids.incident(),
        title=f"{AUTH_SERVICE} token validation timeout cascades into payment failures",
        severity="critical",
        status="resolved",
        category="availability",
        root_cause=cast.root_cause,
        service=AUTH_SERVICE,
        opened_at=timeline.incident_opened_at,
        resolved_at=timeline.resolved_at,
        approved=True,
        approved_by=cast.approver.name,
    )
    fraud = IncidentRecord(
        incident_id=ids.incident(),
        title=f"{FRAUD_SERVICE} rule FR-{rng.randint(100, 899)} blocks high-value card payments",
        severity="high",
        status="resolved",
        category="security",
        root_cause=f"an over-broad velocity rule shipped to {FRAUD_SERVICE} blocked legitimate card payments",
        service=FRAUD_SERVICE,
        opened_at=timeline.fraud_rule_deploy_at + timedelta(hours=2),
        resolved_at=timeline.fraud_rule_deploy_at + timedelta(hours=14),
        approved=True,
        approved_by=cast.approver.name,
    )
    network = IncidentRecord(
        incident_id=ids.incident(),
        title=f"Transit packet loss in {cast.region} degrades {GATEWAY_SERVICE} egress",
        severity="high",
        status="resolved",
        category="availability",
        root_cause=f"a transit provider link in {cast.region} dropped 9% of egress packets",
        service=GATEWAY_SERVICE,
        opened_at=timeline.network_event_at,
        resolved_at=timeline.network_event_at + timedelta(hours=3),
        approved=False,
        approved_by=None,
    )
    filler: list[IncidentRecord] = []
    for index in range(max(0, count - 3)):
        service = pick(rng, SERVICES)
        opened = timeline.deploy_at - timedelta(days=rng.randint(4, 300), minutes=rng.randint(0, 1400))
        filler.append(
            IncidentRecord(
                incident_id=ids.incident(),
                title=pick(rng, FILLER_INCIDENT_TITLES).format(service=service),
                severity=pick(rng, SEVERITIES),
                status="resolved" if rng.random() > 0.15 else "monitoring",
                category=pick(rng, INCIDENT_CATEGORIES),
                root_cause=f"routine {service} degradation, index {index}",
                service=service,
                opened_at=opened,
                resolved_at=opened + timedelta(hours=rng.randint(1, 30)),
                approved=rng.random() > 0.4,
                approved_by=pick(rng, [person.name for person in cast.people]),
            )
        )
    return (root, fraud, network, *filler), root, fraud, network


def _story_transactions(
    rng: random.Random,
    ids: IdFactory,
    cast: Cast,
    customers: tuple[CustomerRecord, ...],
    focus: CustomerRecord,
    root: IncidentRecord,
    fraud: IncidentRecord,
    network: IncidentRecord,
) -> tuple[list[TransactionRecord], TransactionRecord]:
    """The rows the narrative cites, including every rival explanation's trace."""
    timeline = cast.timeline
    rows: list[TransactionRecord] = []
    focus_transaction = _transaction(
        rng, ids, cast, focus.customer_id,
        created_at=timeline.transaction_at,
        status=FAILED,
        failure_reason=FOCUS_FAILURE_REASON,
        incident_id=root.incident_id,
        amount=money(rng, FOCUS_AMOUNT_MIN, FOCUS_AMOUNT_MAX),
    )
    rows.append(focus_transaction)

    others = [customer for customer in customers if customer.customer_id != focus.customer_id]
    for _ in range(COLLATERAL_FAILURES):
        drift = timedelta(minutes=rng.randint(-COLLATERAL_WINDOW_MINUTES, COLLATERAL_WINDOW_MINUTES))
        rows.append(
            _transaction(
                rng, ids, cast, pick(rng, others).customer_id,
                created_at=timeline.transaction_at + drift,
                status=FAILED,
                failure_reason=FOCUS_FAILURE_REASON,
                incident_id=root.incident_id,
            )
        )
    for _ in range(FRAUD_FAILURES):
        rows.append(
            _transaction(
                rng, ids, cast, pick(rng, others).customer_id,
                created_at=timeline.fraud_rule_deploy_at + timedelta(minutes=rng.randint(10, 700)),
                status=FAILED,
                failure_reason=FRAUD_FAILURE_REASON,
                incident_id=fraud.incident_id,
            )
        )
    for _ in range(NETWORK_FAILURES):
        rows.append(
            _transaction(
                rng, ids, cast, pick(rng, others).customer_id,
                created_at=timeline.network_event_at + timedelta(minutes=rng.randint(5, 170)),
                status=FAILED,
                failure_reason=NETWORK_FAILURE_REASON,
                incident_id=network.incident_id,
            )
        )
    for index in range(BALANCE_FAILURES):
        holder = focus.customer_id if index == 0 else pick(rng, others).customer_id
        rows.append(
            _transaction(
                rng, ids, cast, holder,
                created_at=timeline.deploy_at - timedelta(days=rng.randint(9, 80)),
                status=FAILED,
                failure_reason=BALANCE_FAILURE_REASON,
                incident_id=None,
            )
        )
    return rows, focus_transaction


def _boost_failures(
    rng: random.Random,
    ids: IdFactory,
    cast: Cast,
    rows: list[TransactionRecord],
    boosted: tuple[CustomerRecord, ...],
) -> None:
    """Top selected customers up to a deliberate, above-threshold failure count."""
    counts: dict[str, int] = {}
    for row in rows:
        if row.status == FAILED:
            counts[row.customer_id] = counts.get(row.customer_id, 0) + 1
    for customer in boosted:
        target = rng.randint(HIGH_FAILURE_MIN, HIGH_FAILURE_MAX)
        while counts.get(customer.customer_id, 0) < target:
            rows.append(
                _transaction(
                    rng, ids, cast, customer.customer_id,
                    created_at=_moment(rng, cast),
                    status=FAILED,
                    failure_reason=pick(rng, OTHER_FAILURE_REASONS),
                    incident_id=None,
                )
            )
            counts[customer.customer_id] = counts.get(customer.customer_id, 0) + 1


def build_enterprise(rng: random.Random, ids: IdFactory, cast: Cast, total_records: int) -> EnterpriseData:
    """Build every table, then read the pointers back out of the written rows."""
    volumes: RecordVolumes = volumes_for(total_records)
    customers = build_customers(rng, ids, cast, volumes.customers)
    assets, auth_asset, gateway_asset, database_assets = build_assets(rng, ids, cast, volumes.assets)
    incidents, root, fraud, network = build_incidents(rng, ids, cast, volumes.incidents)

    focus = customers[0]
    rows, focus_transaction = _story_transactions(
        rng, ids, cast, customers, focus, root, fraud, network
    )
    remaining = max(0, volumes.transactions - len(rows))
    for _ in range(remaining):
        customer = pick(rng, customers)
        failed = rng.random() < BASE_FAILURE_RATE
        rows.append(
            _transaction(
                rng, ids, cast, customer.customer_id,
                created_at=_moment(rng, cast),
                status=FAILED if failed else pick(rng, NON_FAILED_STATUSES),
                failure_reason=pick(rng, OTHER_FAILURE_REASONS) if failed else None,
                incident_id=None,
            )
        )
    boosted = tuple(customers[1 : 1 + HIGH_FAILURE_CUSTOMERS])
    _boost_failures(rng, ids, cast, rows, boosted)
    transactions = tuple(sorted(rows, key=lambda row: (row.created_at, row.transaction_id)))

    data = EnterpriseData(
        customers=customers,
        transactions=transactions,
        incidents=incidents,
        assets=assets,
        focus_customer=focus,
        focus_transaction=focus_transaction,
        root_incident=root,
        fraud_incident=fraud,
        network_incident=network,
        auth_asset=auth_asset,
        gateway_asset=gateway_asset,
        database_assets=database_assets,
        high_failure_customers=tuple(customer.customer_id for customer in boosted),
        meeting_customers=(),
        focus_available_balance=FOCUS_AVAILABLE_BALANCE,
    )
    return _with_meeting_customers(data, rng)


def _with_meeting_customers(data: EnterpriseData, rng: random.Random) -> EnterpriseData:
    """Name a few customers in the recorded meeting - only some exceed the threshold."""
    failures = data.failed_counts()
    above = [cid for cid in data.high_failure_customers if failures.get(cid, 0) > FAILED_PAYMENT_THRESHOLD]
    below = [
        customer.customer_id
        for customer in data.customers
        if failures.get(customer.customer_id, 0) <= FAILED_PAYMENT_THRESHOLD
        and customer.customer_id != data.focus_customer.customer_id
    ]
    chosen = list(above[: MEETING_CUSTOMERS - 1])
    if below:
        chosen.append(pick(rng, below))
    return EnterpriseData(
        customers=data.customers,
        transactions=data.transactions,
        incidents=data.incidents,
        assets=data.assets,
        focus_customer=data.focus_customer,
        focus_transaction=data.focus_transaction,
        root_incident=data.root_incident,
        fraud_incident=data.fraud_incident,
        network_incident=data.network_incident,
        auth_asset=data.auth_asset,
        gateway_asset=data.gateway_asset,
        database_assets=data.database_assets,
        high_failure_customers=data.high_failure_customers,
        meeting_customers=tuple(chosen),
        focus_available_balance=data.focus_available_balance,
    )
