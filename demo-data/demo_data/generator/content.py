from __future__ import annotations

from .constants import INCIDENT_REPORT_KEY_PAGE, INCIDENT_REPORT_PAGES
from .content_plain import (
    adr,
    capacity_plan,
    changelog,
    failed_transactions_csv,
    oncall_handover,
    security_review,
    service_catalogue,
    transaction_extract_xlsx,
    wiki_page,
)
from .content_support import (
    architecture_deck,
    customer_statement,
    fraud_rule_review,
    meeting_minutes,
    network_incident_report,
    postmortem,
    sharding_design,
)
from .rng import clock, human_date, iso
from .specs import (
    FORMAT_DOCX,
    FORMAT_PDF,
    VERSION_CURRENT,
    VERSION_SUPERSEDED,
    DocumentSpec,
    Section,
    section,
)
from .story import AUTH_SERVICE, FRAUD_SERVICE, GATEWAY_SERVICE, LEDGER_SERVICE, SESSION_DB
from .world import World


def _incident_report_sections(world: World) -> tuple[Section, ...]:
    cast, timeline = world.cast, world.cast.timeline
    transaction, customer, incident = world.transaction_id, world.customer_id, world.incident_id
    return (
        section(
            f"Incident report {incident}",
            f"Severity: {world.data.root_incident.severity}. Service: {AUTH_SERVICE}. "
            f"Commander: {cast.commander.name} ({cast.commander.role}).",
            f"Opened {iso(timeline.incident_opened_at)}, resolved {iso(timeline.resolved_at)}. "
            f"This report is the authoritative record for {incident}.",
        ),
        section(
            "Scope and blast radius",
            f"Card and wallet authorisations routed through {GATEWAY_SERVICE} failed for approximately "
            f"{int((timeline.resolved_at - timeline.latency_spike_at).total_seconds() // 60)} minutes in "
            f"{cast.region}.",
            f"The reference failure raised by the customer is {world.variant('transaction', 1)}, "
            f"raised by {world.customer_name} ({world.variant('customer', 1)}).",
        ),
        section(
            "Timeline of record",
            f"{clock(timeline.deploy_at)} UTC - release {cast.release_tag} of {AUTH_SERVICE} reaches production.",
            f"{clock(timeline.latency_spike_at)} UTC - token validation p99 crosses 8 seconds.",
            f"{clock(timeline.transaction_at)} UTC - {transaction} fails with "
            f"{world.data.focus_transaction.failure_reason}.",
            f"{clock(timeline.incident_opened_at)} UTC - {incident} opened by {cast.reliability_engineer.name}.",
            f"{clock(timeline.rollback_at)} UTC - release {cast.release_tag} rolled back.",
            f"{clock(timeline.resolved_at)} UTC - authorisation success rate returns to baseline.",
        ),
        section(
            "Customer impact",
            f"{world.customer_name} reported a declined payment of {world.amount_text}. "
            f"The payment reference quoted on the support ticket was {world.variant('transaction', 3)}.",
            "Twelve further authorisations from other merchants failed inside the same window with the "
            "identical upstream code, which is why this was treated as a platform incident and not a "
            "single-merchant dispute.",
        ),
        section(
            f"Telemetry: {AUTH_SERVICE}",
            f"Token validation p99 rose from 220ms to {8.4:.1f}s within 35 minutes of the release. "
            "Thread pool saturation is visible in the same window.",
            f"The regression was introduced by a synchronous revocation-list lookup added in "
            f"{cast.release_tag}; the lookup was not cached and contended on {SESSION_DB}.",
        ),
        section(
            f"Telemetry: {GATEWAY_SERVICE}",
            f"{GATEWAY_SERVICE} holds an authorisation session open until {AUTH_SERVICE} answers. "
            "With answers arriving after 8 seconds, the 64-connection pool was fully occupied.",
            "Once the pool was exhausted the gateway rejected new authorisations upstream, which is the "
            "code the merchant saw.",
        ),
        section(
            f"Telemetry: {LEDGER_SERVICE}",
            f"{LEDGER_SERVICE} recorded no write errors during the window. No funds moved for the failed "
            "authorisations, so no reconciliation was required.",
        ),
        section(
            "Candidate explanation 1 - fraud rule rejection",
            f"A velocity rule shipped to {FRAUD_SERVICE} at {clock(timeline.fraud_rule_deploy_at)} UTC on "
            f"{human_date(timeline.fraud_rule_deploy_at)} was the first suspect, and {world.fraud_incident_id} "
            "was raised for it.",
            f"The rule did block nine unrelated high-value card payments. It did not block {transaction}: "
            f"the {FRAUD_SERVICE} decision log records ALLOW for that authorisation.",
        ),
        section(
            "Candidate explanation 2 - network failure",
            f"{world.network_incident_id} describes transit packet loss in {cast.region}. That event is "
            f"dated {human_date(timeline.network_event_at)}, three days before this incident.",
            "Interface counters for the incident window show no loss, so the network candidate explanation does not "
            "survive the timeline.",
        ),
        section(
            "Candidate explanation 3 - insufficient balance",
            f"The account behind {world.variant('customer', 0)} had an available balance of "
            f"{world.data.focus_available_balance:,.2f} {world.data.focus_transaction.currency} at the time "
            f"of the attempt, against an authorisation of {world.amount_text}.",
            "The authorisation also never reached the issuer, so an issuer-side decline was not possible.",
        ),
        section(
            "Evidence inventory",
            "Gateway access logs, auth-service traces, the fraud decision log, interface counters, the "
            "customer statement and the payments dashboard screenshot were all reviewed.",
            f"The dashboard screenshot captured at {clock(timeline.incident_opened_at)} UTC shows "
            f"{transaction} in the failed state.",
        ),
        section(
            "Change management",
            f"The rollback of {cast.release_tag} was executed as an emergency change. The approval record "
            f"for that change is held in the incident approval memo for {incident}; version 2 of that memo "
            "is the current one.",
        ),
        section(
            "Contributing factors",
            "No canary stage existed for the revocation-list lookup, and the gateway had no bounded wait "
            f"on {AUTH_SERVICE}. Either control alone would have contained the incident.",
        ),
        section(
            "Root cause determination",
            world.key_finding,
            f"Confidence: high. The determination is supported by the {AUTH_SERVICE} trace sample, the "
            f"{GATEWAY_SERVICE} pool metric, the {FRAUD_SERVICE} ALLOW decision for {transaction} and the "
            "customer statement.",
        ),
        section(
            "Remediation",
            "Cache the revocation list with a 30-second TTL, add a 1.5-second bounded wait in "
            f"{GATEWAY_SERVICE}, and stage the next {AUTH_SERVICE} release behind a canary.",
        ),
        section(
            "Follow-up actions",
            f"ACT-1 owner {cast.auth_engineer.name}: ship the cache. ACT-2 owner {cast.payments_engineer.name}: "
            f"bounded wait. ACT-3 owner {cast.reliability_engineer.name}: canary stage. "
            f"All actions tracked against {incident}.",
        ),
    )


def _approval_memo(world: World, *, revision: int) -> DocumentSpec:
    cast, timeline = world.cast, world.cast.timeline
    approved = revision == 2
    verdict = (
        f"The change advisory board approved the emergency rollback out of band at "
        f"{clock(timeline.approval_at)} UTC on {human_date(timeline.approval_at)}. "
        f"Approver of record: {cast.approver.name}."
        if approved
        else (
            "At the time of writing the change advisory board had NOT approved the emergency rollback; "
            "the rollback proceeded under the incident commander's standing authority."
        )
    )
    return DocumentSpec(
        slug=f"approval-memo-{world.incident_id.lower()}-v{revision}",
        fmt=FORMAT_DOCX,
        title=f"Incident approval memo {world.incident_id} (revision {revision})",
        version=str(revision),
        version_status=VERSION_CURRENT if approved else VERSION_SUPERSEDED,
        occurred_at=timeline.approval_at if approved else timeline.incident_opened_at,
        tags=("approval", "contradiction", "incident"),
        entities=(world.incident_id, world.transaction_id),
        key_finding=verdict,
        sections=(
            section(
                f"Approval status for {world.incident_id}",
                verdict,
                f"Change: rollback of {AUTH_SERVICE} release {cast.release_tag}. "
                f"Requested by {cast.commander.name}.",
            ),
            section(
                "Revision note",
                (
                    f"Revision 2 supersedes revision 1, which was written at "
                    f"{clock(timeline.incident_opened_at)} UTC before the board answered."
                    if approved
                    else "Revision 1, written during the incident. Supersede this memo once the board answers."
                ),
            ),
        ),
    )


def _runbook(world: World) -> DocumentSpec:
    cast = world.cast
    pages = (
        section("Runbook: payment authorisation failures", "Owner: payments platform. Review cycle: quarterly."),
        section("Symptoms", "Authorisation success rate drops while ledger writes stay healthy."),
        section("First checks", f"Compare {GATEWAY_SERVICE} pool utilisation against {AUTH_SERVICE} p99."),
        section("Escalation", f"Page the {AUTH_SERVICE} owner, currently {cast.auth_engineer.name}."),
        section(
            "Connection pool exhaustion",
            f"If {GATEWAY_SERVICE} pool utilisation is at 100% and {AUTH_SERVICE} p99 is above 2 seconds, "
            "the gateway is blocked on authentication and the correct action is to roll back the most "
            f"recent {AUTH_SERVICE} release, not to restart the gateway.",
            "Restarting the gateway clears the symptom for roughly ninety seconds and then reproduces it.",
        ),
        section("Rollback procedure", "Emergency change ticket, then rollback, then confirm p99 recovery."),
        section("After the incident", "Write the post-mortem within two working days."),
    )
    return DocumentSpec(
        slug="runbook-payment-authorisation",
        fmt=FORMAT_PDF,
        title="Runbook: payment authorisation failures",
        sections=pages,
        key_section=4,
        key_finding="Pool exhaustion means roll back the auth-service release, not restart the gateway.",
        tags=("runbook", "procedure"),
        entities=(AUTH_SERVICE, GATEWAY_SERVICE),
    )


def _incident_report(world: World) -> DocumentSpec:
    sections = _incident_report_sections(world)
    if len(sections) != INCIDENT_REPORT_PAGES:
        raise ValueError(
            f"incident report must have exactly {INCIDENT_REPORT_PAGES} pages, got {len(sections)}"
        )
    return DocumentSpec(
        slug=f"incident-report-{world.incident_id.lower()}",
        fmt=FORMAT_PDF,
        title=f"Incident report {world.incident_id}: {world.data.root_incident.title}",
        sections=sections,
        version="2",
        version_status=VERSION_CURRENT,
        key_section=INCIDENT_REPORT_KEY_PAGE - 1,
        key_finding=world.key_finding,
        tags=("incident", "root_cause", "primary"),
        entities=(world.incident_id, world.transaction_id, world.customer_id),
        occurred_at=world.cast.timeline.resolved_at,
    )


def build_document_specs(world: World) -> tuple[DocumentSpec, ...]:
    """The full narrative document set, in a stable order."""
    return (
        _incident_report(world),
        postmortem(world),
        _approval_memo(world, revision=1),
        _approval_memo(world, revision=2),
        _runbook(world),
        fraud_rule_review(world),
        network_incident_report(world),
        customer_statement(world),
        meeting_minutes(world),
        architecture_deck(world),
        sharding_design(world),
        adr(world),
        changelog(world),
        wiki_page(world),
        oncall_handover(world),
        service_catalogue(world),
        capacity_plan(world),
        security_review(world),
        transaction_extract_xlsx(world),
        failed_transactions_csv(world),
    )
