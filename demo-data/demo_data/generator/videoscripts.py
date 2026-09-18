"""Slide-and-narration scripts for the generated videos.

A script is pure data: slides with the lines to draw and the turns spoken over
them, plus which scene answers which benchmark question.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from .rng import clock, iso, make_rng, pick
from .story import AUTH_SERVICE, FRAUD_SERVICE, GATEWAY_SERVICE, SESSION_DB
from .world import STREAM_VIDEO, World

#: Cue names used as answer keys in the manifest.
CUE_TRANSACTION_ON_SCREEN: Final[str] = "transaction_on_screen"
CUE_ROOT_CAUSE: Final[str] = "root_cause"
CUE_ARCHITECTURE_CHANGE: Final[str] = "architecture_change"
CUE_CUSTOMERS_NAMED: Final[str] = "customers_named"


@dataclass(frozen=True)
class VideoScene:
    title: str
    lines: tuple[str, ...]
    turns: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class VideoScript:
    slug: str
    title: str
    scenes: tuple[VideoScene, ...]
    answer_scenes: dict[str, int]
    entities: tuple[str, ...]
    tags: tuple[str, ...]


def _incident_walkthrough(world: World) -> VideoScript:
    cast, timeline = world.cast, world.cast.timeline
    transaction = world.data.focus_transaction
    return VideoScript(
        slug=f"incident-walkthrough-{world.incident_id.lower()}",
        title=f"Incident walkthrough {world.incident_id}",
        entities=(world.incident_id, world.transaction_id, world.customer_id),
        tags=("incident", "walkthrough", "primary"),
        answer_scenes={CUE_TRANSACTION_ON_SCREEN: 1, CUE_ROOT_CAUSE: 3},
        scenes=(
            VideoScene(
                title=f"Incident {world.incident_id}",
                lines=(
                    f"Service: {AUTH_SERVICE}",
                    f"Severity: {world.data.root_incident.severity}",
                    f"- Opened {iso(timeline.incident_opened_at)}",
                ),
                turns=((cast.commander.speaker,
                        f"This is the walkthrough for {world.incident_id}, a critical availability "
                        f"incident on {AUTH_SERVICE}."),),
            ),
            VideoScene(
                title="The failing payment",
                lines=(
                    f"Transaction {transaction.transaction_id}",
                    f"Customer {world.customer_id}",
                    f"Amount {transaction.amount:,.2f} {transaction.currency}",
                    f"!Status failed: {transaction.failure_reason}",
                ),
                turns=((cast.payments_engineer.speaker,
                        f"The reference payment is {world.variant('transaction', 0)} from "
                        f"{world.variant('customer', 0)}, and it failed at "
                        f"{clock(timeline.transaction_at)} UTC."),),
            ),
            VideoScene(
                title="What we ruled out",
                lines=(
                    f"- {FRAUD_SERVICE} returned ALLOW",
                    "- Packet loss was three days earlier",
                    "- Balance was sufficient",
                ),
                turns=((cast.fraud_analyst.speaker,
                        "Three explanations looked plausible and all three were ruled out with "
                        "evidence, not opinion."),),
            ),
            VideoScene(
                title="Root cause",
                lines=(
                    f"{AUTH_SERVICE} token validation p99 8.4s",
                    f"{GATEWAY_SERVICE} pool exhausted at 64",
                    f"Release {cast.release_tag} rolled back",
                ),
                turns=((cast.auth_engineer.speaker,
                        f"The root cause is the {AUTH_SERVICE} timeout. {GATEWAY_SERVICE} blocks on token "
                        f"validation, so the connection pool was exhausted and authorisations were "
                        f"rejected."),),
            ),
            VideoScene(
                title="Actions",
                lines=("Cache the revocation list", "Bound the gateway wait", "Add a canary stage"),
                turns=((cast.commander.speaker,
                        "Three actions are tracked against the incident and all three have owners."),),
            ),
        ),
    )


def _architecture_review(world: World) -> VideoScript:
    cast = world.cast
    return VideoScript(
        slug="architecture-review-sharding",
        title=f"Architecture review: sharding {SESSION_DB}",
        entities=(SESSION_DB, AUTH_SERVICE),
        tags=("architecture", "sharding", "review"),
        answer_scenes={CUE_ARCHITECTURE_CHANGE: 2},
        scenes=(
            VideoScene(
                title="Agenda",
                lines=("Session store scaling", "- One agenda item"),
                turns=((cast.data_architect.speaker,
                        "One agenda item today, the session store and how we scale it."),),
            ),
            VideoScene(
                title="Current topology",
                lines=(f"{SESSION_DB} primary", f"{SESSION_DB} replica", "- Two database nodes today"),
                turns=((cast.auth_engineer.speaker,
                        f"Today {SESSION_DB} is one primary and one replica, and every token validation "
                        f"contends on the primary."),),
            ),
            VideoScene(
                title="Proposed architecture change",
                lines=(
                    f"Shard {SESSION_DB} into three database nodes",
                    "Keyed by tenant band",
                    "One replica per shard",
                ),
                turns=((cast.data_architect.speaker,
                        f"The architecture change I am proposing is sharding: we split {SESSION_DB} into "
                        f"three database nodes keyed by tenant band, each with its own replica."),),
            ),
            VideoScene(
                title="Risks and decision",
                lines=("- Cross-shard hop", "- Cache still required", "Approved in principle"),
                turns=((cast.reliability_engineer.speaker,
                        "The risk is a cross-shard hop, and we still need the revocation cache regardless. "
                        "Approved in principle."),),
            ),
        ),
    )


def _engineering_meeting(world: World) -> VideoScript:
    cast = world.cast
    named = world.data.meeting_customers
    return VideoScript(
        slug="engineering-meeting-merchants",
        title="Engineering meeting: merchant tickets",
        entities=tuple(named) + (world.incident_id,),
        tags=("meeting", "customers"),
        answer_scenes={CUE_CUSTOMERS_NAMED: 1},
        scenes=(
            VideoScene(
                title="Agenda",
                lines=("Merchant tickets from the incident", f"- {world.incident_id}"),
                turns=((cast.commander.speaker,
                        f"We are reviewing the merchant tickets raised during {world.incident_id}."),),
            ),
            VideoScene(
                title="Merchants who raised tickets",
                lines=tuple(f"Customer {customer}" for customer in named),
                turns=((cast.payments_engineer.speaker,
                        "The merchants that raised tickets were "
                        + ", ".join(named)
                        + ". I want to know which of them had more than five failed payments."),),
            ),
            VideoScene(
                title="Next steps",
                lines=("Pull failed payment counts", "- From the payments database"),
                turns=((cast.reliability_engineer.speaker,
                        "I will pull the failed payment counts from the payments database and circulate "
                        "them."),),
            ),
        ),
    )


def build_video_scripts(world: World) -> tuple[VideoScript, ...]:
    return (_incident_walkthrough(world), _architecture_review(world), _engineering_meeting(world))


def filler_script(world: World, index: int) -> VideoScript:
    """A cheap two-scene clip so the large tier stays feasible."""
    rng = make_rng(world.seed, f"{STREAM_VIDEO}-filler-{index}")
    asset = pick(rng, list(world.data.assets))
    speaker = pick(rng, [person.speaker for person in world.cast.people])
    return VideoScript(
        slug=f"ops-clip-{index:05d}",
        title=f"Operations clip {index:05d}",
        entities=(asset.asset_id,),
        tags=("filler",),
        answer_scenes={},
        scenes=(
            VideoScene(
                title=f"{asset.service} status",
                lines=(f"Asset {asset.asset_id}", f"- {asset.environment}"),
                turns=((speaker, f"Status update for {asset.service}, nothing to report."),),
            ),
            VideoScene(
                title="Close",
                lines=("No action required",),
                turns=((speaker, "No action required this cycle."),),
            ),
        ),
    )
