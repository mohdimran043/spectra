'use client';

import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { useState } from 'react';

import { Button, SegmentButton } from '@/components/button';
import { Mark, StatusChip } from '@/components/chip';
import { TextField } from '@/components/field';
import { Leaf, LeafHead, Reading, Rule } from '@/components/leaf';
import { Division, DivisionIntro } from '@/components/page';
import { ErrorState, SkeletonRows } from '@/components/states';
import { getModelRuntime, listSources } from '@/lib/api';
import { API_BASE_URL, APP_BASE_URL, IS_USING_DEFAULT_API_BASE_URL } from '@/lib/env';
import { formatMegabytes } from '@/lib/format';
import { queryKeys } from '@/lib/query-keys';
import { ROLE_CAPABILITIES, ROLE_SUMMARY, type Role, type ThemePreference } from '@/lib/role';
import { MODEL_STATE_LABEL, MODEL_STATE_TONE, SOURCE_TYPE_LABEL } from '@/lib/vocab';
import { useHealth } from '@/features/shell/use-health';
import { useSession } from '@/features/shell/session-context';

const ROLES: readonly Role[] = ['admin', 'analyst', 'viewer'];
const THEMES: readonly ThemePreference[] = ['system', 'light', 'dark'];

/**
 * Settings is a read-out plus the few controls this client genuinely owns.
 *
 * Budgets, thresholds and model choice are server configuration: showing them as
 * editable fields the API has no endpoint for would be a lie about what the
 * button does, so they are shown as the values in force with the file that sets
 * them named.
 */
export function SettingsDivision() {
  const session = useSession();
  const health = useHealth();
  const [userDraft, setUserDraft] = useState(session.userId);

  const models = useQuery({
    queryKey: queryKeys.models,
    queryFn: ({ signal }) => getModelRuntime(signal),
  });

  const sources = useQuery({
    queryKey: queryKeys.sources,
    queryFn: ({ signal }) => listSources(signal),
  });

  return (
    <Division width="reading">
      <DivisionIntro
        title="Settings"
        lede="What this console is pointed at, whose seat you are in, and what the server has configured on the other end."
      />

      <div className="flex flex-col gap-3">
        <Leaf>
          <LeafHead title="Permissions" hint="Sent on every request as X-Spectra-Role" />
          <div className="flex flex-col gap-3 p-3">
            <div className="flex flex-wrap gap-1.5">
              {ROLES.map((role) => (
                <SegmentButton
                  key={role}
                  selected={session.role === role}
                  onClick={() => session.setRole(role)}
                >
                  {role}
                </SegmentButton>
              ))}
            </div>
            <p className="text-body text-ink-1">{ROLE_SUMMARY[session.role]}</p>
            <div className="flex flex-wrap gap-1.5">
              {ROLE_CAPABILITIES[session.role].map((capability) => (
                <Mark key={capability} mono>
                  {capability}
                </Mark>
              ))}
            </div>

            <Rule />

            <div className="flex flex-wrap items-end gap-2">
              <div className="min-w-[14rem] flex-1">
                <TextField
                  label="User id"
                  hint="X-Spectra-User"
                  value={userDraft}
                  mono
                  onChange={(event) => setUserDraft(event.target.value)}
                />
              </div>
              <Button
                variant="secondary"
                onClick={() => session.setUserId(userDraft)}
                disabled={userDraft.trim() === session.userId}
              >
                Apply
              </Button>
            </div>
            <p className="max-w-prose text-micro text-ink-2">
              Development uses a header shim. It is designed to be replaced by OAuth/OIDC without
              touching retrieval code, so nothing in this console assumes the shim is permanent.
            </p>
          </div>
        </Leaf>

        <Leaf>
          <LeafHead title="Appearance" />
          <div className="flex flex-wrap items-center gap-1.5 p-3">
            {THEMES.map((theme) => (
              <SegmentButton
                key={theme}
                selected={session.theme === theme}
                onClick={() => session.setTheme(theme)}
              >
                {theme}
              </SegmentButton>
            ))}
            <p className="ml-2 text-micro text-ink-2">
              Light for the day desk, dark for the night shift. &ldquo;System&rdquo; follows the
              machine.
            </p>
          </div>
        </Leaf>

        <Leaf>
          <LeafHead title="Connections" />
          <div className="grid gap-x-6 gap-y-3 p-3 md:grid-cols-2">
            <Reading label="SPECTRA API" value={API_BASE_URL} mono />
            <Reading label="Enterprise application" value={APP_BASE_URL} mono />
            <Reading
              label="API status"
              value={
                health.isError
                  ? 'unreachable'
                  : `${health.data?.status ?? 'checking'}${health.data?.degraded ? ' · degraded' : ''}`
              }
            />
            <Reading label="API version" value={health.data?.version ?? '—'} />
          </div>
          {IS_USING_DEFAULT_API_BASE_URL && (
            <p className="border-t border-rule px-3 py-2 text-mark text-caution">
              NEXT_PUBLIC_API_BASE_URL is not set, so this console is using the built-in default.
              Set it in the environment before deploying anywhere but a workstation.
            </p>
          )}
          {health.isError && <ErrorState error={health.error} context="Health check" />}
        </Leaf>

        <Leaf>
          <LeafHead
            title="Model configuration"
            hint="Server-side; this console reports it rather than setting it"
            actions={
              <Link
                href="/models"
                className="text-micro uppercase tracking-[0.08em] text-ink-2 underline decoration-rule-strong underline-offset-2 hover:text-ink"
              >
                Runtime dashboard
              </Link>
            }
          />
          {models.isPending && <SkeletonRows rows={3} />}
          {models.isError && <ErrorState error={models.error} context="Model runtime" />}
          {models.data && (
            <div className="flex flex-col gap-2 p-3">
              <div className="flex flex-wrap gap-x-6 gap-y-2">
                <Reading label="Profile" value={models.data.profile} mono={false} />
                <Reading
                  label="GPU"
                  value={models.data.gpu.available ? (models.data.gpu.name ?? 'present') : 'unavailable'}
                  mono={false}
                  tone={models.data.gpu.available ? undefined : 'text-caution'}
                />
                <Reading label="VRAM budget" value={formatMegabytes(models.data.gpu.budget_mb)} />
                <Reading label="Queue depth" value={String(models.data.queue_depth)} />
              </div>
              <ul className="flex flex-wrap gap-1.5">
                {models.data.models.map((model) => (
                  <li key={model.role}>
                    <StatusChip tone={MODEL_STATE_TONE[model.state]}>
                      {model.role} · {MODEL_STATE_LABEL[model.state]}
                    </StatusChip>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Leaf>

        <Leaf>
          <LeafHead
            title="Connectors"
            count={sources.data?.length}
            actions={
              <Link
                href="/sources"
                className="text-micro uppercase tracking-[0.08em] text-ink-2 underline decoration-rule-strong underline-offset-2 hover:text-ink"
              >
                Source registry
              </Link>
            }
          />
          {sources.isPending && <SkeletonRows rows={3} />}
          {sources.isError && <ErrorState error={sources.error} context="Source registry" />}
          {sources.data && (
            <ul className="flex flex-col">
              {sources.data.map((source) => (
                <li
                  key={source.source_id}
                  className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-rule px-3 py-1.5 last:border-b-0"
                >
                  <span className="text-mark text-ink">{source.name}</span>
                  <Mark>{SOURCE_TYPE_LABEL[source.type]}</Mark>
                  <span className="font-mono text-micro text-ink-2">{source.source_id}</span>
                  <span className="ml-auto text-micro text-ink-2">
                    {source.credential_ref ? `credential ${source.credential_ref}` : 'no credential'}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Leaf>

        <Leaf>
          <LeafHead title="Budgets and thresholds" />
          <div className="flex flex-col gap-2 p-3">
            <p className="max-w-prose text-body text-ink-1">
              Tool-call ceilings, iteration limits, latency budgets and confidence thresholds are
              enforced by the API and travel with each investigation. The live values for a run are
              printed on its Brain status band, and the budget it actually spent is on its search
              autopsy.
            </p>
            <p className="max-w-prose text-micro text-ink-2">
              The API exposes no endpoint for changing them, so this console does not offer controls
              that would not take effect. They are configured server-side in the deployment&rsquo;s
              environment.
            </p>
          </div>
        </Leaf>
      </div>
    </Division>
  );
}
