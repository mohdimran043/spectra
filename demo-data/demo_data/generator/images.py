"""Generated screenshots and diagrams.

Each image is a real PNG with real rendered text, and each carries a
``.render.json`` sidecar recording exactly which strings were painted and
where.  The sidecar is the ground-truth OCR used by the fixture ingestion path
and by the evaluation corpus loader; a machine with a working OCR model reads
the pixels instead.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Final

from spectra_config.logging import get_logger

from .canvas import (
    ACCENT,
    BODY_SIZE,
    DANGER,
    HEADING_SIZE,
    MUTED,
    SMALL_SIZE,
    SUCCESS,
    TITLE_SIZE,
    WARNING,
    Sheet,
)
from .constants import (
    ARCHITECTURE_DATABASE_NODES,
    FILLER_IMAGE_HEIGHT,
    FILLER_IMAGE_WIDTH,
    IMAGE_HEIGHT,
    IMAGE_WIDTH,
    IMAGES_DIR,
)
from .rng import clock, iso, iso_date, make_rng, pick
from .story import AUTH_SERVICE, FRAUD_SERVICE, GATEWAY_SERVICE, SESSION_DB
from .world import STREAM_IMAGES, World

log = get_logger(__name__)

MEDIA_TYPE: Final[str] = "image/png"
SIDECAR_SUFFIX: Final[str] = ".render.json"
#: Decoy topology - two database nodes, so the three-node question stays crisp.
DECOY_DATABASE_NODES: Final[int] = 2
LATENCY_SERIES: Final[tuple[float, ...]] = (
    0.22, 0.24, 0.21, 0.25, 0.9, 2.4, 4.8, 6.9, 8.4, 8.1, 7.6, 3.2, 0.7, 0.26, 0.23,
)
POOL_SERIES: Final[tuple[float, ...]] = (22, 25, 24, 31, 44, 58, 64, 64, 64, 64, 61, 38, 26, 24, 23)


@dataclass(frozen=True)
class ImageArtifact:
    image_id: str
    slug: str
    path: str
    sidecar_path: str
    media_type: str
    title: str
    kind: str
    tags: tuple[str, ...]
    entities: tuple[str, ...]
    database_nodes: int
    text: str
    size_bytes: int


@dataclass(frozen=True)
class ImageSpec:
    slug: str
    kind: str
    title: str
    tags: tuple[str, ...]
    entities: tuple[str, ...]
    database_nodes: int
    render: Callable[[World, Sheet], None]


def _header(sheet: Sheet, world: World, title: str, subtitle: str) -> None:
    sheet.panel((0, 0, sheet.width, 74))
    sheet.text((28, 20), title, size=TITLE_SIZE, bold=True, role="title")
    sheet.text((28, 92), subtitle, size=SMALL_SIZE, colour=MUTED, role="subtitle")
    del world


def _payments_dashboard(world: World, sheet: Sheet) -> None:
    transaction = world.data.focus_transaction
    _header(sheet, world, "Payments Operations Console", f"Environment: production | {iso(transaction.created_at)}")
    sheet.panel((24, 128, sheet.width - 24, 470))
    sheet.text((44, 146), "Recent authorisations", size=HEADING_SIZE, bold=True, role="heading")
    rows = [
        (transaction.transaction_id, transaction.customer_id, f"{transaction.amount:.2f}",
         transaction.currency, "failed", transaction.failure_reason or ""),
    ]
    for row in world.data.transactions[:4]:
        rows.append(
            (row.transaction_id, row.customer_id, f"{row.amount:.2f}", row.currency, row.status,
             row.failure_reason or "-")
        )
    sheet.table((44, 192), ("TRANSACTION", "CUSTOMER", "AMOUNT", "CCY", "STATUS", "REASON"),
                rows, (220, 170, 130, 80, 120, 260), highlight_row=0)
    sheet.panel((24, 496, sheet.width - 24, 690))
    sheet.text((44, 512), f"Incident linked: {world.incident_id}", size=BODY_SIZE, colour=WARNING, role="metric")
    sheet.text((44, 548), f"Customer: {world.customer_name} ({world.customer_id})", size=BODY_SIZE, role="metric")
    sheet.text((44, 584), f"Failure code: {transaction.failure_reason}", size=BODY_SIZE, colour=DANGER,
               role="metric")
    sheet.text((44, 620), f"Gateway: {GATEWAY_SERVICE} | Upstream: {AUTH_SERVICE}", size=BODY_SIZE,
               colour=MUTED, role="metric")


def _architecture_diagram(world: World, sheet: Sheet) -> None:
    _header(sheet, world, "Target Architecture - Session Store", f"Design review | {SESSION_DB} sharding")
    sheet.node((60, 150, 330, 240), AUTH_SERVICE, "token validation")
    sheet.node((60, 300, 330, 390), GATEWAY_SERVICE, "authorisation path")
    labels = ("shard-a", "shard-b", "shard-c")
    for index in range(ARCHITECTURE_DATABASE_NODES):
        top = 140 + index * 170
        sheet.node((760, top, 1080, top + 120), f"{SESSION_DB} {labels[index]}", "database node",
                   accent=SUCCESS, role="database_node")
        sheet.arrow((330, 195 + index * 10), (760, top + 60))
    sheet.text((60, 470), f"{ARCHITECTURE_DATABASE_NODES} database nodes, one per tenant band",
               size=BODY_SIZE, colour=MUTED, role="caption")
    sheet.text((60, 510), f"Owner: {world.cast.data_architect.name}", size=SMALL_SIZE, colour=MUTED,
               role="caption")


def _current_topology(world: World, sheet: Sheet) -> None:
    _header(sheet, world, "Current Architecture - Session Store", "Before the sharding change")
    sheet.node((60, 180, 340, 270), AUTH_SERVICE, "token validation")
    for index, label in enumerate(("primary", "replica")):
        top = 160 + index * 200
        sheet.node((760, top, 1080, top + 120), f"{SESSION_DB} {label}", "database node", accent=WARNING,
                   role="database_node")
        sheet.arrow((340, 225), (760, top + 60))
    sheet.text((60, 470), f"{DECOY_DATABASE_NODES} database nodes today", size=BODY_SIZE, colour=MUTED,
               role="caption")


def _error_dialog(world: World, sheet: Sheet) -> None:
    transaction = world.data.focus_transaction
    _header(sheet, world, "Checkout", "Merchant portal")
    sheet.panel((280, 180, 1000, 520))
    sheet.text((320, 210), "Authorisation failed", size=TITLE_SIZE, bold=True, colour=DANGER, role="heading")
    sheet.text((320, 280), "The payment could not be authorised because the", size=BODY_SIZE, role="body")
    sheet.text((320, 312), "authentication service did not respond in time.", size=BODY_SIZE, role="body")
    sheet.text((320, 368), f"Reference: {transaction.transaction_id}", size=BODY_SIZE, mono=True, role="body")
    sheet.text((320, 404), f"Code: {transaction.failure_reason}", size=BODY_SIZE, mono=True, colour=DANGER,
               role="body")
    sheet.text((320, 448), f"Time: {iso(transaction.created_at)}", size=SMALL_SIZE, colour=MUTED, role="body")


def _latency_graph(world: World, sheet: Sheet) -> None:
    timeline = world.cast.timeline
    _header(sheet, world, f"{AUTH_SERVICE} token validation p99", f"{iso_date(timeline.deploy_at)} UTC")
    sheet.chart((60, 150, sheet.width - 60, 520), LATENCY_SERIES, colour=DANGER)
    sheet.text((60, 548), "Peak p99: 8.4 s", size=HEADING_SIZE, bold=True, colour=DANGER, role="metric")
    sheet.text((60, 590), f"Release {world.cast.release_tag} deployed {clock(timeline.deploy_at)} UTC",
               size=BODY_SIZE, colour=MUTED, role="metric")
    sheet.text((60, 626), f"Rolled back {clock(timeline.rollback_at)} UTC under {world.incident_id}",
               size=BODY_SIZE, colour=MUTED, role="metric")


def _pool_graph(world: World, sheet: Sheet) -> None:
    _header(sheet, world, f"{GATEWAY_SERVICE} authorisation pool", "Connections in use, 64 available")
    sheet.chart((60, 150, sheet.width - 60, 520), POOL_SERIES, colour=WARNING)
    sheet.text((60, 548), "Saturated at 64 of 64 connections", size=HEADING_SIZE, bold=True, colour=WARNING,
               role="metric")
    sheet.text((60, 590), f"Blocked on {AUTH_SERVICE}; see {world.incident_id}", size=BODY_SIZE, colour=MUTED,
               role="metric")


def _network_topology(world: World, sheet: Sheet) -> None:
    _header(sheet, world, "Network Topology", f"{world.cast.region} edge")
    sheet.node((60, 200, 300, 290), "edge-router-01", "transit A")
    sheet.node((400, 200, 640, 290), "core-switch-01", "spine")
    sheet.node((740, 140, 1010, 230), GATEWAY_SERVICE, "egress")
    sheet.node((740, 300, 1010, 390), AUTH_SERVICE, "internal")
    sheet.arrow((300, 245), (400, 245))
    sheet.arrow((640, 245), (740, 185))
    sheet.arrow((640, 245), (740, 345))
    sheet.text((60, 460), f"Packet loss recorded {iso_date(world.cast.timeline.network_event_at)} only",
               size=BODY_SIZE, colour=MUTED, role="caption")
    sheet.text((60, 500), f"See {world.network_incident_id}", size=BODY_SIZE, colour=MUTED, role="caption")


def _fraud_console(world: World, sheet: Sheet) -> None:
    transaction = world.data.focus_transaction
    _header(sheet, world, f"{FRAUD_SERVICE} decision console", "Rule evaluation log")
    sheet.panel((24, 128, sheet.width - 24, 430))
    sheet.table(
        (44, 160),
        ("TRANSACTION", "DECISION", "SCORE", "RULE"),
        (
            (transaction.transaction_id, "ALLOW", "0.11", "none matched"),
            (world.data.transactions[1].transaction_id, "BLOCK", "0.88", "velocity-high-value"),
        ),
        (260, 160, 120, 320),
    )
    sheet.text((44, 470), f"{transaction.transaction_id} was not blocked by any fraud rule", size=BODY_SIZE,
               colour=SUCCESS, role="metric")
    sheet.text((44, 510), f"Rule incident: {world.fraud_incident_id}", size=BODY_SIZE, colour=MUTED,
               role="metric")


def _incident_board(world: World, sheet: Sheet) -> None:
    incident = world.data.root_incident
    _header(sheet, world, "Incident Board", f"{incident.severity.upper()} | {incident.status}")
    sheet.panel((24, 128, sheet.width - 24, 520))
    sheet.text((44, 156), incident.incident_id, size=TITLE_SIZE, bold=True, colour=ACCENT, role="heading")
    sheet.text((44, 214), incident.title, size=BODY_SIZE, role="body")
    sheet.text((44, 262), f"Service: {incident.service}", size=BODY_SIZE, colour=MUTED, role="body")
    sheet.text((44, 302), f"Opened: {iso(incident.opened_at)}", size=BODY_SIZE, colour=MUTED, role="body")
    sheet.text((44, 342), f"Commander: {world.cast.commander.name}", size=BODY_SIZE, colour=MUTED, role="body")
    sheet.text((44, 382), f"Linked transaction: {world.transaction_id}", size=BODY_SIZE, role="body")
    sheet.text((44, 422), f"Linked customer: {world.customer_id}", size=BODY_SIZE, role="body")


def _terminal(world: World, sheet: Sheet) -> None:
    timeline = world.cast.timeline
    _header(sheet, world, "gateway-edge-01 : journalctl", f"{GATEWAY_SERVICE}")
    lines = (
        f"{clock(timeline.transaction_at)}:02 WARN  auth call exceeded 8000ms txn={world.transaction_id}",
        f"{clock(timeline.transaction_at)}:03 ERROR pool exhausted size=64 waiters=37",
        f"{clock(timeline.transaction_at)}:03 ERROR authorisation rejected reason=upstream_auth_timeout",
        f"{clock(timeline.incident_opened_at)}:11 INFO  incident {world.incident_id} opened",
    )
    for index, line in enumerate(lines):
        sheet.text((44, 150 + index * 38), line, size=SMALL_SIZE, mono=True,
                   colour=DANGER if "ERROR" in line else MUTED, role="log")


def _approval_email(world: World, sheet: Sheet) -> None:
    cast = world.cast
    _header(sheet, world, "Mail - Change Advisory Board", "Emergency change approval")
    sheet.panel((24, 128, sheet.width - 24, 520))
    sheet.text((44, 156), f"From: {cast.approver.name} <{cast.approver.email}>", size=BODY_SIZE, role="body")
    sheet.text((44, 200), f"Sent: {iso(cast.timeline.approval_at)}", size=BODY_SIZE, colour=MUTED, role="body")
    sheet.text((44, 244), f"Subject: APPROVED - emergency rollback for {world.incident_id}", size=BODY_SIZE,
               bold=True, colour=SUCCESS, role="body")
    sheet.text((44, 306), f"The board approves the rollback of {AUTH_SERVICE} release", size=BODY_SIZE,
               role="body")
    sheet.text((44, 342), f"{cast.release_tag} out of band. Approver of record: {cast.approver.name}.",
               size=BODY_SIZE, role="body")


def _account_screen(world: World, sheet: Sheet) -> None:
    customer = world.data.focus_customer
    transaction = world.data.focus_transaction
    _header(sheet, world, "Customer Account", customer.name)
    sheet.panel((24, 128, sheet.width - 24, 520))
    sheet.text((44, 156), f"Customer {customer.customer_id}", size=TITLE_SIZE, bold=True, role="heading")
    sheet.text((44, 220), f"Segment: {customer.segment} | Country: {customer.country}", size=BODY_SIZE,
               colour=MUTED, role="body")
    sheet.text((44, 264), f"Available balance: {world.data.focus_available_balance:,.2f} "
                          f"{transaction.currency}", size=BODY_SIZE, colour=SUCCESS, role="body")
    sheet.text((44, 308), f"Declined authorisation: {transaction.transaction_id} for "
                          f"{transaction.amount:,.2f} {transaction.currency}", size=BODY_SIZE, colour=DANGER,
               role="body")
    sheet.text((44, 352), "Balance was sufficient at the time of the attempt", size=BODY_SIZE, colour=MUTED,
               role="body")


def build_image_specs(world: World) -> tuple[ImageSpec, ...]:
    del world
    return (
        ImageSpec("dashboard-payments-console", "dashboard", "Payments operations console",
                  ("dashboard", "screenshot", "primary"), (), 0, _payments_dashboard),
        ImageSpec("diagram-target-architecture", "diagram", "Target architecture, session store",
                  ("diagram", "architecture"), (), ARCHITECTURE_DATABASE_NODES, _architecture_diagram),
        ImageSpec("diagram-current-topology", "diagram", "Current architecture, session store",
                  ("diagram", "architecture", "decoy"), (), DECOY_DATABASE_NODES, _current_topology),
        ImageSpec("screenshot-error-dialog", "error_dialog", "Checkout authorisation error",
                  ("screenshot", "error"), (), 0, _error_dialog),
        ImageSpec("chart-auth-latency", "chart", "Auth service p99 latency", ("chart", "monitoring"), (), 0,
                  _latency_graph),
        ImageSpec("chart-gateway-pool", "chart", "Gateway authorisation pool", ("chart", "monitoring"), (), 0,
                  _pool_graph),
        ImageSpec("diagram-network-topology", "topology", "Network topology", ("diagram", "network"), (), 0,
                  _network_topology),
        ImageSpec("screenshot-fraud-console", "console", "Fraud decision console",
                  ("screenshot", "fraud", "disproof"), (), 0, _fraud_console),
        ImageSpec("screenshot-incident-board", "board", "Incident board", ("screenshot", "incident"), (), 0,
                  _incident_board),
        ImageSpec("screenshot-gateway-terminal", "terminal", "Gateway log terminal",
                  ("screenshot", "logs"), (), 0, _terminal),
        ImageSpec("screenshot-approval-email", "email", "Change board approval mail",
                  ("screenshot", "approval", "contradiction"), (), 0, _approval_email),
        ImageSpec("screenshot-customer-account", "account", "Customer account screen",
                  ("screenshot", "customer", "disproof"), (), 0, _account_screen),
    )


def _write_sidecar(path: Path, image_id: str, sheet: Sheet) -> str:
    blocks = [
        {"text": drawn.text, "box": list(drawn.box), "role": drawn.role} for drawn in sheet.drawn
    ]
    text = "\n".join(drawn.text for drawn in sheet.drawn)
    payload = {"image_id": image_id, "source": "generated", "blocks": blocks, "text": text}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return text


def _render(spec: ImageSpec, world: World, image_id: str, directory: Path, out_dir: Path) -> ImageArtifact:
    sheet = Sheet(IMAGE_WIDTH, IMAGE_HEIGHT)
    spec.render(world, sheet)
    sheet.text((IMAGE_WIDTH - 260, IMAGE_HEIGHT - 40), f"Image {image_id}", size=SMALL_SIZE, colour=MUTED,
               role="watermark")
    path = directory / f"{spec.slug}.png"
    sheet.save(path)
    sidecar = directory / f"{spec.slug}{SIDECAR_SUFFIX}"
    text = _write_sidecar(sidecar, image_id, sheet)
    return ImageArtifact(
        image_id=image_id,
        slug=spec.slug,
        path=path.relative_to(out_dir).as_posix(),
        sidecar_path=sidecar.relative_to(out_dir).as_posix(),
        media_type=MEDIA_TYPE,
        title=spec.title,
        kind=spec.kind,
        tags=spec.tags,
        entities=spec.entities,
        database_nodes=spec.database_nodes,
        text=text,
        size_bytes=path.stat().st_size,
    )


def _filler(world: World, image_id: str, index: int, directory: Path, out_dir: Path) -> ImageArtifact:
    rng = make_rng(world.seed, f"{STREAM_IMAGES}-filler-{index}")
    asset = pick(rng, list(world.data.assets))
    sheet = Sheet(FILLER_IMAGE_WIDTH, FILLER_IMAGE_HEIGHT)
    sheet.text((16, 16), f"{asset.service} panel", size=BODY_SIZE, bold=True, role="title")
    sheet.text((16, 56), f"Asset {asset.asset_id}", size=SMALL_SIZE, colour=MUTED, role="body")
    sheet.text((16, 90), f"Environment {asset.environment}", size=SMALL_SIZE, colour=MUTED, role="body")
    sheet.text((16, 124), f"Image {image_id}", size=SMALL_SIZE, colour=MUTED, role="watermark")
    slug = f"panel-{index:06d}"
    path = directory / f"{slug}.png"
    sheet.save(path)
    sidecar = directory / f"{slug}{SIDECAR_SUFFIX}"
    text = _write_sidecar(sidecar, image_id, sheet)
    return ImageArtifact(
        image_id=image_id, slug=slug, path=path.relative_to(out_dir).as_posix(),
        sidecar_path=sidecar.relative_to(out_dir).as_posix(), media_type=MEDIA_TYPE,
        title=f"{asset.service} panel {index}", kind="panel", tags=("filler",),
        entities=(asset.asset_id,), database_nodes=0, text=text, size_bytes=path.stat().st_size,
    )


def generate_images(world: World, out_dir: Path) -> tuple[ImageArtifact, ...]:
    """Render the narrative images, then cheap filler panels up to the tier size."""
    directory = out_dir / IMAGES_DIR
    directory.mkdir(parents=True, exist_ok=True)
    specs = build_image_specs(world)
    artifacts = [_render(spec, world, world.ids.image(), directory, out_dir) for spec in specs]
    for index in range(max(0, world.scale.images - len(specs))):
        artifacts.append(_filler(world, world.ids.image(), index, directory, out_dir))
    log.info("demo_data.images_generated", count=len(artifacts), directory=str(directory))
    return tuple(artifacts)
