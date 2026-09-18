'use client';

import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  type Simulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from 'd3-force';
import { useCallback, useEffect, useRef, useState } from 'react';

import { cn } from '@/components/cn';
import type { GraphEdgeData, GraphNodeData } from '@/lib/schemas/evidence';
import { readGraphTheme, type GraphTheme } from './palette';

interface SimNode extends SimulationNodeDatum {
  readonly id: string;
  readonly label: string;
  readonly title: string;
  readonly degree: number;
}

interface SimLink extends SimulationLinkDatum<SimNode> {
  readonly id: string;
  readonly type: string;
}

const NODE_RADIUS_BASE = 5;
const NODE_RADIUS_PER_DEGREE = 0.9;
const NODE_RADIUS_MAX = 13;
const LABEL_VISIBLE_SCALE = 0.72;
const MIN_SCALE = 0.25;
const MAX_SCALE = 3.5;

function radiusFor(node: SimNode): number {
  return Math.min(NODE_RADIUS_MAX, NODE_RADIUS_BASE + node.degree * NODE_RADIUS_PER_DEGREE);
}

function nodeTitle(node: GraphNodeData): string {
  const properties = node.properties;
  for (const key of ['canonical_name', 'name', 'title', 'label', 'record_id']) {
    const value = properties[key];
    if (typeof value === 'string' && value.trim()) return value;
  }
  return node.node_id;
}

/**
 * An authored canvas layer over `d3-force`.
 *
 * Drawing it here rather than importing a graph widget keeps the console's own
 * hairlines, hues and type on the canvas, and keeps the accessible fallback
 * honest: every node and edge the canvas shows is also reachable as a list.
 */
export function ForceCanvas({
  nodes,
  edges,
  focusId,
  selectedId,
  onSelect,
  onExpand,
  className,
  height = 520,
}: {
  nodes: readonly GraphNodeData[];
  edges: readonly GraphEdgeData[];
  focusId?: string | null;
  selectedId?: string | null;
  onSelect?: (nodeId: string | null) => void;
  onExpand?: (nodeId: string) => void;
  className?: string;
  height?: number;
}) {
  const wrapperRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const simulationRef = useRef<Simulation<SimNode, SimLink> | null>(null);
  const nodesRef = useRef<SimNode[]>([]);
  const linksRef = useRef<SimLink[]>([]);
  const themeRef = useRef<GraphTheme | null>(null);
  const viewRef = useRef({ x: 0, y: 0, scale: 1 });
  const dragRef = useRef<{ pointerX: number; pointerY: number; node: SimNode | null } | null>(null);
  const [hoveredId, setHoveredId] = useState<string | null>(null);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const theme = themeRef.current;
    if (!canvas || !theme) return;
    const context = canvas.getContext('2d');
    if (!context) return;

    const ratio = window.devicePixelRatio || 1;
    const width = canvas.width / ratio;
    const drawHeight = canvas.height / ratio;
    const view = viewRef.current;

    context.save();
    context.scale(ratio, ratio);
    context.clearRect(0, 0, width, drawHeight);
    context.fillStyle = theme.board;
    context.fillRect(0, 0, width, drawHeight);

    context.translate(view.x, view.y);
    context.scale(view.scale, view.scale);

    context.lineWidth = 1 / view.scale;
    context.strokeStyle = theme.rule;
    for (const link of linksRef.current) {
      const source = link.source as SimNode;
      const target = link.target as SimNode;
      if (source.x === undefined || target.x === undefined) continue;
      context.beginPath();
      context.moveTo(source.x, source.y ?? 0);
      context.lineTo(target.x, target.y ?? 0);
      context.stroke();
    }

    if (view.scale >= LABEL_VISIBLE_SCALE) {
      context.font = `${9 / view.scale}px ui-monospace, monospace`;
      context.fillStyle = theme.inkSoft;
      context.textAlign = 'center';
      for (const link of linksRef.current) {
        const source = link.source as SimNode;
        const target = link.target as SimNode;
        if (source.x === undefined || target.x === undefined) continue;
        const midX = ((source.x ?? 0) + (target.x ?? 0)) / 2;
        const midY = ((source.y ?? 0) + (target.y ?? 0)) / 2;
        context.fillText(link.type, midX, midY - 3 / view.scale);
      }
    }

    for (const node of nodesRef.current) {
      if (node.x === undefined || node.y === undefined) continue;
      const radius = radiusFor(node);
      const isActive = node.id === selectedId || node.id === hoveredId || node.id === focusId;

      context.beginPath();
      context.arc(node.x, node.y, radius, 0, Math.PI * 2);
      context.fillStyle = theme.labelColour(node.label);
      context.fill();

      if (isActive) {
        context.lineWidth = 2 / view.scale;
        context.strokeStyle = node.id === focusId ? theme.focus : theme.ink;
        context.stroke();
      }

      if (view.scale >= LABEL_VISIBLE_SCALE || isActive) {
        context.font = `${10 / view.scale}px ui-sans-serif, system-ui, sans-serif`;
        context.fillStyle = theme.ink;
        context.textAlign = 'center';
        context.fillText(node.title, node.x, node.y + radius + 11 / view.scale);
      }
    }

    context.restore();
  }, [focusId, hoveredId, selectedId]);

  /** Rebuild the simulation whenever the graph itself changes. */
  useEffect(() => {
    const degrees = new Map<string, number>();
    for (const edge of edges) {
      degrees.set(edge.start, (degrees.get(edge.start) ?? 0) + 1);
      degrees.set(edge.end, (degrees.get(edge.end) ?? 0) + 1);
    }

    const simNodes: SimNode[] = nodes.map((node) => ({
      id: node.node_id,
      label: node.labels[0] ?? 'Node',
      title: nodeTitle(node),
      degree: degrees.get(node.node_id) ?? 0,
    }));
    const known = new Set(simNodes.map((node) => node.id));
    const simLinks: SimLink[] = edges
      .filter((edge) => known.has(edge.start) && known.has(edge.end))
      .map((edge) => ({ id: edge.edge_id, type: edge.type, source: edge.start, target: edge.end }));

    nodesRef.current = simNodes;
    linksRef.current = simLinks;

    simulationRef.current?.stop();
    const simulation = forceSimulation<SimNode>(simNodes)
      .force('charge', forceManyBody<SimNode>().strength(-180).distanceMax(420))
      .force(
        'link',
        forceLink<SimNode, SimLink>(simLinks)
          .id((node) => node.id)
          .distance(78)
          .strength(0.35),
      )
      .force('collide', forceCollide<SimNode>((node) => radiusFor(node) + 9))
      .force('center', forceCenter(0, 0))
      .alpha(1)
      .alphaDecay(0.035);

    simulation.on('tick', draw);
    simulationRef.current = simulation;

    return () => {
      simulation.stop();
    };
  }, [nodes, edges, draw]);

  /** Size, theme sampling and redraw on resize or theme change. */
  useEffect(() => {
    const wrapper = wrapperRef.current;
    const canvas = canvasRef.current;
    if (!wrapper || !canvas) return undefined;

    const applyTheme = () => {
      themeRef.current = readGraphTheme(wrapper);
      draw();
    };

    const resize = () => {
      const ratio = window.devicePixelRatio || 1;
      const rect = wrapper.getBoundingClientRect();
      canvas.width = Math.max(1, Math.floor(rect.width * ratio));
      canvas.height = Math.max(1, Math.floor(height * ratio));
      canvas.style.width = `${rect.width}px`;
      canvas.style.height = `${height}px`;
      viewRef.current = { ...viewRef.current, x: rect.width / 2, y: height / 2 };
      applyTheme();
    };

    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(wrapper);

    const themeObserver = new MutationObserver(applyTheme);
    themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });

    const media = window.matchMedia('(prefers-color-scheme: dark)');
    media.addEventListener('change', applyTheme);

    return () => {
      observer.disconnect();
      themeObserver.disconnect();
      media.removeEventListener('change', applyTheme);
    };
  }, [draw, height]);

  const toGraphSpace = (clientX: number, clientY: number) => {
    const canvas = canvasRef.current;
    if (!canvas) return { x: 0, y: 0 };
    const rect = canvas.getBoundingClientRect();
    const view = viewRef.current;
    return {
      x: (clientX - rect.left - view.x) / view.scale,
      y: (clientY - rect.top - view.y) / view.scale,
    };
  };

  const nodeAt = (clientX: number, clientY: number): SimNode | null => {
    const point = toGraphSpace(clientX, clientY);
    for (let index = nodesRef.current.length - 1; index >= 0; index -= 1) {
      const node = nodesRef.current[index];
      if (!node || node.x === undefined || node.y === undefined) continue;
      const distance = Math.hypot(node.x - point.x, node.y - point.y);
      if (distance <= radiusFor(node) + 3) return node;
    }
    return null;
  };

  return (
    <div ref={wrapperRef} className={cn('relative w-full', className)}>
      <canvas
        ref={canvasRef}
        className="block w-full cursor-grab border border-rule active:cursor-grabbing"
        onPointerDown={(event) => {
          const node = nodeAt(event.clientX, event.clientY);
          dragRef.current = { pointerX: event.clientX, pointerY: event.clientY, node };
          if (node) {
            node.fx = node.x;
            node.fy = node.y;
            simulationRef.current?.alphaTarget(0.22).restart();
          }
          event.currentTarget.setPointerCapture(event.pointerId);
        }}
        onPointerMove={(event) => {
          const drag = dragRef.current;
          if (!drag) {
            const hovered = nodeAt(event.clientX, event.clientY);
            setHoveredId(hovered?.id ?? null);
            return;
          }
          const dx = event.clientX - drag.pointerX;
          const dy = event.clientY - drag.pointerY;
          dragRef.current = { ...drag, pointerX: event.clientX, pointerY: event.clientY };
          if (drag.node) {
            const scale = viewRef.current.scale;
            drag.node.fx = (drag.node.fx ?? 0) + dx / scale;
            drag.node.fy = (drag.node.fy ?? 0) + dy / scale;
          } else {
            viewRef.current = {
              ...viewRef.current,
              x: viewRef.current.x + dx,
              y: viewRef.current.y + dy,
            };
            draw();
          }
        }}
        onPointerUp={(event) => {
          const drag = dragRef.current;
          dragRef.current = null;
          event.currentTarget.releasePointerCapture(event.pointerId);
          if (drag?.node) {
            drag.node.fx = null;
            drag.node.fy = null;
            simulationRef.current?.alphaTarget(0);
            const moved =
              Math.abs(event.clientX - drag.pointerX) > 3 || Math.abs(event.clientY - drag.pointerY) > 3;
            if (!moved) onSelect?.(drag.node.id);
          } else if (drag && !drag.node) {
            const moved =
              Math.abs(event.clientX - drag.pointerX) > 3 || Math.abs(event.clientY - drag.pointerY) > 3;
            if (!moved) onSelect?.(null);
          }
        }}
        onDoubleClick={(event) => {
          const node = nodeAt(event.clientX, event.clientY);
          if (node) onExpand?.(node.id);
        }}
        onWheel={(event) => {
          const view = viewRef.current;
          const factor = event.deltaY < 0 ? 1.12 : 1 / 1.12;
          const nextScale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, view.scale * factor));
          const canvas = canvasRef.current;
          if (!canvas) return;
          const rect = canvas.getBoundingClientRect();
          const pointerX = event.clientX - rect.left;
          const pointerY = event.clientY - rect.top;
          viewRef.current = {
            scale: nextScale,
            x: pointerX - ((pointerX - view.x) / view.scale) * nextScale,
            y: pointerY - ((pointerY - view.y) / view.scale) * nextScale,
          };
          draw();
        }}
        role="img"
        aria-label={`Force-directed graph of ${nodes.length} nodes and ${edges.length} edges. An equivalent list follows.`}
      />
    </div>
  );
}
