"""Permission model, budgets and tool-schema validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from spectra_config.budgets import budget_for
from spectra_schemas import PermissionContext, Role
from spectra_tool_contracts import SchemaViolation, apply_defaults, array, integer, obj, string, validate


class TestPermissionContext:
    def test_role_capabilities_are_distinct(self):
        admin = PermissionContext(role=Role.ADMIN)
        analyst = PermissionContext(role=Role.ANALYST)
        viewer = PermissionContext(role=Role.VIEWER)

        assert admin.can("manage_sources") and admin.can("run_sql")
        assert analyst.can("run_sql") and not analyst.can("manage_sources")
        assert viewer.can("search") and not viewer.can("run_sql") and not viewer.can("upload")

    def test_denied_sources_win_over_everything(self):
        ctx = PermissionContext(role=Role.ADMIN, denied_sources=["src_secret"])
        assert not ctx.may_read_source("src_secret")
        assert ctx.may_read_source("src_public")

    def test_allowlist_restricts_when_present(self):
        ctx = PermissionContext(role=Role.ANALYST, source_access=["src_a"])
        assert ctx.may_read_source("src_a")
        assert not ctx.may_read_source("src_b")

    def test_empty_allowlist_means_all_sources(self):
        assert PermissionContext(role=Role.ANALYST).may_read_source("anything")

    def test_source_permission_list_is_enforced(self):
        ctx = PermissionContext(role=Role.VIEWER)
        assert not ctx.may_read_source("src", ["admin", "analyst"])
        assert ctx.may_read_source("src", ["admin", "analyst", "viewer"])

    def test_cache_key_separates_roles(self):
        """A cached result must never cross a role boundary."""
        assert PermissionContext(role=Role.ADMIN).cache_key() != PermissionContext(role=Role.VIEWER).cache_key()

    def test_cache_key_separates_source_scopes(self):
        a = PermissionContext(role=Role.ANALYST, source_access=["src_a"])
        b = PermissionContext(role=Role.ANALYST, source_access=["src_b"])
        assert a.cache_key() != b.cache_key()

    def test_context_is_immutable(self):
        ctx = PermissionContext(role=Role.VIEWER)
        with pytest.raises(ValidationError):
            ctx.role = Role.ADMIN


class TestBudgets:
    def test_fast_is_strictly_cheaper_than_deep(self, settings):
        fast, deep = budget_for("fast", settings), budget_for("deep", settings)
        assert fast.max_tool_calls < deep.max_tool_calls
        assert fast.max_latency_seconds < deep.max_latency_seconds
        assert fast.max_iterations < deep.max_iterations
        assert fast.allow_gpu_heavy is False and deep.allow_gpu_heavy is True

    def test_budgets_are_immutable_and_tighten_by_copy(self, settings):
        budget = budget_for("deep", settings)
        tighter = budget.tightened(max_tool_calls=3)
        assert budget.max_tool_calls != 3
        assert tighter.max_tool_calls == 3

    def test_unknown_mode_defaults_to_deep(self, settings):
        assert budget_for("something-else", settings).mode == "deep"


class TestToolSchemaValidation:
    SCHEMA = obj(
        {
            "query": string("what to search for"),
            "top_k": integer(minimum=1, maximum=100, default=10),
            "modalities": array(string(), max_items=3),
        },
        required=["query"],
    )

    def test_valid_arguments_pass(self):
        validate({"query": "x", "top_k": 5, "modalities": ["document"]}, self.SCHEMA)

    @pytest.mark.parametrize(
        "bad,fragment",
        [
            ({}, "is required"),
            ({"query": 1}, "expected string"),
            ({"query": "x", "top_k": 0}, ">= 1"),
            ({"query": "x", "top_k": 500}, "<= 100"),
            ({"query": "x", "unknown": 1}, "unknown properties"),
            ({"query": "x", "modalities": ["a", "b", "c", "d"]}, "at most 3"),
            ({"query": "x", "modalities": [1]}, "expected string"),
        ],
    )
    def test_invalid_arguments_are_rejected_with_a_useful_message(self, bad, fragment):
        with pytest.raises(SchemaViolation) as exc:
            validate(bad, self.SCHEMA)
        assert fragment in str(exc.value)

    def test_booleans_are_not_accepted_as_integers(self):
        with pytest.raises(SchemaViolation):
            validate({"query": "x", "top_k": True}, self.SCHEMA)

    def test_defaults_are_applied_without_mutating_the_input(self):
        args = {"query": "x"}
        filled = apply_defaults(args, self.SCHEMA)
        assert filled["top_k"] == 10
        assert "top_k" not in args
