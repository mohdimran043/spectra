'use client';

import { useMemo, useState } from 'react';

import { Mark, StatusChip } from '@/components/chip';
import { cn } from '@/components/cn';
import { Disclosure } from '@/components/disclosure';
import { Leaf, LeafHead } from '@/components/leaf';
import { EmptyState } from '@/components/states';
import type { GraphEdgeData, GraphNodeData } from '@/lib/schemas/evidence';
import { ForceCanvas } from './force-canvas';
import { tokenForLabel } from './palette';

function nodeTitle(node: GraphNodeData): string {
  for (const key of ['canonical_name', 'name', 'title', 'label', 'record_id']) {
    const value = node.properties[key];
    if (typeof value === 'string' && value.trim()) return value;
  }
  return node.node_id;
}

/**
 * The graph division. The canvas is the fast read; the list below it is the
 * complete one, and the filters drive both. Nothing is visible in the canvas
 * that the keyboard cannot also reach.
 */
export function GraphExplorer({
  nodes,
  edges,
  truncated,
  focusId,
  onExpand,
  height = 520,
}: {
  nodes: readonly GraphNodeData[];
  edges: readonly GraphEdgeData[];
  truncated?: boolean;
  focusId?: string | null;
  onExpand?: (nodeId: string) => void;
  height?: number;
}) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [hiddenLabels, setHiddenLabels] = useState<readonly string[]>([]);

  const labels = useMemo(() => {
    const counts = new Map<string, number>();
    for (const node of nodes) {
      const label = node.labels[0] ?? 'Node';
      counts.set(label, (counts.get(label) ?? 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [nodes]);

  const visibleNodes = useMemo(
    () => nodes.filter((node) => !hiddenLabels.includes(node.labels[0] ?? 'Node')),
    [nodes, hiddenLabels],
  );

  const visibleIds = useMemo(
    () => new Set(visibleNodes.map((node) => node.node_id)),
    [visibleNodes],
  );

  const visibleEdges = useMemo(
    () => edges.filter((edge) => visibleIds.has(edge.start) && visibleIds.has(edge.end)),
    [edges, visibleIds],
  );

  const selected = nodes.find((node) => node.node_id === selectedId) ?? null;
  const selectedEdges = selected
    ? edges.filter((edge) => edge.start === selected.node_id || edge.end === selected.node_id)
    : [];

  if (nodes.length === 0) {
    return (
      <Leaf>
        <LeafHead title="Evidence graph" />
        <EmptyState
          title="No graph for this record"
          body="The knowledge graph links entities to the documents, frames, segments and rows that mention them. Nothing has been linked for this selection yet."
        />
      </Leaf>
    );
  }

  return (
    <Leaf className="flex flex-col">
      <LeafHead
        title="Evidence graph"
        count={`${visibleNodes.length} nodes · ${visibleEdges.length} edges`}
        actions={truncated ? <StatusChip tone="caution">Truncated</StatusChip> : undefined}
      />

      <div className="flex flex-wrap items-center gap-1.5 border-b border-rule px-3 py-1.5">
        <span className="text-micro uppercase tracking-[0.08em] text-ink-2">Types</span>
        {labels.map(([label, count]) => {
          const hidden = hiddenLabels.includes(label);
          return (
            <button
              key={label}
              type="button"
              aria-pressed={!hidden}
              onClick={() =>
                setHiddenLabels((current) =>
                  hidden ? current.filter((value) => value !== label) : [...current, label],
                )
              }
              className={cn(
                'inline-flex items-center gap-1.5 rounded-sm border px-1.5 py-[0.0625rem] text-micro',
                hidden ? 'border-rule text-ink-3 line-through' : 'border-rule-strong text-ink-1 hover:text-ink',
              )}
            >
              <span
                className="block h-2 w-2 rounded-full"
                style={{ backgroundColor: `var(${tokenForLabel(label)})` }}
                aria-hidden="true"
              />
              {label}
              <span className="font-mono tabular text-ink-2">{count}</span>
            </button>
          );
        })}
      </div>

      <ForceCanvas
        nodes={visibleNodes}
        edges={visibleEdges}
        focusId={focusId}
        selectedId={selectedId}
        onSelect={setSelectedId}
        onExpand={onExpand}
        height={height}
      />

      <p className="border-b border-rule px-3 py-1 text-micro text-ink-2">
        Drag to pan, scroll to zoom, drag a node to pin it, double-click a node to expand its
        neighbours.
      </p>

      {selected && (
        <div className="border-b border-rule px-3 py-2">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className="block h-2.5 w-2.5"
              style={{ backgroundColor: `var(${tokenForLabel(selected.labels[0] ?? 'Node')})` }}
              aria-hidden="true"
            />
            <span className="text-head font-semibold text-ink">{nodeTitle(selected)}</span>
            {selected.labels.map((label) => (
              <Mark key={label}>{label}</Mark>
            ))}
            <span className="font-mono text-micro tabular text-ink-2">{selected.node_id}</span>
            {onExpand && (
              <button
                type="button"
                onClick={() => onExpand(selected.node_id)}
                className="ml-auto text-micro uppercase tracking-[0.08em] text-ink-2 underline decoration-rule-strong underline-offset-2 hover:text-ink"
              >
                Expand neighbours
              </button>
            )}
          </div>

          {Object.keys(selected.properties).length > 0 && (
            <dl className="mt-1.5 grid grid-cols-2 gap-x-4 gap-y-0.5 md:grid-cols-4">
              {Object.entries(selected.properties).map(([key, value]) => (
                <div key={key} className="min-w-0">
                  <dt className="text-micro uppercase tracking-[0.08em] text-ink-2">{key}</dt>
                  <dd className="truncate font-mono text-mark tabular text-ink">{String(value)}</dd>
                </div>
              ))}
            </dl>
          )}

          {selectedEdges.length > 0 && (
            <ul className="mt-1.5 flex flex-wrap gap-1.5">
              {selectedEdges.slice(0, 12).map((edge) => (
                <li
                  key={edge.edge_id}
                  className="rounded-sm border border-rule bg-board-sunk px-1.5 py-[0.0625rem] font-mono text-micro text-ink-1"
                >
                  {edge.start === selected.node_id ? '→' : '←'} {edge.type}{' '}
                  {edge.start === selected.node_id ? edge.end : edge.start}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <Disclosure summary={`All ${visibleNodes.length} nodes as a list`}>
        <div className="max-h-80 overflow-y-auto">
          <table className="w-full text-mark">
            <thead className="sticky top-0 bg-board-sunk">
              <tr className="border-b border-rule">
                <th scope="col" className="px-3 py-1 text-left text-micro uppercase tracking-[0.08em] text-ink-2">
                  Node
                </th>
                <th scope="col" className="px-3 py-1 text-left text-micro uppercase tracking-[0.08em] text-ink-2">
                  Type
                </th>
                <th scope="col" className="px-3 py-1 text-left text-micro uppercase tracking-[0.08em] text-ink-2">
                  Id
                </th>
                <th scope="col" className="px-3 py-1 text-right text-micro uppercase tracking-[0.08em] text-ink-2">
                  Edges
                </th>
              </tr>
            </thead>
            <tbody>
              {visibleNodes.map((node) => {
                const degree = visibleEdges.filter(
                  (edge) => edge.start === node.node_id || edge.end === node.node_id,
                ).length;
                return (
                  <tr
                    key={node.node_id}
                    className={cn(
                      'border-b border-rule last:border-b-0',
                      node.node_id === selectedId && 'bg-held-weak',
                    )}
                  >
                    <td className="px-3 py-1">
                      <button
                        type="button"
                        onClick={() => setSelectedId(node.node_id)}
                        className="text-left text-ink underline decoration-transparent underline-offset-2 hover:decoration-ink"
                      >
                        {nodeTitle(node)}
                      </button>
                    </td>
                    <td className="px-3 py-1 text-ink-1">{node.labels.join(', ') || '—'}</td>
                    <td className="px-3 py-1 font-mono text-micro tabular text-ink-2">
                      {node.node_id}
                    </td>
                    <td className="px-3 py-1 text-right font-mono tabular text-ink-1">{degree}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Disclosure>
    </Leaf>
  );
}
