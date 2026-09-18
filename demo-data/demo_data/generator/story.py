"""The investigation narrative: cast, services and the timeline it turns on.

The story is deliberately *adversarial*.  A payment fails; the true root cause
is an authentication-service timeout; three competing explanations (a fraud
rule, a network event, an insufficient balance) are each plausible and each
leave a real trace in the corpus; and two versions of one approval memo
disagree about whether the emergency change was signed off.  Only resolving
entities across modalities makes the evidence cohere.

Nothing here is hard-coded to a seed: the cast, the services and the calendar
all move when the seed moves.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from .rng import incident_moment, pick

FIRST_NAMES: Final[tuple[str, ...]] = (
    "Dana", "Marcus", "Priya", "Tomas", "Elena", "Helena", "Samuel", "Noor",
    "Jonas", "Amara", "Ruben", "Ingrid", "Yusuf", "Clara", "Mateo", "Leila",
)
LAST_NAMES: Final[tuple[str, ...]] = (
    "Okonkwo", "Feld", "Raghunathan", "Lindqvist", "Duarte", "Vogt", "Ateba",
    "Halvorsen", "Baptiste", "Sandoval", "Keller", "Novak", "Mbeki", "Ferraro",
)
ROLES: Final[tuple[str, ...]] = (
    "incident commander",
    "authentication platform engineer",
    "payments engineer",
    "site reliability engineer",
    "fraud analyst",
    "change advisory board chair",
    "data architect",
)
COMPANY_DOMAIN: Final[str] = "northwind-financial.example"

AUTH_SERVICE: Final[str] = "auth-service"
GATEWAY_SERVICE: Final[str] = "payment-gateway"
FRAUD_SERVICE: Final[str] = "fraud-service"
LEDGER_SERVICE: Final[str] = "ledger-service"
NOTIFICATION_SERVICE: Final[str] = "notification-service"
SESSION_DB: Final[str] = "session-db"
SERVICES: Final[tuple[str, ...]] = (
    AUTH_SERVICE, GATEWAY_SERVICE, FRAUD_SERVICE, LEDGER_SERVICE, NOTIFICATION_SERVICE, SESSION_DB,
)

RELEASE_TAGS: Final[tuple[str, ...]] = ("2.14.0", "3.2.1", "4.7.3", "5.1.9", "6.0.2")
REGIONS: Final[tuple[str, ...]] = ("eu-west-1", "eu-central-1", "us-east-1", "ap-south-1")
CURRENCIES: Final[tuple[str, ...]] = ("EUR", "USD", "GBP")

#: p99 latency, in seconds, that auth-service reached during the incident.
AUTH_P99_SECONDS: Final[float] = 8.4
#: Connection-pool size the payment gateway exhausted.
GATEWAY_POOL_SIZE: Final[int] = 64
#: The failure code written onto the focus transaction row.
FOCUS_FAILURE_REASON: Final[str] = "upstream_auth_timeout"
FRAUD_FAILURE_REASON: Final[str] = "fraud_rule_block"
NETWORK_FAILURE_REASON: Final[str] = "network_unreachable"
BALANCE_FAILURE_REASON: Final[str] = "insufficient_funds"
OTHER_FAILURE_REASONS: Final[tuple[str, ...]] = (
    "card_expired", "issuer_declined", "3ds_abandoned", "duplicate_submission",
)


@dataclass(frozen=True)
class Person:
    name: str
    role: str
    email: str
    speaker: str


@dataclass(frozen=True)
class Timeline:
    """Every instant the narrative refers to, in UTC."""

    deploy_at: datetime
    latency_spike_at: datetime
    transaction_at: datetime
    incident_opened_at: datetime
    approval_at: datetime
    rollback_at: datetime
    resolved_at: datetime
    standup_at: datetime
    postmortem_at: datetime
    architecture_review_at: datetime
    fraud_rule_deploy_at: datetime
    network_event_at: datetime

    @property
    def ordered(self) -> tuple[tuple[str, datetime], ...]:
        return (
            ("network_event", self.network_event_at),
            ("fraud_rule_deploy", self.fraud_rule_deploy_at),
            ("deploy", self.deploy_at),
            ("latency_spike", self.latency_spike_at),
            ("transaction_failed", self.transaction_at),
            ("incident_opened", self.incident_opened_at),
            ("change_approved", self.approval_at),
            ("rollback", self.rollback_at),
            ("incident_resolved", self.resolved_at),
            ("standup", self.standup_at),
            ("postmortem", self.postmortem_at),
            ("architecture_review", self.architecture_review_at),
        )


@dataclass(frozen=True)
class Cast:
    """People, services and calendar - everything the records must agree with."""

    commander: Person
    auth_engineer: Person
    payments_engineer: Person
    reliability_engineer: Person
    fraud_analyst: Person
    approver: Person
    data_architect: Person
    timeline: Timeline
    release_tag: str
    region: str
    currency: str

    @property
    def people(self) -> tuple[Person, ...]:
        return (
            self.commander,
            self.auth_engineer,
            self.payments_engineer,
            self.reliability_engineer,
            self.fraud_analyst,
            self.approver,
            self.data_architect,
        )

    @property
    def root_cause(self) -> str:
        return (
            f"{AUTH_SERVICE} token validation p99 rose to {AUTH_P99_SECONDS:.1f}s after release "
            f"{self.release_tag}, so {GATEWAY_SERVICE} held authorisation sessions open until its "
            f"{GATEWAY_POOL_SIZE}-connection pool was exhausted"
        )


def _person(rng: random.Random, role: str, used: set[str]) -> Person:
    for _ in range(len(FIRST_NAMES) * len(LAST_NAMES)):
        first = pick(rng, FIRST_NAMES)
        last = pick(rng, LAST_NAMES)
        name = f"{first} {last}"
        if name not in used:
            used.add(name)
            return Person(
                name=name,
                role=role,
                email=f"{first.lower()}.{last.lower()}@{COMPANY_DOMAIN}",
                speaker=first,
            )
    raise RuntimeError("exhausted the name pool while building the cast")


def build_timeline(rng: random.Random) -> Timeline:
    """Place every narrative instant around the seeded incident moment."""
    deploy_at = incident_moment(rng)
    return Timeline(
        deploy_at=deploy_at,
        latency_spike_at=deploy_at + timedelta(minutes=35),
        transaction_at=deploy_at + timedelta(minutes=51),
        incident_opened_at=deploy_at + timedelta(minutes=58),
        approval_at=deploy_at + timedelta(minutes=88),
        rollback_at=deploy_at + timedelta(minutes=133),
        resolved_at=deploy_at + timedelta(minutes=166),
        standup_at=deploy_at + timedelta(days=1, hours=7, minutes=48),
        postmortem_at=deploy_at + timedelta(days=1, hours=9),
        architecture_review_at=deploy_at + timedelta(days=2, hours=12, minutes=48),
        fraud_rule_deploy_at=deploy_at - timedelta(hours=9),
        network_event_at=deploy_at - timedelta(days=3, hours=2),
    )


def build_cast(rng: random.Random) -> Cast:
    """Draw the cast, the release under investigation and the calendar."""
    used: set[str] = set()
    people = [_person(rng, role, used) for role in ROLES]
    return Cast(
        commander=people[0],
        auth_engineer=people[1],
        payments_engineer=people[2],
        reliability_engineer=people[3],
        fraud_analyst=people[4],
        approver=people[5],
        data_architect=people[6],
        timeline=build_timeline(rng),
        release_tag=pick(rng, RELEASE_TAGS),
        region=pick(rng, REGIONS),
        currency=pick(rng, CURRENCIES),
    )
