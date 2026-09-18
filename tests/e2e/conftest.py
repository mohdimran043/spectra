"""Fixtures for the acceptance scenarios.

These build a small but genuinely multimodal corpus, ingest it through the real
pipeline, and hand the tests a live service container.  Nothing is mocked: the
point of these tests is that the whole stack does the thing.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

TX, CUSTOMER, INCIDENT = "TX82931", "C82731", "INC1829"
OTHER_TX = "TX77120"


def _write_incident_pdf(path: Path) -> None:
    import pymupdf

    doc = pymupdf.open()
    for section in range(1, 4):
        page = doc.new_page()
        page.insert_text((60, 70), f"Operations Handbook - Section {section}", fontsize=15)
        page.insert_text((60, 105), "Routine capacity and rota notes.", fontsize=11)
    page = doc.new_page()
    page.insert_text((60, 70), "Authentication", fontsize=17)
    page.insert_text((60, 105), f"Incident {INCIDENT} post-mortem for transaction {TX}.", fontsize=11)
    page.insert_text((60, 130), "The authentication service connection pool was exhausted at 10:42.", fontsize=11)
    page.insert_text((60, 155), f"Payment for customer {CUSTOMER} failed with an auth timeout.", fontsize=11)
    page.insert_text((60, 180), "No fraud rule fired and the balance was sufficient.", fontsize=11)
    doc.save(str(path))
    doc.close()


def _write_approval_versions(approved: Path, superseded: Path) -> None:
    """Two versions of one memo that disagree - the contradiction case."""
    import pymupdf

    for path, verdict, status in ((approved, "approved", "v2 approved"), (superseded, "rejected", "v1 superseded")):
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((60, 70), "Incident Approval Memo", fontsize=16)
        page.insert_text((60, 105), f"Incident {INCIDENT} was {verdict} by the risk board.", fontsize=11)
        page.insert_text((60, 130), f"Document status: {status}.", fontsize=11)
        doc.save(str(path))
        doc.close()


def _write_console_screenshot(path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (740, 250), "white")
    draw = ImageDraw.Draw(image)
    try:
        title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 26)
        body = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 21)
    except OSError:  # pragma: no cover - font-dependent
        title = body = ImageFont.load_default()
    draw.text((28, 22), "Payment Gateway Console", fill="black", font=title)
    draw.text((28, 84), f"Transaction: {TX}", fill="black", font=body)
    draw.text((28, 122), f"Customer: {CUSTOMER}", fill="black", font=body)
    draw.text((28, 160), "Status: FAILED", fill="black", font=body)
    draw.text((28, 198), f"Incident: {INCIDENT}", fill="black", font=body)
    image.save(path)


def _write_enterprise_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE customers(customer_id TEXT PRIMARY KEY, name TEXT, email TEXT, segment TEXT,
            country TEXT, risk_score REAL, created_at TEXT, status TEXT);
        CREATE TABLE incidents(incident_id TEXT PRIMARY KEY, title TEXT, severity TEXT, status TEXT,
            category TEXT, root_cause TEXT, service TEXT, opened_at TEXT, resolved_at TEXT,
            approved INTEGER, approved_by TEXT);
        CREATE TABLE transactions(transaction_id TEXT PRIMARY KEY, customer_id TEXT, amount REAL,
            currency TEXT, status TEXT, method TEXT, failure_reason TEXT, created_at TEXT,
            updated_at TEXT, incident_id TEXT,
            FOREIGN KEY(customer_id) REFERENCES customers(customer_id),
            FOREIGN KEY(incident_id) REFERENCES incidents(incident_id));
        """
    )
    connection.execute(
        "INSERT INTO customers VALUES(?,?,?,?,?,?,?,?)",
        (CUSTOMER, "Mohammed Imran", "m.imran@example.com", "enterprise", "QA", 0.21,
         "2024-02-01T09:00:00Z", "active"),
    )
    connection.execute(
        "INSERT INTO incidents VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (INCIDENT, "Authentication service degradation", "sev2", "resolved", "availability",
         "Authentication service connection pool exhausted", "auth-api",
         "2026-03-11T10:45:12Z", "2026-03-11T12:02:10Z", 1, "l.ashford"),
    )
    connection.execute(
        "INSERT INTO transactions VALUES(?,?,?,?,?,?,?,?,?,?)",
        (TX, CUSTOMER, 482.50, "EUR", "FAILED", "card", "auth_timeout",
         "2026-03-11T10:42:01Z", "2026-03-11T10:42:07Z", INCIDENT),
    )
    # A second customer with more than five failed payments, for the aggregation case.
    connection.execute(
        "INSERT INTO customers VALUES(?,?,?,?,?,?,?,?)",
        ("C90001", "Verdemar Holdings", "ops@verdemar.example", "enterprise", "ES", 0.55,
         "2024-03-01T09:00:00Z", "active"),
    )
    for index in range(1, 8):
        connection.execute(
            "INSERT INTO transactions VALUES(?,?,?,?,?,?,?,?,?,?)",
            (f"TX7{index:04d}", "C90001", 25.0 * index, "EUR", "FAILED", "card",
             "insufficient_funds", "2026-03-10T08:00:00Z", "2026-03-10T08:00:05Z", None),
        )
    connection.commit()
    connection.close()


@pytest.fixture(scope="session")
def corpus(isolated_environment) -> dict[str, Path]:
    """Generate the multimodal fixture corpus once per session."""
    root = Path(isolated_environment) / "corpus"
    root.mkdir(parents=True, exist_ok=True)
    paths = {
        "incident_pdf": root / "Incident_Report.pdf",
        "approved_memo": root / "Approval_Memo_v2.pdf",
        "superseded_memo": root / "Approval_Memo_v1.pdf",
        "screenshot": root / "console.png",
        "enterprise_db": Path(isolated_environment) / "runtime" / "enterprise.db",
    }
    _write_incident_pdf(paths["incident_pdf"])
    _write_approval_versions(paths["approved_memo"], paths["superseded_memo"])
    _write_console_screenshot(paths["screenshot"])
    _write_enterprise_db(paths["enterprise_db"])
    return paths


@pytest.fixture(scope="session")
async def live_container(corpus):
    """A fully wired container with the fixture corpus ingested."""
    from spectra_api.container import build_container, shutdown_container

    container = await build_container()
    for key in ("incident_pdf", "approved_memo", "superseded_memo", "screenshot"):
        path = corpus[key]
        job = await container.ingestion.ingest_upload(
            filename=path.name,
            data=path.read_bytes(),
            source_id="src_uploads",
            permissions=["admin", "analyst", "viewer"],
        )
        await container.ingestion.process_job(job.job_id)
    yield container
    await shutdown_container()


@pytest.fixture
def analyst():
    from spectra_schemas import PermissionContext, Role

    return PermissionContext(user_id="acceptance", role=Role.ANALYST)
