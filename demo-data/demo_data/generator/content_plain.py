"""Lightweight corpus members: ADR, changelog, wiki page, exports and notes.

These carry the same entities as the heavyweight reports, in the terser
register those file types are actually written in, which is what makes
cross-document retrieval a real test rather than near-duplicate matching.
"""

from __future__ import annotations

from .content_support import TRANSACTION_HEADERS, failed_rows
from .rng import clock, iso_date
from .specs import (
    FORMAT_CSV,
    FORMAT_DOCX,
    FORMAT_HTML,
    FORMAT_MD,
    FORMAT_TXT,
    FORMAT_XLSX,
    DocumentSpec,
    section,
)
from .story import AUTH_SERVICE, FRAUD_SERVICE, GATEWAY_SERVICE, SESSION_DB
from .world import World


def adr(world: World) -> DocumentSpec:
    cast = world.cast
    return DocumentSpec(
        slug="adr-0007-revocation-list-cache",
        fmt=FORMAT_MD,
        title="ADR 0007: cache the token revocation list",
        occurred_at=cast.timeline.postmortem_at,
        tags=("adr", "decision"),
        entities=(AUTH_SERVICE, world.incident_id),
        key_finding="Accepted: cache the revocation list in-process with a 30 second TTL.",
        sections=(
            section("Status", "Accepted."),
            section(
                "Context",
                f"Release {cast.release_tag} of {AUTH_SERVICE} added a synchronous revocation-list lookup "
                f"per token validation. Under load this contends on {SESSION_DB} and pushes p99 past eight "
                f"seconds, which is what caused {world.incident_id}.",
            ),
            section(
                "Decision",
                "Cache the revocation list in-process with a 30 second TTL and refresh it asynchronously.",
            ),
            section(
                "Consequences",
                "A revoked token may be honoured for up to 30 seconds. The security review accepted that "
                "trade-off explicitly.",
            ),
        ),
    )


def changelog(world: World) -> DocumentSpec:
    cast, timeline = world.cast, world.cast.timeline
    return DocumentSpec(
        slug="platform-changelog",
        fmt=FORMAT_MD,
        title="Platform changelog",
        occurred_at=timeline.rollback_at,
        tags=("changelog", "timeline"),
        entities=(AUTH_SERVICE, FRAUD_SERVICE, world.incident_id),
        sections=(
            section(
                f"{iso_date(timeline.fraud_rule_deploy_at)}",
                f"{clock(timeline.fraud_rule_deploy_at)} UTC - {FRAUD_SERVICE}: velocity rule deployed to "
                "production.",
            ),
            section(
                f"{iso_date(timeline.deploy_at)}",
                f"{clock(timeline.deploy_at)} UTC - {AUTH_SERVICE}: release {cast.release_tag} deployed.",
                f"{clock(timeline.rollback_at)} UTC - {AUTH_SERVICE}: release {cast.release_tag} rolled back "
                f"under {world.incident_id}.",
            ),
            section(
                f"{iso_date(timeline.architecture_review_at)}",
                f"{clock(timeline.architecture_review_at)} UTC - {SESSION_DB}: sharding design circulated.",
            ),
        ),
    )


def wiki_page(world: World) -> DocumentSpec:
    cast = world.cast
    return DocumentSpec(
        slug="wiki-auth-service",
        fmt=FORMAT_HTML,
        title=f"Wiki: {AUTH_SERVICE}",
        occurred_at=cast.timeline.resolved_at,
        tags=("wiki", "reference"),
        entities=(AUTH_SERVICE, GATEWAY_SERVICE, SESSION_DB),
        sections=(
            section(
                "Overview",
                f"{AUTH_SERVICE} issues and validates session tokens for every customer-facing surface. "
                f"It stores sessions in {SESSION_DB}.",
            ),
            section(
                "Callers",
                f"{GATEWAY_SERVICE} calls token validation on the authorisation path and blocks on the "
                "answer, so authentication latency is payment latency.",
            ),
            section("Ownership", f"Owner: {cast.auth_engineer.name}. Escalation: {cast.commander.name}."),
            section(
                "Known failure modes",
                f"Token validation latency above two seconds exhausts the {GATEWAY_SERVICE} connection pool. "
                f"See {world.incident_id}.",
            ),
        ),
    )


def oncall_handover(world: World) -> DocumentSpec:
    cast, timeline = world.cast, world.cast.timeline
    return DocumentSpec(
        slug="oncall-handover-note",
        fmt=FORMAT_TXT,
        title="On-call handover note",
        occurred_at=timeline.standup_at,
        tags=("oncall", "note"),
        entities=(world.incident_id, world.transaction_id),
        sections=(
            section(
                "Handover",
                f"{world.incident_id} is resolved as of {clock(timeline.resolved_at)} UTC. "
                f"Watch authorisation success rate for another 24 hours.",
                f"If anyone asks, {world.variant('incident', 1)} is the same ticket under a different "
                "reference style.",
                f"Merchant ticket references {world.variant('transaction', 3)}; refund not required, no funds "
                "moved.",
                f"Next shift: {cast.reliability_engineer.name}.",
            ),
        ),
    )


def service_catalogue(world: World) -> DocumentSpec:
    assets = world.data.assets[:6]
    lines = tuple(
        f"{asset.asset_id} - {asset.name} ({asset.kind}, {asset.service}), owner {asset.owner}"
        for asset in assets
    )
    return DocumentSpec(
        slug="service-catalogue",
        fmt=FORMAT_MD,
        title="Service and asset catalogue",
        occurred_at=world.cast.timeline.deploy_at,
        tags=("catalogue", "assets"),
        entities=tuple(asset.asset_id for asset in assets),
        sections=(section("Registered assets", *lines),),
    )


def capacity_plan(world: World) -> DocumentSpec:
    cast = world.cast
    return DocumentSpec(
        slug="capacity-plan-payments",
        fmt=FORMAT_DOCX,
        title="Capacity plan: payments platform",
        occurred_at=cast.timeline.architecture_review_at,
        tags=("capacity", "planning"),
        entities=(GATEWAY_SERVICE, AUTH_SERVICE),
        sections=(
            section(
                "Current headroom",
                f"{GATEWAY_SERVICE} runs a 64-connection authorisation pool per edge node. At peak the pool "
                "sits at 48% utilisation, so a doubling of authentication latency saturates it.",
            ),
            section(
                "Plan",
                "Raise the pool to 96 connections only after the bounded wait ships; a larger pool without a "
                "bounded wait just delays saturation.",
            ),
        ),
    )


def security_review(world: World) -> DocumentSpec:
    cast = world.cast
    return DocumentSpec(
        slug="security-review-revocation-cache",
        fmt=FORMAT_DOCX,
        title="Security review: revocation list caching",
        occurred_at=cast.timeline.postmortem_at,
        tags=("security", "review"),
        entities=(AUTH_SERVICE,),
        sections=(
            section(
                "Scope",
                "Reviewed the proposal to cache the token revocation list in-process for 30 seconds.",
            ),
            section(
                "Finding",
                "Accepted with compensating control: high-risk revocations are pushed over the invalidation "
                "channel and bypass the cache.",
            ),
        ),
    )


def transaction_extract_xlsx(world: World) -> DocumentSpec:
    return DocumentSpec(
        slug="transaction-extract-failed",
        fmt=FORMAT_XLSX,
        title="Failed transaction extract",
        occurred_at=world.cast.timeline.resolved_at,
        tags=("export", "database"),
        entities=(world.transaction_id, world.customer_id),
        headers=TRANSACTION_HEADERS,
        rows=failed_rows(world),
    )


def failed_transactions_csv(world: World) -> DocumentSpec:
    return DocumentSpec(
        slug="failed-transactions-export",
        fmt=FORMAT_CSV,
        title="Failed transactions export",
        occurred_at=world.cast.timeline.resolved_at,
        tags=("export", "database"),
        entities=(world.transaction_id, world.customer_id),
        headers=TRANSACTION_HEADERS,
        rows=failed_rows(world),
    )
