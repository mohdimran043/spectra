'use client';

import { useQuery } from '@tanstack/react-query';
import { useRouter, useSearchParams } from 'next/navigation';
import { useCallback, useMemo, useState } from 'react';

import { Button } from '@/components/button';
import { Mark } from '@/components/chip';
import { IconSearch } from '@/components/icons';
import { Leaf, LeafHead } from '@/components/leaf';
import { Division, DivisionIntro } from '@/components/page';
import { EmptyState, ErrorState, SkeletonRows } from '@/components/states';
import { getGraph, searchEntities } from '@/lib/api';
import { queryKeys } from '@/lib/query-keys';
import type { GraphEdgeData, GraphNodeData } from '@/lib/schemas/evidence';
import { GraphExplorer } from './graph-explorer';

const EDGE_TYPE_PRESETS: readonly string[] = ['', 'MENTIONS,REFERS_TO', 'MENTIONS', 'REFERS_TO'];
const DEPTHS: readonly number[] = [1, 2, 3];

/**
 * The graph division. A focus node plus a traversal depth is the whole query —
 * expanding a node re-roots the view, which is how an investigator actually
 * walks a graph: one hop at a time from something they recognise.
 */
export function GraphDivision() {
  const router = useRouter();
  const params = useSearchParams();

  const focusFromUrl = params.get('focus') ?? '';
  const [focusId, setFocusId] = useState(focusFromUrl);
  const [depth, setDepth] = useState(2);
  const [types, setTypes] = useState('');
  const [entityQuery, setEntityQuery] = useState('');
  const [accumulated, setAccumulated] = useState<{
    nodes: readonly GraphNodeData[];
    edges: readonly GraphEdgeData[];
  }>({ nodes: [], edges: [] });

  const graphQuery = useQuery({
    queryKey: queryKeys.graph(focusId, depth, types),
    queryFn: ({ signal }) => getGraph(focusId, { depth, types: types || undefined }, signal),
    enabled: focusId.length > 0,
    retry: false,
  });

  const entities = useQuery({
    queryKey: queryKeys.entitySearch(entityQuery),
    queryFn: ({ signal }) => searchEntities(entityQuery, undefined, signal),
    enabled: entityQuery.trim().length >= 2,
    retry: false,
  });

  const merged = useMemo(() => {
    const view = graphQuery.data;
    if (!view) return accumulated;
    const nodeById = new Map<string, GraphNodeData>();
    for (const node of [...accumulated.nodes, ...view.nodes]) nodeById.set(node.node_id, node);
    const edgeById = new Map<string, GraphEdgeData>();
    for (const edge of [...accumulated.edges, ...view.edges]) edgeById.set(edge.edge_id, edge);
    return { nodes: [...nodeById.values()], edges: [...edgeById.values()] };
  }, [graphQuery.data, accumulated]);

  const expand = useCallback(
    (nodeId: string) => {
      setAccumulated(merged);
      setFocusId(nodeId);
      router.replace(`/graph?focus=${encodeURIComponent(nodeId)}`, { scroll: false });
    },
    [merged, router],
  );

  return (
    <Division>
      <DivisionIntro
        title="Evidence graph"
        lede="Entities and the records that mention them. Start from an entity, walk outwards, and every node keeps the colour it has everywhere else in the console."
      />

      <div className="flex flex-col gap-3">
        <Leaf>
          <LeafHead title="Focus" hint="Search for an entity, or paste a node id" />
          <div className="flex flex-col gap-2 p-3">
            <div className="flex flex-wrap items-end gap-2">
              <div className="min-w-[14rem] flex-1">
                <label htmlFor="entity-search" className="sr-only">
                  Search entities
                </label>
                <input
                  id="entity-search"
                  value={entityQuery}
                  onChange={(event) => setEntityQuery(event.target.value)}
                  placeholder="Search entities by name…"
                  className="h-7 w-full rounded-sm border border-rule-strong bg-leaf px-2 text-body text-ink placeholder:text-ink-2"
                />
              </div>
              <div className="min-w-[14rem] flex-1">
                <label htmlFor="node-id" className="sr-only">
                  Node id
                </label>
                <input
                  id="node-id"
                  value={focusId}
                  onChange={(event) => setFocusId(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') setAccumulated({ nodes: [], edges: [] });
                  }}
                  placeholder="ent_transaction_ab12"
                  className="h-7 w-full rounded-sm border border-rule-strong bg-leaf px-2 font-mono text-mark tabular text-ink placeholder:text-ink-2"
                />
              </div>
              <div className="flex items-center gap-1.5">
                <label htmlFor="graph-depth" className="text-micro uppercase tracking-[0.08em] text-ink-2">
                  Depth
                </label>
                <select
                  id="graph-depth"
                  value={depth}
                  onChange={(event) => setDepth(Number(event.target.value))}
                  className="h-7 rounded-sm border border-rule-strong bg-leaf px-1.5 text-mark text-ink"
                >
                  {DEPTHS.map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
              </div>
              <div className="flex items-center gap-1.5">
                <label htmlFor="graph-types" className="text-micro uppercase tracking-[0.08em] text-ink-2">
                  Edge types
                </label>
                <select
                  id="graph-types"
                  value={types}
                  onChange={(event) => setTypes(event.target.value)}
                  className="h-7 rounded-sm border border-rule-strong bg-leaf px-1.5 text-mark text-ink"
                >
                  {EDGE_TYPE_PRESETS.map((preset) => (
                    <option key={preset || 'all'} value={preset}>
                      {preset || 'All'}
                    </option>
                  ))}
                </select>
              </div>
              <Button
                variant="primary"
                onClick={() => {
                  setAccumulated({ nodes: [], edges: [] });
                  void graphQuery.refetch();
                }}
                disabled={!focusId}
              >
                <IconSearch size={12} />
                Load
              </Button>
              {merged.nodes.length > 0 && (
                <Button variant="quiet" onClick={() => setAccumulated({ nodes: [], edges: [] })}>
                  Reset view
                </Button>
              )}
            </div>

            {entities.data && entities.data.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-micro uppercase tracking-[0.08em] text-ink-2">Matches</span>
                {entities.data.slice(0, 12).map((entity) => (
                  <button
                    key={entity.entity_id}
                    type="button"
                    onClick={() => {
                      setAccumulated({ nodes: [], edges: [] });
                      setFocusId(entity.entity_id);
                    }}
                    className="inline-flex items-center gap-1.5 rounded-sm border border-rule-strong bg-leaf px-1.5 py-[0.0625rem] text-micro text-ink-1 hover:text-ink"
                  >
                    {entity.canonical_name}
                    <Mark>{entity.entity_type}</Mark>
                  </button>
                ))}
              </div>
            )}
            {entities.isError && <ErrorState error={entities.error} context="Entity search" className="px-0" />}
          </div>
        </Leaf>

        {!focusId && (
          <Leaf>
            <EmptyState
              title="No focus selected"
              body="The graph is traversed from a starting node. Search for an entity above, or arrive here from an entity chip on a search result."
            />
          </Leaf>
        )}

        {focusId && graphQuery.isPending && (
          <Leaf>
            <LeafHead title="Loading graph" />
            <SkeletonRows rows={4} />
          </Leaf>
        )}

        {graphQuery.isError && (
          <ErrorState error={graphQuery.error} context="Graph traversal" onRetry={() => graphQuery.refetch()} />
        )}

        {focusId && merged.nodes.length > 0 && (
          <GraphExplorer
            nodes={merged.nodes}
            edges={merged.edges}
            truncated={graphQuery.data?.truncated}
            focusId={focusId}
            onExpand={expand}
            height={560}
          />
        )}
      </div>
    </Division>
  );
}
