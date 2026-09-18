"""Entity Resolver - deciding who or what a name refers to.

Turns a surface form (an id, a partial name, a nickname) into a canonical entity
with its candidate list and matching method, and searches the canonical entities
by name or alias.  The Brain leans on it before the graph agent so that a
subgraph is expanded from a real entity rather than a string.

Switched off with the ``entity_resolution`` deployment flag.
"""

from __future__ import annotations

from .tools import ENTITY_TOOLS, ResolveEntityTool, SearchEntitiesTool

__all__ = ["ENTITY_TOOLS", "ResolveEntityTool", "SearchEntitiesTool"]
