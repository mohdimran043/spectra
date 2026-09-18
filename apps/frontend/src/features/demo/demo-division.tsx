'use client';

import { useMutation, useQuery } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { useState } from 'react';

import { Button } from '@/components/button';
import { Mark } from '@/components/chip';
import { IconChevronRight, IconDemo } from '@/components/icons';
import { Leaf, LeafHead } from '@/components/leaf';
import { Division, DivisionIntro } from '@/components/page';
import { EmptyState, ErrorState, SkeletonRows } from '@/components/states';
import { ModalityGlyph } from '@/components/stamp';
import { listDemoScenarios, runDemoScenario, seedDemoData } from '@/lib/api';
import { queryKeys } from '@/lib/query-keys';
import type { DemoScenario } from '@/lib/schemas/system';
import { useSession } from '@/features/shell/session-context';

function scenarioTitle(scenario: DemoScenario): string {
  return scenario.title ?? scenario.name ?? scenario.scenario_id;
}

function scenarioQuestion(scenario: DemoScenario): string | null {
  return scenario.question ?? scenario.seed_query ?? scenario.query ?? null;
}

function narrationLines(scenario: DemoScenario): readonly string[] {
  if (Array.isArray(scenario.narration)) return scenario.narration;
  if (typeof scenario.narration === 'string') return [scenario.narration];
  return scenario.steps ?? [];
}

/**
 * The guided demo runs the real endpoints. Each scenario states what it will
 * exercise, then hands the operator the live investigation record it produced —
 * there is no scripted playback and nothing here is staged.
 */
export function DemoDivision() {
  const router = useRouter();
  const session = useSession();
  const [runningId, setRunningId] = useState<string | null>(null);

  const scenarios = useQuery({
    queryKey: queryKeys.demoScenarios,
    queryFn: ({ signal }) => listDemoScenarios(signal),
  });

  const run = useMutation({
    mutationFn: (scenarioId: string) => runDemoScenario(scenarioId),
    onSuccess: (result) => router.push(`/investigations/${result.investigation_id}`),
    onSettled: () => setRunningId(null),
  });

  const seed = useMutation({ mutationFn: () => seedDemoData() });

  const rows = scenarios.data ?? [];

  return (
    <Division>
      <DivisionIntro
        title="Guided demo"
        lede="Six scenarios, each one a real call to the real API. They exist to show the machinery working across modalities, not to perform it."
        actions={
          session.can('manage_sources') && (
            <Button variant="secondary" onClick={() => seed.mutate()} disabled={seed.isPending}>
              {seed.isPending ? 'Seeding…' : 'Reload synthetic dataset'}
            </Button>
          )
        }
      />

      <div className="flex flex-col gap-3">
        {seed.isError && <ErrorState error={seed.error} context="Seeding the demo dataset" />}
        {seed.isSuccess && (
          <p className="border border-seal bg-seal-weak px-3 py-2 text-mark text-ink">
            The synthetic enterprise dataset was reloaded. Sources will re-index in the background.
          </p>
        )}

        {scenarios.isPending && (
          <Leaf>
            <LeafHead title="Loading scenarios" />
            <SkeletonRows rows={3} />
          </Leaf>
        )}

        {scenarios.isError && (
          <ErrorState
            error={scenarios.error}
            context="Demo scenarios"
            onRetry={() => scenarios.refetch()}
          />
        )}

        {run.isError && <ErrorState error={run.error} context="Running the scenario" />}

        {scenarios.isSuccess && rows.length === 0 && (
          <Leaf>
            <EmptyState
              title="No scenarios published"
              body="The API returned an empty scenario list. Seed the synthetic dataset, or check that the demo module is enabled on the server."
            />
          </Leaf>
        )}

        {rows.length > 0 && (
          <ul className="grid gap-2 xl:grid-cols-2">
            {rows.map((scenario) => {
              const narration = narrationLines(scenario);
              const question = scenarioQuestion(scenario);
              const busy = run.isPending && runningId === scenario.scenario_id;
              return (
                <li key={scenario.scenario_id} className="flex flex-col border border-rule bg-leaf">
                  <div className="flex flex-wrap items-center gap-2 border-b border-rule px-3 py-2">
                    <IconDemo size={14} className="text-ink-1" />
                    <h3 className="text-head font-semibold text-ink">{scenarioTitle(scenario)}</h3>
                    <Mark mono>{scenario.scenario_id}</Mark>
                    {scenario.modalities && (
                      <span className="flex items-center gap-1">
                        {scenario.modalities.map((modality) => (
                          <ModalityGlyph key={modality} modality={modality} size={12} />
                        ))}
                      </span>
                    )}
                    {scenario.mode && <Mark>{scenario.mode}</Mark>}
                  </div>

                  <div className="flex flex-1 flex-col gap-2 p-3">
                    {(scenario.description ?? scenario.summary) && (
                      <p className="text-body text-ink-1">
                        {scenario.description ?? scenario.summary}
                      </p>
                    )}

                    {question && (
                      <p className="border-l border-rule-strong pl-2.5 text-prose text-ink">
                        {question}
                      </p>
                    )}

                    {narration.length > 0 && (
                      <ol className="flex flex-col gap-1">
                        {narration.map((line, index) => (
                          <li key={`${scenario.scenario_id}-${index}`} className="flex gap-2">
                            <span className="font-mono text-micro tabular text-ink-2">
                              {String(index + 1).padStart(2, '0')}
                            </span>
                            <span className="text-mark text-ink-1">{line}</span>
                          </li>
                        ))}
                      </ol>
                    )}

                    {scenario.expected && (
                      <p className="text-mark text-ink-2">
                        <span className="uppercase tracking-[0.08em]">Expect </span>
                        {scenario.expected}
                      </p>
                    )}

                    <div className="mt-auto pt-1">
                      <Button
                        variant="primary"
                        onClick={() => {
                          setRunningId(scenario.scenario_id);
                          run.mutate(scenario.scenario_id);
                        }}
                        disabled={run.isPending || !session.can('investigate')}
                      >
                        {busy ? 'Running…' : 'Run this scenario'}
                        <IconChevronRight size={12} />
                      </Button>
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        )}

        {!session.can('investigate') && (
          <p className="text-mark text-caution">
            The viewer role cannot start an investigation, so the scenarios are read-only. Switch to
            analyst or admin in the record line.
          </p>
        )}
      </div>
    </Division>
  );
}
