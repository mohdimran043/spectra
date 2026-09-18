"""Supporting documents: the corroboration, the rivals and the exports.

Each rival explanation owns a document that makes it look plausible *and*
contains the detail that finally disproves it, so disproof search has real work
to do rather than a straw man.
"""

from __future__ import annotations

from typing import Final

from .records import FAILED
from .rng import clock, human_date, iso, iso_date
from .specs import (
    FORMAT_DOCX,
    FORMAT_PDF,
    FORMAT_PPTX,
    DocumentSpec,
    section,
)
from .story import AUTH_SERVICE, FRAUD_SERVICE, GATEWAY_SERVICE, SESSION_DB
from .world import World

EXTRACT_ROW_LIMIT: Final[int] = 60
TRANSACTION_HEADERS: Final[tuple[str, ...]] = (
    "transaction_id", "customer_id", "amount", "currency", "status", "failure_reason",
    "created_at", "incident_id",
)
#: Number of database nodes the architecture deck and diagram both describe.
SHARD_COUNT: Final[int] = 3


def failed_rows(world: World, limit: int = EXTRACT_ROW_LIMIT) -> tuple[tuple[str, ...], ...]:
    """Failed transactions, focus row first, for the tabular exports."""
    rows = [row for row in world.data.transactions if row.status == FAILED]
    rows.sort(key=lambda row: (row.created_at, row.transaction_id))
    focus = world.data.focus_transaction
    selected = [focus] + [row for row in rows if row.transaction_id != focus.transaction_id][: limit - 1]
    return tuple(
        (
            row.transaction_id, row.customer_id, f"{row.amount:.2f}", row.currency, row.status,
            row.failure_reason or "", iso(row.created_at), row.incident_id or "",
        )
        for row in selected
    )


def postmortem(world: World) -> DocumentSpec:
    cast, timeline = world.cast, world.cast.timeline
    return DocumentSpec(
        slug=f"postmortem-{world.incident_id.lower()}",
        fmt=FORMAT_DOCX,
        title=f"Post-mortem: {world.incident_id}",
        occurred_at=timeline.postmortem_at,
        tags=("postmortem", "root_cause"),
        entities=(world.incident_id, world.transaction_id, world.customer_id),
        key_finding=world.key_finding,
        sections=(
            section(
                "Summary",
                f"On {human_date(timeline.deploy_at)} a release of {AUTH_SERVICE} introduced an uncached "
                f"revocation-list lookup. {world.key_finding}",
            ),
            section(
                "What we got wrong first",
                f"For the first forty minutes the bridge worked the {FRAUD_SERVICE} rule theory, because a "
                f"velocity rule had shipped the evening before. That theory was wrong for {world.transaction_id}.",
            ),
            section(
                "Detection",
                f"Detection came from the merchant, not from us: {world.customer_name} raised "
                f"{world.variant('transaction', 2)} before our authorisation-rate alert fired.",
            ),
            section(
                "Actions",
                f"Cache the revocation list, bound the {GATEWAY_SERVICE} wait, add a canary. "
                f"Owners: {cast.auth_engineer.name}, {cast.payments_engineer.name}, "
                f"{cast.reliability_engineer.name}.",
            ),
        ),
    )


def fraud_rule_review(world: World) -> DocumentSpec:
    cast, timeline = world.cast, world.cast.timeline
    return DocumentSpec(
        slug=f"fraud-rule-review-{world.fraud_incident_id.lower()}",
        fmt=FORMAT_PDF,
        title=f"Fraud rule review for {world.fraud_incident_id}",
        occurred_at=timeline.fraud_rule_deploy_at,
        tags=("fraud", "rival_candidate explanation", "disproof"),
        entities=(world.fraud_incident_id, world.transaction_id),
        key_section=2,
        key_finding=f"{FRAUD_SERVICE} returned ALLOW for {world.transaction_id}.",
        sections=(
            section(
                f"Rule review {world.fraud_incident_id}",
                f"Author: {cast.fraud_analyst.name}. A velocity rule was deployed at "
                f"{clock(timeline.fraud_rule_deploy_at)} UTC on {human_date(timeline.fraud_rule_deploy_at)}.",
            ),
            section(
                "Impact of the rule",
                "Nine high-value card payments were blocked by the rule and later reprocessed manually. "
                "Those blocks carry the fraud_rule_block failure code.",
            ),
            section(
                "Decision log extract",
                f"Authorisation {world.transaction_id} was evaluated at "
                f"{clock(timeline.transaction_at)} UTC and the decision was ALLOW, score 0.11, "
                "no rule matched.",
                f"The rule therefore does not explain {world.variant('transaction', 1)}; the failure code "
                f"on that row is {world.data.focus_transaction.failure_reason}.",
            ),
            section("Remediation", "The rule was narrowed to card-present traffic and redeployed."),
        ),
    )


def network_incident_report(world: World) -> DocumentSpec:
    timeline = world.cast.timeline
    return DocumentSpec(
        slug=f"network-incident-{world.network_incident_id.lower()}",
        fmt=FORMAT_PDF,
        title=f"Network incident report {world.network_incident_id}",
        occurred_at=timeline.network_event_at,
        tags=("network", "rival_candidate explanation", "disproof"),
        entities=(world.network_incident_id,),
        key_section=1,
        key_finding="Packet loss was confined to a window three days before the payment incident.",
        sections=(
            section(
                f"Network incident {world.network_incident_id}",
                f"Transit packet loss of 9% in {world.cast.region} on "
                f"{human_date(timeline.network_event_at)} between "
                f"{clock(timeline.network_event_at)} and {clock(timeline.network_event_at)} UTC plus three hours.",
            ),
            section(
                "Window and counters",
                f"Interface counters were clean from {iso_date(timeline.network_event_at)} 23:00 UTC onwards, "
                f"including the whole of {iso_date(timeline.deploy_at)}.",
                "No packet loss is recorded for the payment incident window.",
            ),
            section("Provider response", "The transit provider replaced an optic and closed the ticket."),
        ),
    )


def customer_statement(world: World) -> DocumentSpec:
    customer = world.data.focus_customer
    transaction = world.data.focus_transaction
    return DocumentSpec(
        slug=f"customer-statement-{customer.customer_id.lower()}",
        fmt=FORMAT_PDF,
        title=f"Account statement for {customer.name} ({customer.customer_id})",
        occurred_at=transaction.created_at,
        tags=("statement", "rival_candidate explanation", "disproof"),
        entities=(customer.customer_id, transaction.transaction_id),
        key_section=1,
        key_finding=f"Available balance {world.data.focus_available_balance:,.2f} {transaction.currency}.",
        sections=(
            section(
                f"Statement for {world.variant('customer', 0)}",
                f"Account holder: {customer.name}. Segment: {customer.segment}. Country: {customer.country}.",
            ),
            section(
                "Balance at the time of the declined authorisation",
                f"Available balance on {human_date(transaction.created_at)} was "
                f"{world.data.focus_available_balance:,.2f} {transaction.currency}.",
                f"The declined authorisation {world.variant('transaction', 0)} was for {world.amount_text}, "
                "well within the available balance, so the decline was not a funding decline.",
            ),
            section(
                "Prior declines",
                f"An earlier attempt from {world.variant('customer', 1)} was declined for insufficient funds. "
                "That attempt is unrelated to the incident and predates it by weeks.",
            ),
        ),
    )


def meeting_minutes(world: World) -> DocumentSpec:
    cast, timeline = world.cast, world.cast.timeline
    named = ", ".join(world.data.meeting_customers)
    return DocumentSpec(
        slug=f"meeting-minutes-{iso_date(timeline.postmortem_at)}",
        fmt=FORMAT_DOCX,
        title=f"Engineering review minutes, {human_date(timeline.postmortem_at)}",
        occurred_at=timeline.postmortem_at,
        tags=("meeting", "minutes"),
        entities=tuple(world.data.meeting_customers) + (world.incident_id,),
        sections=(
            section(
                "Attendees",
                ", ".join(f"{person.name} ({person.role})" for person in cast.people),
            ),
            section(
                "Payment failures review",
                f"The review covered {world.incident_id} and the merchants that raised tickets: {named}.",
                f"{cast.payments_engineer.name} asked which of those merchants had more than five failed "
                "payments in the last quarter; the answer was to be pulled from the payments database.",
            ),
            section(
                "Fraud rule discussion",
                f"{cast.fraud_analyst.name} confirmed the velocity rule blocked nine payments but not "
                f"{world.variant('transaction', 1)}.",
            ),
            section(
                "Architecture item",
                f"{cast.data_architect.name} tabled the {SESSION_DB} sharding change for the architecture "
                "review later in the week.",
            ),
        ),
    )


def architecture_deck(world: World) -> DocumentSpec:
    cast, timeline = world.cast, world.cast.timeline
    return DocumentSpec(
        slug="architecture-review-session-sharding",
        fmt=FORMAT_PPTX,
        title=f"Architecture review: sharding {SESSION_DB}",
        occurred_at=timeline.architecture_review_at,
        tags=("architecture", "sharding"),
        entities=(SESSION_DB, AUTH_SERVICE),
        key_finding=f"Split {SESSION_DB} into {SHARD_COUNT} shards keyed by tenant.",
        sections=(
            section("Why we are here", f"{AUTH_SERVICE} contends on a single {SESSION_DB} primary."),
            section(
                "Proposal",
                f"Shard {SESSION_DB} into {SHARD_COUNT} nodes keyed by tenant, with a read replica per shard.",
            ),
            section(
                "Risk",
                "Cross-shard session lookups add a hop; the revocation list must be cached regardless.",
            ),
            section("Decision", f"Approved in principle by {cast.data_architect.name}; ADR to follow."),
        ),
    )


def sharding_design(world: World) -> DocumentSpec:
    return DocumentSpec(
        slug="design-session-db-sharding",
        fmt=FORMAT_PDF,
        title=f"Design document: sharding {SESSION_DB}",
        occurred_at=world.cast.timeline.architecture_review_at,
        tags=("architecture", "design", "sharding"),
        entities=(SESSION_DB,),
        key_section=3,
        key_finding=f"The target topology has exactly {SHARD_COUNT} database nodes.",
        sections=(
            section("Context", f"{SESSION_DB} is a single primary with one replica and no horizontal split."),
            section("Goals", "Remove the write hotspot and bound token validation latency."),
            section("Alternatives", "Vertical scaling, caching only, or sharding. Caching alone was rejected."),
            section(
                "Target topology",
                f"The target topology has exactly {SHARD_COUNT} database nodes: one shard primary per tenant "
                "band, each fronted by the authentication service and the ledger reader.",
            ),
            section("Migration", "Dual-write, backfill, cut over one tenant band at a time."),
        ),
    )
