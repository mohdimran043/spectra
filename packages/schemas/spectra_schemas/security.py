"""Permission context threaded through every search tool."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .enums import Role

ROLE_CAPABILITIES: dict[Role, set[str]] = {
    Role.ADMIN: {
        "search",
        "investigate",
        "upload",
        "manage_sources",
        "manage_agents",
        "manage_models",
        "run_sql",
        "view_autopsy",
        "export",
    },
    Role.ANALYST: {"search", "investigate", "upload", "run_sql", "view_autopsy", "export"},
    Role.VIEWER: {"search", "view_autopsy"},
}


class PermissionContext(BaseModel):
    """Who is asking.  Every retrieval path filters against this."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: str = "local-user"
    role: Role = Role.ANALYST
    source_access: list[str] = Field(
        default_factory=list, description="Empty = all sources this role may see"
    )
    entity_access: list[str] = Field(default_factory=list)
    denied_sources: list[str] = Field(default_factory=list)

    @property
    def capabilities(self) -> set[str]:
        return ROLE_CAPABILITIES.get(self.role, set())

    def can(self, capability: str) -> bool:
        return capability in self.capabilities

    def may_read_source(self, source_id: str, source_permissions: list[str] | None = None) -> bool:
        if source_id in self.denied_sources:
            return False
        if self.source_access and source_id not in self.source_access:
            return False
        if source_permissions and self.role.value not in source_permissions:
            return False
        return True

    def cache_key(self) -> str:
        """Included in every cache key so one role never serves another's results."""
        parts = [self.role.value, ",".join(sorted(self.source_access)), ",".join(sorted(self.denied_sources))]
        return "|".join(parts)


ANONYMOUS = PermissionContext(user_id="anonymous", role=Role.VIEWER)
SYSTEM = PermissionContext(user_id="system", role=Role.ADMIN)
