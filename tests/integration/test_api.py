"""API surface tests driven through the real ASGI app (lifespan included)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def client(request):
    """Boot the real application once for this module."""
    from fastapi.testclient import TestClient
    from spectra_api.main import create_app

    with TestClient(create_app()) as c:
        yield c


class TestHealth:
    def test_liveness_never_touches_a_dependency(self, client):
        response = client.get("/api/health/live")
        assert response.status_code == 200
        assert response.json() == {"status": "alive"}

    def test_health_reports_every_component(self, client):
        body = client.get("/api/health").json()
        assert body["version"] == "1.0.0"
        for component in ("vectors", "lexical", "graph", "objects", "cache", "relational", "models"):
            assert component in body["components"], component

    def test_health_names_the_active_backends(self, client):
        backends = client.get("/api/health").json()["components"]["backends"]
        assert backends["relational"] == "sqlite"
        assert backends["vector"] == "embedded"

    def test_model_state_is_reported_honestly(self, client):
        """Health must mirror the real hardware, and never claim a capability it lacks.

        Asserting a specific environment would make this test wrong the moment the
        GPU appears (or disappears), so it checks the invariant instead: the
        reported GPU state matches what detection actually finds, and any degraded
        status carries a reason explaining it.
        """
        from spectra_ai_core.gpu import detect_gpu
        from spectra_config import get_settings

        models = client.get("/api/health").json()["components"]["models"]
        assert models["gpu_available"] is detect_gpu(get_settings()).available
        if models["status"] == "degraded":
            assert models["detail"], "a degraded model layer must say why"


class TestCorrelation:
    def test_every_response_carries_a_request_id(self, client):
        assert client.get("/api/health/live").headers["X-Request-ID"].startswith("req_")

    def test_supplied_request_id_is_echoed(self, client):
        response = client.get("/api/health/live", headers={"X-Request-ID": "req_caller_supplied"})
        assert response.headers["X-Request-ID"] == "req_caller_supplied"

    def test_response_time_header_is_present(self, client):
        assert "X-Response-Time-Ms" in client.get("/api/health/live").headers


class TestErrorEnvelope:
    def test_unknown_route_uses_the_error_envelope(self, client):
        body = client.get("/api/does-not-exist").json()
        assert body["error"] == "not_found"
        assert "request_id" in body

    def test_schema_violation_returns_422_with_details(self, client):
        body = client.post("/api/search", json={"top_k": "not-an-integer"}).json()
        assert body["error"] == "schema_violation"
        assert body["detail"]["errors"]

    def test_unknown_role_is_rejected(self, client):
        """`/api/health` takes no permission context, so probe a route that does."""
        response = client.get("/api/agents/status", headers={"X-Spectra-Role": "superuser"})
        assert response.status_code == 403
        assert response.json()["error"] == "permission_denied"
        assert "superuser" in response.json()["reason"]


class TestPermissions:
    def test_viewer_may_not_run_sql(self, client):
        response = client.post(
            "/api/database/query",
            json={"source_id": "src_x", "question": "anything"},
            headers={"X-Spectra-Role": "viewer"},
        )
        assert response.status_code == 403
        assert "may not run_sql" in response.json()["reason"]

    def test_analyst_may_not_manage_sources(self, client):
        response = client.post(
            "/api/sources",
            json={"name": "x", "type": "local_folder"},
            headers={"X-Spectra-Role": "analyst"},
        )
        assert response.status_code == 403

    def test_viewer_may_not_upload(self, client):
        response = client.post(
            "/api/uploads",
            files={"file": ("a.txt", b"hello", "text/plain")},
            headers={"X-Spectra-Role": "viewer"},
        )
        assert response.status_code == 403


class TestSourceSecrets:
    def test_inline_secrets_in_connection_are_rejected(self, client):
        """Credentials must go to the credential store, never into the descriptor."""
        response = client.post(
            "/api/sources",
            json={
                "name": "leaky",
                "type": "postgres",
                "connection": {"host": "db", "password": "hunter2"},
            },
            headers={"X-Spectra-Role": "admin"},
        )
        assert response.status_code == 400
        assert response.json()["error"] == "validation_rejected"
        assert "password" in response.json()["reason"]


class TestAgentControlCenter:
    def test_status_lists_every_agent_with_alternatives(self, client):
        agents = client.get("/api/agents/status").json()
        names = {a["name"] for a in agents}
        assert {"document", "image", "video", "audio", "database", "graph",
                "entity_resolution", "claim", "disproof", "verifier"} <= names
        for agent in agents:
            assert agent["alternatives"], f"{agent['name']} must offer alternatives"

    def test_toggling_requires_admin(self, client):
        assert client.patch(
            "/api/agents/image", json={"enabled": False}, headers={"X-Spectra-Role": "analyst"}
        ).status_code == 403

    def test_admin_can_disable_and_reenable_an_agent(self, client):
        admin = {"X-Spectra-Role": "admin"}
        assert client.patch("/api/agents/image", json={"enabled": False}, headers=admin).status_code == 200
        disabled = next(a for a in client.get("/api/agents/status").json() if a["name"] == "image")
        assert disabled["enabled"] is False
        assert disabled["state"] == "disabled"
        assert disabled["reason"]
        assert disabled["alternatives"]

        client.patch("/api/agents/image", json={"enabled": True}, headers=admin)
        assert next(a for a in client.get("/api/agents/status").json() if a["name"] == "image")["enabled"]

    def test_unknown_agent_is_404(self, client):
        assert client.patch(
            "/api/agents/telepathy", json={"enabled": False}, headers={"X-Spectra-Role": "admin"}
        ).status_code == 404


class TestModelsDashboard:
    def test_model_status_exposes_every_role_and_the_real_gpu_state(self, client):
        from spectra_ai_core.gpu import detect_gpu
        from spectra_config import get_settings

        body = client.get("/api/models").json()
        assert body["profile"]
        detected = detect_gpu(get_settings())
        assert body["gpu"]["available"] is detected.available
        if not detected.available:
            assert body["gpu"]["detail"], "an unavailable GPU must explain itself"
        roles = {m["role"] for m in body["models"]}
        assert {"fast_brain", "deep_brain", "vision", "embedding", "reranker", "speech", "ocr"} <= roles

    def test_every_role_records_its_selected_candidate_or_why_not(self, client):
        for model in client.get("/api/models").json()["models"]:
            assert model["active_runtime"] or model["degraded_reason"], model["role"]

    def test_unknown_role_unload_is_404(self, client):
        assert client.post(
            "/api/models/telepathy/unload", headers={"X-Spectra-Role": "admin"}
        ).status_code == 404


class TestMetrics:
    def test_json_metrics_include_counters(self, client):
        body = client.get("/api/metrics").json()
        assert "counters" in body and "latency" in body and "catalog" in body

    def test_prometheus_exposition(self, client):
        response = client.get("/api/metrics", headers={"Accept": "text/plain"})
        assert response.headers["content-type"].startswith("text/plain")
        assert "spectra_" in response.text


class TestDemoScenarios:
    def test_six_scenarios_are_published(self, client):
        scenarios = client.get("/api/demo/scenarios").json()
        assert len(scenarios) == 6
        ids = {s["id"] for s in scenarios}
        assert {"image-to-database", "text-to-video", "database-to-documents",
                "investigation", "contradiction", "timeline"} == ids

    def test_each_scenario_has_a_narrative_and_a_question(self, client):
        for scenario in client.get("/api/demo/scenarios").json():
            assert scenario["narrative"] and scenario["question"] and scenario["expects"]

    def test_unknown_scenario_is_404(self, client):
        assert client.post("/api/demo/run/nope", headers={"X-Spectra-Role": "admin"}).status_code == 404


class TestOpenAPI:
    def test_schema_generates(self, client):
        schema = client.get("/openapi.json").json()
        assert schema["info"]["title"] == "SPECTRA"

    def test_documented_routes_exist(self, client):
        paths = client.get("/openapi.json").json()["paths"]
        for route in (
            "/api/health", "/api/metrics", "/api/search", "/api/uploads",
            "/api/investigations", "/api/database/query", "/api/sources",
            "/api/models", "/api/agents/status", "/api/stream/investigation/{investigation_id}",
        ):
            assert route in paths, route
