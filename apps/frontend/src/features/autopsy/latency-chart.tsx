'use client';

import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

import { formatLatency } from '@/lib/format';
import { humaniseKey } from '@/lib/vocab';

const BAR_HEIGHT = 22;
const CHART_PADDING = 28;

/**
 * Per-stage latency. This is a chart because the comparison between stages is
 * the point — where the time went — not because a dashboard needs a graphic.
 */
export function StageLatencyChart({ stages }: { stages: Record<string, number> }) {
  const rows = Object.entries(stages)
    .map(([stage, latency]) => ({ stage: humaniseKey(stage), latency }))
    .sort((a, b) => b.latency - a.latency);

  if (rows.length === 0) return null;

  const peak = Math.max(...rows.map((row) => row.latency));

  return (
    <div style={{ height: rows.length * BAR_HEIGHT + CHART_PADDING * 2 }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 56, bottom: 4, left: 4 }}>
          <CartesianGrid horizontal={false} stroke="var(--rule)" />
          <XAxis
            type="number"
            tick={{ fill: 'var(--ink-2)', fontSize: 11 }}
            stroke="var(--rule-strong)"
            tickFormatter={(value: number) => formatLatency(value)}
          />
          <YAxis
            type="category"
            dataKey="stage"
            width={148}
            tick={{ fill: 'var(--ink-1)', fontSize: 12 }}
            stroke="var(--rule-strong)"
          />
          <Tooltip
            cursor={{ fill: 'var(--board-sunk)' }}
            contentStyle={{
              background: 'var(--overlay)',
              border: '1px solid var(--rule-strong)',
              borderRadius: 2,
              fontSize: 12,
              color: 'var(--ink-0)',
            }}
            formatter={(value: number) => [formatLatency(value), 'Latency']}
          />
          <Bar dataKey="latency" isAnimationActive={false} barSize={12}>
            {rows.map((row) => (
              <Cell
                key={row.stage}
                fill={row.latency === peak ? 'var(--caution)' : 'var(--held)'}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
