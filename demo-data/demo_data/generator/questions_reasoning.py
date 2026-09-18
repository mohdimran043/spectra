"""Benchmark questions for the reasoning categories.

These are the questions a retrieval-only baseline is expected to lose on:
resolving surface forms, chaining hops, ordering events, settling a
contradiction, testing a candidate explanation to destruction, judging sufficiency and
knowing when to abstain.
"""

from __future__ import annotations

from typing import Final

from .expected import (
    CorpusIndex,
    ExpectedQuestion,
    audio_target,
    database_target,
    document_target,
    image_target,
    video_target,
)
from .rng import digits_of, human_date
from .story import AUTH_SERVICE, SESSION_DB
from .videoscripts import CUE_ROOT_CAUSE
from .world import World

MODE_FAST: Final[str] = "fast"
MODE_DEEP: Final[str] = "deep"
STATUS_SUPPORTED: Final[str] = "supported"
STATUS_CONTESTED: Final[str] = "contested"
STATUS_INSUFFICIENT: Final[str] = "insufficient_evidence"


def entity_resolution(world: World, index: CorpusIndex) -> tuple[ExpectedQuestion, ...]:
    report = index.document("incident-report-")
    handover = index.document("oncall-handover-note")
    transaction_digits = digits_of(world.transaction_id)
    customer_digits = digits_of(world.customer_id)
    incident_digits = digits_of(world.incident_id)
    return (
        ExpectedQuestion(
            id="entity_resolution_payment_reference",
            question=f"Does 'payment reference {transaction_digits}' refer to the same thing as "
                     f"{world.transaction_id}?",
            category="entity_resolution",
            mode=MODE_FAST,
            expected_entities=(world.transaction_id,),
            expected_targets=(
                document_target(report.document_id, report.page_of("Customer impact")),
                database_target("transactions", world.transaction_id),
            ),
            expected_conclusion=f"Yes. Both surface forms resolve to {world.transaction_id}.",
            expected_status=STATUS_SUPPORTED,
            notes="Variant surface form used verbatim in the corpus.",
        ),
        ExpectedQuestion(
            id="entity_resolution_customer_variant",
            question=f"'Customer {customer_digits}' appears in the incident report. Which customer record "
                     "is that?",
            category="entity_resolution",
            mode=MODE_FAST,
            expected_entities=(world.customer_id,),
            expected_targets=(
                document_target(report.document_id, report.page_of("Scope")),
                database_target("customers", world.customer_id),
            ),
            expected_conclusion=f"{world.customer_id} - {world.customer_name}.",
            expected_status=STATUS_SUPPORTED,
            notes="Prefixed form to canonical id.",
        ),
        ExpectedQuestion(
            id="entity_resolution_incident_variant",
            question=f"The handover note mentions 'Incident #{incident_digits}'. Which incident is that and "
                     "is it the same as the one in the incident report?",
            category="entity_resolution",
            mode=MODE_FAST,
            expected_entities=(world.incident_id,),
            expected_targets=(
                document_target(handover.document_id),
                database_target("incidents", world.incident_id),
            ),
            expected_conclusion=f"Yes - both are {world.incident_id}.",
            expected_status=STATUS_SUPPORTED,
            notes="Cross-document identity of one incident.",
        ),
        ExpectedQuestion(
            id="entity_resolution_variant_family",
            question=f"Which canonical id do 'Txn {transaction_digits}', 'Transaction #{transaction_digits}' "
                     f"and '{world.transaction_id}' all resolve to?",
            category="entity_resolution",
            mode=MODE_FAST,
            expected_entities=(world.transaction_id,),
            expected_targets=(database_target("transactions", world.transaction_id),),
            expected_conclusion=world.transaction_id,
            expected_status=STATUS_SUPPORTED,
            notes="Three variants, one entity.",
        ),
    )


def multi_hop(world: World, index: CorpusIndex) -> tuple[ExpectedQuestion, ...]:
    report = index.document("incident-report-")
    walkthrough = index.video("incident-walkthrough-")
    bridge = index.clip("incident-bridge-call")
    dashboard = index.image("dashboard-payments-console")
    return (
        ExpectedQuestion(
            id="multi_hop_investigate_transaction",
            question=f"Investigate why {world.transaction_id} failed and find all corroborating evidence.",
            category="multi_hop_investigation",
            mode=MODE_DEEP,
            expected_entities=(world.transaction_id, world.customer_id, world.incident_id, AUTH_SERVICE),
            expected_targets=(
                database_target("transactions", world.transaction_id),
                database_target("incidents", world.incident_id),
                document_target(report.document_id, report.key_page),
                video_target(walkthrough.video_id, walkthrough.answer_spans[CUE_ROOT_CAUSE]),
                audio_target(bridge.audio_id, bridge.answer_spans["token validation"]),
                image_target(dashboard.image_id),
            ),
            expected_conclusion=world.key_finding,
            expected_status=STATUS_SUPPORTED,
            notes="The spec's Demo G and first end-to-end test.",
        ),
        ExpectedQuestion(
            id="multi_hop_from_screenshot",
            question=f"Starting from the payments console screenshot {dashboard.image_id}, explain which "
                     "incident the payment belongs to and why it failed.",
            category="multi_hop_investigation",
            mode=MODE_DEEP,
            expected_entities=(world.transaction_id, world.incident_id),
            expected_targets=(
                image_target(dashboard.image_id),
                database_target("transactions", world.transaction_id),
                database_target("incidents", world.incident_id),
                document_target(report.document_id, report.key_page),
            ),
            expected_conclusion=f"It belongs to {world.incident_id}; {world.key_finding}",
            expected_status=STATUS_SUPPORTED,
            notes="Image to entity to database to document.",
        ),
        ExpectedQuestion(
            id="multi_hop_customer_to_service",
            question=f"What connects customer {world.customer_id} to the {AUTH_SERVICE}?",
            category="multi_hop_investigation",
            mode=MODE_DEEP,
            expected_entities=(world.customer_id, world.transaction_id, world.incident_id, AUTH_SERVICE),
            expected_targets=(
                database_target("customers", world.customer_id),
                database_target("transactions", world.transaction_id),
                database_target("incidents", world.incident_id),
                document_target(report.document_id, report.key_page),
            ),
            expected_conclusion=f"The customer's failed payment {world.transaction_id} is linked to "
                                f"{world.incident_id}, whose service is {AUTH_SERVICE}.",
            expected_status=STATUS_SUPPORTED,
            notes="Three-hop graph traversal.",
        ),
    )


def temporal(world: World, index: CorpusIndex) -> tuple[ExpectedQuestion, ...]:
    report = index.document("incident-report-")
    changelog = index.document("platform-changelog")
    network = index.document("network-incident-")
    memo_v2 = index.document(f"approval-memo-{world.incident_id.lower()}-v2")
    timeline = world.cast.timeline
    return (
        ExpectedQuestion(
            id="temporal_fraud_rule_order",
            question=f"Did the fraud rule deployment happen before or after {world.transaction_id} failed?",
            category="temporal_reasoning",
            mode=MODE_DEEP,
            expected_entities=(world.transaction_id, world.fraud_incident_id),
            expected_targets=(
                document_target(changelog.document_id),
                document_target(report.document_id, report.page_of("Timeline")),
            ),
            expected_conclusion="Before - the rule shipped the previous evening, about nine hours earlier.",
            expected_status=STATUS_SUPPORTED,
            notes="Ordering two events from two documents.",
        ),
        ExpectedQuestion(
            id="temporal_network_window",
            question="Was the network packet-loss event inside the payment incident window?",
            category="temporal_reasoning",
            mode=MODE_DEEP,
            expected_entities=(world.network_incident_id, world.incident_id),
            expected_targets=(
                document_target(network.document_id, network.page_of("Window")),
                document_target(report.document_id, report.page_of("Timeline")),
            ),
            expected_conclusion=f"No - the packet loss was on {human_date(timeline.network_event_at)}, "
                                f"three days before {human_date(timeline.deploy_at)}.",
            expected_status=STATUS_SUPPORTED,
            notes="Disproof by timeline.",
        ),
        ExpectedQuestion(
            id="temporal_approval_before_rollback",
            question="Which came first, the change board approval or the rollback?",
            category="temporal_reasoning",
            mode=MODE_DEEP,
            expected_entities=(world.incident_id,),
            expected_targets=(
                document_target(memo_v2.document_id),
                document_target(report.document_id, report.page_of("Timeline")),
            ),
            expected_conclusion="The approval, about 45 minutes before the rollback.",
            expected_status=STATUS_SUPPORTED,
            notes="Requires the current memo, not the superseded one.",
        ),
    )


def contradiction(world: World, index: CorpusIndex) -> tuple[ExpectedQuestion, ...]:
    memo_v1 = index.document(f"approval-memo-{world.incident_id.lower()}-v1")
    memo_v2 = index.document(f"approval-memo-{world.incident_id.lower()}-v2")
    fraud = index.document("fraud-rule-review-")
    report = index.document("incident-report-")
    return (
        ExpectedQuestion(
            id="contradiction_memos_disagree",
            question=f"Do the approval memos for {world.incident_id} agree about whether the emergency "
                     "change was approved?",
            category="contradiction_detection",
            mode=MODE_DEEP,
            expected_entities=(world.incident_id,),
            expected_targets=(
                document_target(memo_v1.document_id),
                document_target(memo_v2.document_id),
            ),
            expected_conclusion="No - revision 1 says the board had not approved it, revision 2 says it "
                                "was approved.",
            expected_status=STATUS_CONTESTED,
            notes="Detection only; the planted contradiction.",
        ),
        ExpectedQuestion(
            id="contradiction_resolved_by_version",
            question=f"The sources disagree about whether {world.incident_id} was approved. Which is "
                     "correct and why?",
            category="contradiction_detection",
            mode=MODE_DEEP,
            expected_entities=(world.incident_id,),
            expected_targets=(
                document_target(memo_v1.document_id),
                document_target(memo_v2.document_id),
                database_target("incidents", world.incident_id),
            ),
            expected_conclusion=f"Revision 2 is correct: it supersedes revision 1 and matches the incidents "
                                f"table, which records approved by {world.cast.approver.name}.",
            expected_status=STATUS_SUPPORTED,
            notes="The spec's fourth end-to-end test: version and source reliability resolve it.",
        ),
        ExpectedQuestion(
            id="contradiction_fraud_claim",
            question=f"Does any source claim the fraud rule caused {world.transaction_id} to fail?",
            category="contradiction_detection",
            mode=MODE_DEEP,
            expected_entities=(world.transaction_id, world.fraud_incident_id),
            expected_targets=(
                document_target(fraud.document_id, fraud.page_of("Decision log")),
                document_target(report.document_id, report.page_of("Candidate explanation 1")),
            ),
            expected_conclusion="No source claims it. The fraud service logged ALLOW for that "
                                "authorisation.",
            expected_status=STATUS_SUPPORTED,
            notes="Guards against confusing 'first suspect' with 'claimed cause'.",
        ),
    )


def claim_verification(world: World, index: CorpusIndex) -> tuple[ExpectedQuestion, ...]:
    report = index.document("incident-report-")
    fraud = index.document("fraud-rule-review-")
    network = index.document("network-incident-")
    statement = index.document("customer-statement-")
    return (
        ExpectedQuestion(
            id="candidate explanation_fraud_rule",
            question=f"Test the candidate explanation that {world.transaction_id} failed because a fraud rule "
                     "rejected it.",
            category="claim_verification",
            mode=MODE_DEEP,
            expected_entities=(world.transaction_id, world.fraud_incident_id),
            expected_targets=(
                document_target(fraud.document_id, fraud.page_of("Decision log")),
                document_target(report.document_id, report.page_of("Candidate explanation 1")),
                database_target("transactions", world.transaction_id),
            ),
            expected_conclusion="Disproved - the fraud service returned ALLOW and the recorded failure "
                                "code is an upstream authentication timeout.",
            expected_status=STATUS_SUPPORTED,
            notes="Rival with genuine supporting trace.",
        ),
        ExpectedQuestion(
            id="candidate explanation_network_failure",
            question=f"Test the candidate explanation that {world.transaction_id} failed because of a network failure.",
            category="claim_verification",
            mode=MODE_DEEP,
            expected_entities=(world.transaction_id, world.network_incident_id),
            expected_targets=(
                document_target(network.document_id, network.page_of("Window")),
                document_target(report.document_id, report.page_of("Candidate explanation 2")),
            ),
            expected_conclusion="Disproved - the packet loss was three days earlier and the counters were "
                                "clean in the incident window.",
            expected_status=STATUS_SUPPORTED,
            notes="Disproof by timeline.",
        ),
        ExpectedQuestion(
            id="candidate explanation_insufficient_balance",
            question=f"Test the candidate explanation that {world.transaction_id} failed because of an insufficient "
                     "balance.",
            category="claim_verification",
            mode=MODE_DEEP,
            expected_entities=(world.transaction_id, world.customer_id),
            expected_targets=(
                document_target(statement.document_id, statement.page_of("Balance")),
                document_target(report.document_id, report.page_of("Candidate explanation 3")),
            ),
            expected_conclusion="Disproved - the available balance exceeded the authorisation and the "
                                "issuer was never reached.",
            expected_status=STATUS_SUPPORTED,
            notes="Rival with a real earlier insufficient-funds decline in the database.",
        ),
        ExpectedQuestion(
            id="candidate explanation_auth_timeout",
            question=f"Test the candidate explanation that an authentication timeout caused {world.transaction_id} "
                     "to fail.",
            category="claim_verification",
            mode=MODE_DEEP,
            expected_entities=(world.transaction_id, AUTH_SERVICE, world.incident_id),
            expected_targets=(
                document_target(report.document_id, report.key_page),
                database_target("incidents", world.incident_id),
            ),
            expected_conclusion=f"Supported - {world.key_finding}",
            expected_status=STATUS_SUPPORTED,
            notes="The surviving candidate explanation.",
        ),
    )


def sufficiency(world: World, index: CorpusIndex) -> tuple[ExpectedQuestion, ...]:
    report = index.document("incident-report-")
    memo_v2 = index.document(f"approval-memo-{world.incident_id.lower()}-v2")
    approval_mail = index.image("screenshot-approval-email")
    bridge = index.clip("incident-bridge-call")
    return (
        ExpectedQuestion(
            id="sufficiency_root_cause",
            question=f"Is there enough evidence to state the root cause of {world.incident_id}?",
            category="evidence_sufficiency",
            mode=MODE_DEEP,
            expected_entities=(world.incident_id, AUTH_SERVICE),
            expected_targets=(
                document_target(report.document_id, report.key_page),
                database_target("incidents", world.incident_id),
                audio_target(bridge.audio_id, bridge.answer_spans["token validation"]),
            ),
            expected_conclusion="Yes - document, database and audio evidence agree.",
            expected_status=STATUS_SUPPORTED,
            notes="Diversity across three modalities.",
        ),
        ExpectedQuestion(
            id="sufficiency_approver",
            question="Is there enough evidence to say who approved the emergency change?",
            category="evidence_sufficiency",
            mode=MODE_DEEP,
            expected_entities=(world.incident_id,),
            expected_targets=(
                document_target(memo_v2.document_id),
                image_target(approval_mail.image_id),
                database_target("incidents", world.incident_id),
            ),
            expected_conclusion=f"Yes - {world.cast.approver.name}, corroborated by the memo, the mail "
                                "screenshot and the incidents table.",
            expected_status=STATUS_SUPPORTED,
            notes="Sufficiency despite a superseded memo saying otherwise.",
        ),
        ExpectedQuestion(
            id="sufficiency_revenue_impact",
            question=f"Is there enough evidence to quantify the revenue lost during {world.incident_id}?",
            category="evidence_sufficiency",
            mode=MODE_DEEP,
            expected_entities=(world.incident_id,),
            expected_targets=(),
            expected_conclusion="No - the corpus records failed authorisations but no revenue impact "
                                "figure.",
            expected_status=STATUS_INSUFFICIENT,
            notes="Sufficiency judged negative; abstention is the correct behaviour.",
        ),
    )


def abstention(world: World, index: CorpusIndex) -> tuple[ExpectedQuestion, ...]:
    del index
    return (
        ExpectedQuestion(
            id="abstention_sla_penalty",
            question="What SLA penalty did the transit provider pay for the packet loss?",
            category="abstention",
            mode=MODE_DEEP,
            expected_entities=(world.network_incident_id,),
            expected_targets=(),
            expected_conclusion="Not recorded anywhere in the corpus.",
            expected_status=STATUS_INSUFFICIENT,
            notes="The network incident exists; the penalty does not.",
        ),
        ExpectedQuestion(
            id="abstention_customer_churn",
            question=f"How many customers churned after {world.incident_id}?",
            category="abstention",
            mode=MODE_DEEP,
            expected_entities=(world.incident_id,),
            expected_targets=(),
            expected_conclusion="Not recorded - no churn data exists in the dataset.",
            expected_status=STATUS_INSUFFICIENT,
            notes="Plausible-sounding but unanswerable.",
        ),
        ExpectedQuestion(
            id="abstention_shard_placement",
            question=f"Which {SESSION_DB} shard stores customer {world.customer_id} today?",
            category="abstention",
            mode=MODE_DEEP,
            expected_entities=(world.customer_id, SESSION_DB),
            expected_targets=(),
            expected_conclusion="None - sharding is a proposal; the migration has not happened.",
            expected_status=STATUS_INSUFFICIENT,
            notes="A design document describes the target topology, which is not the current one.",
        ),
        ExpectedQuestion(
            id="abstention_personal_detail",
            question=f"What is the home address of {world.cast.approver.name}?",
            category="abstention",
            mode=MODE_FAST,
            expected_entities=(),
            expected_targets=(),
            expected_conclusion="Not present in the corpus.",
            expected_status=STATUS_INSUFFICIENT,
            notes="Named person, no such attribute anywhere.",
        ),
    )
