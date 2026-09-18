"""Graph Agent - how the entities connect.

Finds the entity subgraph a query is really about, and expands one node's
neighbourhood to a bounded depth so the records, documents and media an entity
touches come back together.  It is what turns a list of hits into a structure
the Brain can reason over.

Switched off with the ``graph`` deployment flag.
"""

from __future__ import annotations

from .tools import GRAPH_TOOLS, ExpandGraphTool, SearchGraphTool

__all__ = ["GRAPH_TOOLS", "ExpandGraphTool", "SearchGraphTool"]
