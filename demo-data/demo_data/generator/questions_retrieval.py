"""Benchmark questions for the retrieval and cross-modal-hop categories.

Targets are computed from what was actually generated - document entity lists,
image node counts, recorded answer spans - so a re-seed moves the ids and the
ground truth follows.
"""

from __future__ import annotations

from typing import Final

from .constants import ARCHITECTURE_DATABASE_NODES, FAILED_PAYMENT_THRESHOLD
from .expected import (
    CorpusIndex,
    ExpectedQuestion,
    audio_target,
    database_target,
    document_target,
    image_target,
    video_target,
)
from .records import FAILED
from .rng import digits_of
from .story import AUTH_SERVICE, SESSION_DB
from .videoscripts import (
    CUE_ARCHITECTURE_CHANGE,
    CUE_CUSTOMERS_NAMED,
    CUE_ROOT_CAUSE,
    CUE_TRANSACTION_ON_SCREEN,
)
from .world import World

MODE_FAST: Final[str] = "fast"
MODE_DEEP: Final[str] = "deep"
STATUS_SUPPORTED: Final[str] = "supported"
#: Cap on how many database rows a single expected answer enumerates.
MAX_DB_TARGETS: Final[int] = 25


def _failed_for(world: World, customer_id: str) -> tuple[str, ...]:
    return tuple(
        row.transaction_id
        for row in world.data.transactions
        if row.customer_id == customer_id and row.status == FAILED
    )[:MAX_DB_TARGETS]


def _documents_naming(index: CorpusIndex, entity: str) -> tuple[str, ...]:
    return tuple(
        document_target(document.document_id)
        for document in index.documents
        if entity in document.entities
    )


def single_source(world: World, index: CorpusIndex) -> tuple[ExpectedQuestion, ...]:
    report = index.document("incident-report-")
    runbook = index.document("runbook-payment-authorisation")
    adr = index.document("adr-0007")
    wiki = index.document("wiki-auth-service")
    return (
        ExpectedQuestion(
            id="single_source_root_cause",
            question=f"What was the root cause of incident {world.incident_id}?",
            category="single_source_retrieval",
            mode=MODE_FAST,
            expected_entities=(world.incident_id,),
            expected_targets=(document_target(report.document_id, report.key_page),),
            expected_conclusion=world.key_finding,
            expected_status=STATUS_SUPPORTED,
            notes="The determination sits on a late page of the report, so page provenance is checkable.",
        ),
        ExpectedQuestion(
            id="single_source_runbook",
            question="What does the runbook say to do when the authorisation connection pool is exhausted?",
            category="single_source_retrieval",
            mode=MODE_FAST,
            expected_entities=(AUTH_SERVICE,),
            expected_targets=(document_target(runbook.document_id, runbook.key_page),),
            expected_conclusion=f"Roll back the most recent {AUTH_SERVICE} release rather than restarting "
                                "the gateway.",
            expected_status=STATUS_SUPPORTED,
            notes="Answerable from one document page.",
        ),
        ExpectedQuestion(
            id="single_source_adr",
            question="Which decision record covers caching the token revocation list, and what was decided?",
            category="single_source_retrieval",
            mode=MODE_FAST,
            expected_entities=(AUTH_SERVICE,),
            expected_targets=(document_target(adr.document_id),),
            expected_conclusion="ADR 0007 was accepted: cache the revocation list in-process with a 30 "
                                "second TTL.",
            expected_status=STATUS_SUPPORTED,
            notes="Markdown source, no pagination.",
        ),
        ExpectedQuestion(
            id="single_source_auth_failures",
            question="Find documents about authentication failures.",
            category="single_source_retrieval",
            mode=MODE_FAST,
            expected_entities=(AUTH_SERVICE,),
            expected_targets=(
                document_target(wiki.document_id),
                document_target(report.document_id, report.key_page),
            ),
            expected_conclusion=f"The {AUTH_SERVICE} wiki page and the incident report both describe the "
                                "authentication failure mode.",
            expected_status=STATUS_SUPPORTED,
            notes="The spec's Demo A query.",
        ),
    )


def cross_document(world: World, index: CorpusIndex) -> tuple[ExpectedQuestion, ...]:
    report = index.document("incident-report-")
    fraud = index.document("fraud-rule-review-")
    minutes = index.document("meeting-minutes-")
    design = index.document("design-session-db-sharding")
    changelog = index.document("platform-changelog")
    return (
        ExpectedQuestion(
            id="cross_document_fraud_vs_incident",
            question=f"How do the fraud rule review and the incident report differ in what they say about "
                     f"{world.transaction_id}?",
            category="cross_document_retrieval",
            mode=MODE_DEEP,
            expected_entities=(world.transaction_id, world.fraud_incident_id, world.incident_id),
            expected_targets=(
                document_target(fraud.document_id, fraud.page_of("Decision log")),
                document_target(report.document_id, report.page_of("Candidate explanation 1")),
            ),
            expected_conclusion=f"They agree: the fraud service returned ALLOW for {world.transaction_id}, "
                                "so the rule is not the cause.",
            expected_status=STATUS_SUPPORTED,
            notes="Requires reading two documents.",
        ),
        ExpectedQuestion(
            id="cross_document_sharding_mentions",
            question=f"Which documents mention both {world.incident_id} and the {SESSION_DB} sharding "
                     "change?",
            category="cross_document_retrieval",
            mode=MODE_DEEP,
            expected_entities=(world.incident_id, SESSION_DB),
            expected_targets=(
                document_target(minutes.document_id),
                document_target(design.document_id),
                document_target(changelog.document_id),
            ),
            expected_conclusion="The engineering minutes, the sharding design document and the platform "
                                "changelog.",
            expected_status=STATUS_SUPPORTED,
            notes="Cross-document set membership.",
        ),
        ExpectedQuestion(
            id="cross_document_transaction_mentions",
            question=f"Gather every document that names {world.transaction_id}.",
            category="cross_document_retrieval",
            mode=MODE_DEEP,
            expected_entities=(world.transaction_id,),
            expected_targets=_documents_naming(index, world.transaction_id),
            expected_conclusion=f"{world.transaction_id} is named across the incident report, the "
                                "post-mortem, the approval memos, the fraud review, the customer statement, "
                                "the handover note and both transaction exports.",
            expected_status=STATUS_SUPPORTED,
            notes="Recall-oriented: every naming document counts.",
        ),
    )


def image_questions(world: World, index: CorpusIndex) -> tuple[ExpectedQuestion, ...]:
    three_node = tuple(
        image_target(image.image_id)
        for image in index.images
        if image.database_nodes == ARCHITECTURE_DATABASE_NODES
    )
    dashboard = index.image("dashboard-payments-console")
    latency = index.image("chart-auth-latency")
    approval = index.image("screenshot-approval-email")
    return (
        ExpectedQuestion(
            id="image_three_database_nodes",
            question="Find architecture diagrams showing three database nodes.",
            category="image_retrieval",
            mode=MODE_FAST,
            expected_entities=(SESSION_DB,),
            expected_targets=three_node,
            expected_conclusion=f"The target-architecture diagram shows {ARCHITECTURE_DATABASE_NODES} "
                                f"{SESSION_DB} nodes; the current-topology diagram shows two and is not a "
                                "match.",
            expected_status=STATUS_SUPPORTED,
            notes="A two-node decoy diagram exists, so counting matters.",
        ),
        ExpectedQuestion(
            id="image_failed_transaction_screenshot",
            question=f"Find the screenshot showing the failed transaction {world.transaction_id}.",
            category="image_retrieval",
            mode=MODE_FAST,
            expected_entities=(world.transaction_id,),
            expected_targets=(image_target(dashboard.image_id),),
            expected_conclusion="The payments operations console screenshot shows the failed row.",
            expected_status=STATUS_SUPPORTED,
            notes="Needs OCR or the render sidecar.",
        ),
        ExpectedQuestion(
            id="image_latency_chart",
            question=f"Find a monitoring chart showing the {AUTH_SERVICE} latency spike.",
            category="image_retrieval",
            mode=MODE_FAST,
            expected_entities=(AUTH_SERVICE,),
            expected_targets=(image_target(latency.image_id),),
            expected_conclusion="The token validation p99 chart peaks at 8.4 seconds.",
            expected_status=STATUS_SUPPORTED,
            notes="Chart image with legible axis labels.",
        ),
        ExpectedQuestion(
            id="image_approval_mail",
            question="Which screenshot shows the change board approving the rollback?",
            category="image_retrieval",
            mode=MODE_FAST,
            expected_entities=(world.incident_id,),
            expected_targets=(image_target(approval.image_id),),
            expected_conclusion=f"The change advisory board mail approving the rollback, from "
                                f"{world.cast.approver.name}.",
            expected_status=STATUS_SUPPORTED,
            notes="Corroborates the current approval memo.",
        ),
    )


def video_questions(world: World, index: CorpusIndex) -> tuple[ExpectedQuestion, ...]:
    walkthrough = index.video("incident-walkthrough-")
    review = index.video("architecture-review-sharding")
    return (
        ExpectedQuestion(
            id="video_architecture_change",
            question="Find where the architecture change is discussed.",
            category="video_retrieval",
            mode=MODE_FAST,
            expected_entities=(SESSION_DB,),
            expected_targets=(video_target(review.video_id, review.answer_spans[CUE_ARCHITECTURE_CHANGE]),),
            expected_conclusion=f"In the architecture review, the proposal is to shard {SESSION_DB} into "
                                f"{ARCHITECTURE_DATABASE_NODES} database nodes keyed by tenant band.",
            expected_status=STATUS_SUPPORTED,
            notes="The spec's second end-to-end test.",
        ),
        ExpectedQuestion(
            id="video_transaction_frame",
            question=f"Find the video frame that displays transaction {world.transaction_id}.",
            category="video_retrieval",
            mode=MODE_FAST,
            expected_entities=(world.transaction_id,),
            expected_targets=(
                video_target(walkthrough.video_id, walkthrough.answer_spans[CUE_TRANSACTION_ON_SCREEN]),
            ),
            expected_conclusion="The failing-payment scene of the incident walkthrough shows the id on "
                                "screen.",
            expected_status=STATUS_SUPPORTED,
            notes="Frame OCR target.",
        ),
        ExpectedQuestion(
            id="video_root_cause_statement",
            question="Where in the incident walkthrough is the root cause stated?",
            category="video_retrieval",
            mode=MODE_FAST,
            expected_entities=(world.incident_id, AUTH_SERVICE),
            expected_targets=(video_target(walkthrough.video_id, walkthrough.answer_spans[CUE_ROOT_CAUSE]),),
            expected_conclusion=f"In the root-cause scene: the {AUTH_SERVICE} timeout exhausted the gateway "
                                "pool.",
            expected_status=STATUS_SUPPORTED,
            notes="Transcript plus scene boundary.",
        ),
    )


def audio_questions(world: World, index: CorpusIndex) -> tuple[ExpectedQuestion, ...]:
    standup = index.clip("standup-engineering")
    bridge = index.clip("incident-bridge-call")
    review = index.clip("architecture-review-call")
    return (
        ExpectedQuestion(
            id="audio_architecture_change",
            question="Find where the speaker discusses the architecture change.",
            category="audio_retrieval",
            mode=MODE_FAST,
            expected_entities=(SESSION_DB,),
            expected_targets=(audio_target(review.audio_id, review.answer_spans["sharding"]),),
            expected_conclusion=f"The data architect proposes sharding {SESSION_DB} into three nodes.",
            expected_status=STATUS_SUPPORTED,
            notes="The spec's Demo D query.",
        ),
        ExpectedQuestion(
            id="audio_authentication_discussion",
            question="Where in the standup is the authentication service discussed?",
            category="audio_retrieval",
            mode=MODE_FAST,
            expected_entities=(AUTH_SERVICE,),
            expected_targets=(audio_target(standup.audio_id, standup.answer_spans["authentication service"]),),
            expected_conclusion="The authentication platform engineer explains the token validation "
                                "regression.",
            expected_status=STATUS_SUPPORTED,
            notes="Speaker-attributed segment.",
        ),
        ExpectedQuestion(
            id="audio_bridge_root_cause",
            question="On the incident bridge, where is the root cause first stated?",
            category="audio_retrieval",
            mode=MODE_FAST,
            expected_entities=(AUTH_SERVICE, world.incident_id),
            expected_targets=(audio_target(bridge.audio_id, bridge.answer_spans["token validation"]),),
            expected_conclusion="When the p99 of token validation is reported as 8.4 seconds.",
            expected_status=STATUS_SUPPORTED,
            notes="Rival candidate explanations are raised earlier in the same call.",
        ),
    )


def database_questions(world: World, index: CorpusIndex) -> tuple[ExpectedQuestion, ...]:
    del index
    failures = world.data.failed_counts()
    above = tuple(
        customer.customer_id
        for customer in world.data.customers
        if failures.get(customer.customer_id, 0) > FAILED_PAYMENT_THRESHOLD
    )
    linked = tuple(
        row.transaction_id
        for row in world.data.transactions
        if row.incident_id == world.incident_id
    )
    focus_failures = _failed_for(world, world.customer_id)
    return (
        ExpectedQuestion(
            id="database_failed_for_customer",
            question=f"Find failed transactions for customer {world.customer_id}.",
            category="database_reasoning",
            mode=MODE_FAST,
            expected_entities=(world.customer_id,),
            expected_targets=tuple(database_target("transactions", tx) for tx in focus_failures),
            expected_conclusion=f"{len(focus_failures)} failed transactions are recorded for "
                                f"{world.customer_id}.",
            expected_status=STATUS_SUPPORTED,
            notes="The spec's Demo E query; requires real SQL, not retrieval.",
        ),
        ExpectedQuestion(
            id="database_high_failure_customers",
            question=f"Which customers had more than {FAILED_PAYMENT_THRESHOLD} failed payments?",
            category="database_reasoning",
            mode=MODE_FAST,
            expected_entities=above,
            expected_targets=tuple(database_target("customers", cid) for cid in above[:MAX_DB_TARGETS]),
            expected_conclusion=f"{len(above)} customers exceed the threshold.",
            expected_status=STATUS_SUPPORTED,
            notes="Aggregation over the transactions table.",
        ),
        ExpectedQuestion(
            id="database_incident_linked_transactions",
            question=f"How many transactions are linked to incident {world.incident_id}?",
            category="database_reasoning",
            mode=MODE_FAST,
            expected_entities=(world.incident_id,),
            expected_targets=tuple(
                database_target("transactions", tx) for tx in linked[:MAX_DB_TARGETS]
            ),
            expected_conclusion=f"{len(linked)} transactions carry that incident id.",
            expected_status=STATUS_SUPPORTED,
            notes="Join between transactions and incidents.",
        ),
        ExpectedQuestion(
            id="database_failure_reason",
            question=f"What failure reason is recorded for {world.transaction_id}?",
            category="database_reasoning",
            mode=MODE_FAST,
            expected_entities=(world.transaction_id,),
            expected_targets=(database_target("transactions", world.transaction_id),),
            expected_conclusion=str(world.data.focus_transaction.failure_reason),
            expected_status=STATUS_SUPPORTED,
            notes="Single-row lookup.",
        ),
    )


def image_to_database(world: World, index: CorpusIndex) -> tuple[ExpectedQuestion, ...]:
    dashboard = index.image("dashboard-payments-console")
    account = index.image("screenshot-customer-account")
    board = index.image("screenshot-incident-board")
    return (
        ExpectedQuestion(
            id="image_to_db_console",
            question=f"The payments console screenshot {dashboard.image_id} shows a failed payment. Look the "
                     "transaction up in the database and explain its status.",
            category="image_to_database",
            mode=MODE_DEEP,
            expected_entities=(world.transaction_id, world.customer_id),
            expected_targets=(
                image_target(dashboard.image_id),
                database_target("transactions", world.transaction_id),
            ),
            expected_conclusion=f"{world.transaction_id} is failed with "
                                f"{world.data.focus_transaction.failure_reason}.",
            expected_status=STATUS_SUPPORTED,
            notes="The spec's Demo F entry point.",
        ),
        ExpectedQuestion(
            id="image_to_db_account",
            question=f"The account screenshot {account.image_id} identifies a customer. List that "
                     "customer's failed transactions from the database.",
            category="image_to_database",
            mode=MODE_DEEP,
            expected_entities=(world.customer_id,),
            expected_targets=(image_target(account.image_id),)
            + tuple(database_target("transactions", tx) for tx in _failed_for(world, world.customer_id)),
            expected_conclusion=f"The screenshot resolves to {world.customer_id}.",
            expected_status=STATUS_SUPPORTED,
            notes="OCR to entity resolution to SQL.",
        ),
        ExpectedQuestion(
            id="image_to_db_incident_board",
            question=f"The incident board screenshot {board.image_id} references an incident. What does the "
                     "incidents table record about its approval?",
            category="image_to_database",
            mode=MODE_DEEP,
            expected_entities=(world.incident_id,),
            expected_targets=(
                image_target(board.image_id),
                database_target("incidents", world.incident_id),
            ),
            expected_conclusion=f"Approved, by {world.cast.approver.name}.",
            expected_status=STATUS_SUPPORTED,
            notes="Image to database, and the answer also settles the memo contradiction.",
        ),
    )


def database_to_video(world: World, index: CorpusIndex) -> tuple[ExpectedQuestion, ...]:
    walkthrough = index.video("incident-walkthrough-")
    meeting = index.video("engineering-meeting-merchants")
    failures = world.data.failed_counts()
    named_above = tuple(
        customer_id
        for customer_id in world.data.meeting_customers
        if failures.get(customer_id, 0) > FAILED_PAYMENT_THRESHOLD
    )
    return (
        ExpectedQuestion(
            id="db_to_video_incident_walkthrough",
            question=f"Incident {world.incident_id} is in the incidents table. Find the video that walks "
                     "through it.",
            category="database_to_video",
            mode=MODE_DEEP,
            expected_entities=(world.incident_id,),
            expected_targets=(
                database_target("incidents", world.incident_id),
                video_target(walkthrough.video_id),
            ),
            expected_conclusion="The incident walkthrough video covers it in five scenes.",
            expected_status=STATUS_SUPPORTED,
            notes="Database row to media.",
        ),
        ExpectedQuestion(
            id="db_to_video_transaction_frame",
            question=f"Transaction {world.transaction_id} failed. Find the video moment that displays it.",
            category="database_to_video",
            mode=MODE_DEEP,
            expected_entities=(world.transaction_id,),
            expected_targets=(
                database_target("transactions", world.transaction_id),
                video_target(walkthrough.video_id, walkthrough.answer_spans[CUE_TRANSACTION_ON_SCREEN]),
            ),
            expected_conclusion="The failing-payment scene shows the transaction id and the failure code.",
            expected_status=STATUS_SUPPORTED,
            notes="Database row to frame OCR.",
        ),
        ExpectedQuestion(
            id="db_to_video_meeting_customers",
            question=f"Which customers mentioned in the engineering meeting had more than "
                     f"{FAILED_PAYMENT_THRESHOLD} failed payments?",
            category="database_to_video",
            mode=MODE_DEEP,
            expected_entities=named_above,
            expected_targets=(video_target(meeting.video_id, meeting.answer_spans[CUE_CUSTOMERS_NAMED]),)
            + tuple(database_target("customers", customer_id) for customer_id in named_above),
            expected_conclusion=", ".join(named_above) if named_above else "none of them",
            expected_status=STATUS_SUPPORTED,
            notes="The spec's third end-to-end test: video to entity extraction to SQL aggregation.",
        ),
    )


def video_to_document(world: World, index: CorpusIndex) -> tuple[ExpectedQuestion, ...]:
    review = index.video("architecture-review-sharding")
    walkthrough = index.video("incident-walkthrough-")
    meeting = index.video("engineering-meeting-merchants")
    design = index.document("design-session-db-sharding")
    report = index.document("incident-report-")
    minutes = index.document("meeting-minutes-")
    return (
        ExpectedQuestion(
            id="video_to_doc_design",
            question="The architecture review video proposes a change. Which design document describes it?",
            category="video_to_document",
            mode=MODE_DEEP,
            expected_entities=(SESSION_DB,),
            expected_targets=(
                video_target(review.video_id, review.answer_spans[CUE_ARCHITECTURE_CHANGE]),
                document_target(design.document_id, design.page_of("Target topology")),
            ),
            expected_conclusion=f"The sharding design document, whose target topology has "
                                f"{ARCHITECTURE_DATABASE_NODES} database nodes.",
            expected_status=STATUS_SUPPORTED,
            notes="Video to document hop.",
        ),
        ExpectedQuestion(
            id="video_to_doc_root_cause",
            question="The incident walkthrough states a root cause. Which document page records it?",
            category="video_to_document",
            mode=MODE_DEEP,
            expected_entities=(world.incident_id,),
            expected_targets=(
                video_target(walkthrough.video_id, walkthrough.answer_spans[CUE_ROOT_CAUSE]),
                document_target(report.document_id, report.key_page),
            ),
            expected_conclusion=f"Page {report.key_page} of the incident report.",
            expected_status=STATUS_SUPPORTED,
            notes="Checks page-level provenance across modalities.",
        ),
        ExpectedQuestion(
            id="video_to_doc_minutes",
            question="The engineering meeting video names merchants. Which minutes document lists them?",
            category="video_to_document",
            mode=MODE_DEEP,
            expected_entities=tuple(world.data.meeting_customers),
            expected_targets=(
                video_target(meeting.video_id, meeting.answer_spans[CUE_CUSTOMERS_NAMED]),
                document_target(minutes.document_id),
            ),
            expected_conclusion="The engineering review minutes for the same meeting.",
            expected_status=STATUS_SUPPORTED,
            notes="Video to document corroboration.",
        ),
    )


def digits(identifier: str) -> str:
    """Re-exported for the reasoning questions, which quote bare surface forms."""
    return digits_of(identifier)
