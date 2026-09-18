'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { Mark, StatusChip } from '@/components/chip';
import { cn } from '@/components/cn';
import { Toggle } from '@/components/disclosure';
import { Leaf, LeafHead } from '@/components/leaf';
import { Division, DivisionIntro } from '@/components/page';
import { EmptyState, ErrorState, SkeletonRows } from '@/components/states';
import { getAgentStatus, setAgentEnabled } from '@/lib/api';
import { queryKeys } from '@/lib/query-keys';
import type { AgentStatusRow } from '@/lib/schemas/system';
import type { StatusTone } from '@/lib/vocab';
import { useSession } from '@/features/shell/session-context';
import { AgentGlyph, resolveAgentName } from '@/features/investigation/agent-glyph';

function stateTone(agent: AgentStatusRow): StatusTone {
  if (!agent.enabled) return 'quiet';
  if (!agent.ready) return 'caution';
  return 'seal';
}

function stateLabel(agent: AgentStatusRow): string {
  if (!agent.enabled) return 'Disabled';
  if (!agent.ready) return 'Not ready';
  return agent.state || 'Ready';
}

/**
 * A disabled agent renders the shape the spec requires, verbatim: the name, the
 * status, the reason it is off, and what SPECTRA will use instead. An operator
 * who turns off vision must be able to see, without leaving this screen, that
 * documents, videos and the database still cover the question.
 */
function AgentCard({ agent }: { agent: AgentStatusRow }) {
  const session = useSession();
  const queryClient = useQueryClient();
  const canManage = session.can('manage_agents');

  const toggle = useMutation({
    mutationFn: (enabled: boolean) => setAgentEnabled(agent.name, enabled),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.agents }),
  });

  const glyphName = resolveAgentName(agent.name);
  const off = !agent.enabled;

  return (
    <li
      className={cn(
        'flex flex-col gap-2 border px-3 py-2.5',
        off ? 'border-rule bg-board-sunk' : 'border-rule bg-leaf',
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className={off ? 'text-ink-2' : 'text-ink-1'}>
          {glyphName ? <AgentGlyph agent={glyphName} size={15} /> : null}
        </span>
        <h3 className="text-mark font-semibold uppercase tracking-[0.12em] text-ink">
          {agent.label}
        </h3>
        <StatusChip tone={stateTone(agent)}>{stateLabel(agent)}</StatusChip>
        <div className="ml-auto">
          <Toggle
            checked={agent.enabled}
            disabled={!canManage || toggle.isPending}
            onCheckedChange={(next) => toggle.mutate(next)}
            label={`${agent.enabled ? 'Disable' : 'Enable'} ${agent.label}`}
          />
        </div>
      </div>

      <dl className="flex flex-col gap-1">
        <div className="flex gap-2">
          <dt className="w-[6.5rem] shrink-0 text-micro uppercase tracking-[0.08em] text-ink-2">
            Status
          </dt>
          <dd className="text-mark text-ink">{stateLabel(agent)}</dd>
        </div>
        {agent.reason && (
          <div className="flex gap-2">
            <dt className="w-[6.5rem] shrink-0 text-micro uppercase tracking-[0.08em] text-ink-2">
              Reason
            </dt>
            <dd className={cn('text-mark', off ? 'text-caution' : 'text-ink-1')}>{agent.reason}</dd>
          </div>
        )}
        {agent.alternatives.length > 0 && (
          <div className="flex gap-2">
            <dt className="w-[6.5rem] shrink-0 text-micro uppercase tracking-[0.08em] text-ink-2">
              Alternatives
            </dt>
            <dd className="text-mark text-ink-1">{agent.alternatives.join(', ')}</dd>
          </div>
        )}
        {agent.depends_on.length > 0 && (
          <div className="flex gap-2">
            <dt className="w-[6.5rem] shrink-0 text-micro uppercase tracking-[0.08em] text-ink-2">
              Depends on
            </dt>
            <dd className="text-mark text-ink-1">{agent.depends_on.join(', ')}</dd>
          </div>
        )}
      </dl>

      {agent.tools.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-micro uppercase tracking-[0.08em] text-ink-2">Tools</span>
          {agent.tools.map((tool) => (
            <Mark key={tool} mono>
              {tool}
            </Mark>
          ))}
        </div>
      )}

      {toggle.isError && <ErrorState error={toggle.error} context={`Toggling ${agent.label}`} className="px-0" />}
    </li>
  );
}

export function AgentsDivision() {
  const session = useSession();
  const query = useQuery({
    queryKey: queryKeys.agents,
    queryFn: ({ signal }) => getAgentStatus(signal),
  });

  const agents = query.data ?? [];
  const disabled = agents.filter((agent) => !agent.enabled).length;

  return (
    <Division>
      <DivisionIntro
        title="Agent control center"
        lede="Turn a capability off and SPECTRA says so — in this list, on the trace, and in the answer's explanation of which sources it skipped. Nothing degrades quietly."
        meta={
          <>
            <Mark>{agents.length} agents</Mark>
            {disabled > 0 && <StatusChip tone="caution">{disabled} disabled</StatusChip>}
            {!session.can('manage_agents') && (
              <StatusChip tone="quiet">Read-only in the {session.role} role</StatusChip>
            )}
          </>
        }
      />

      {query.isPending && (
        <Leaf>
          <LeafHead title="Loading agents" />
          <SkeletonRows rows={5} />
        </Leaf>
      )}

      {query.isError && (
        <ErrorState error={query.error} context="Agent status" onRetry={() => query.refetch()} />
      )}

      {query.isSuccess && agents.length === 0 && (
        <Leaf>
          <EmptyState
            title="No agents registered"
            body="The API returned an empty agent roster. Nothing can run until at least the Brain is registered."
          />
        </Leaf>
      )}

      {agents.length > 0 && (
        <ul className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
          {agents.map((agent) => (
            <AgentCard key={agent.name} agent={agent} />
          ))}
        </ul>
      )}
    </Division>
  );
}
