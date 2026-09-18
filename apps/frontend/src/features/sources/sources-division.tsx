'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { Button, SegmentButton } from '@/components/button';
import { SelectField, TextField } from '@/components/field';
import { Leaf, LeafHead } from '@/components/leaf';
import { Division, DivisionIntro } from '@/components/page';
import { EmptyState, ErrorState, SkeletonRows } from '@/components/states';
import { createSource, listSources } from '@/lib/api';
import { queryKeys } from '@/lib/query-keys';
import type { Modality, SourceType } from '@/lib/schemas/primitives';
import type { SourceDescriptor } from '@/lib/schemas/system';
import { MODALITY_LABEL, SOURCE_TYPE_LABEL } from '@/lib/vocab';
import { useSession } from '@/features/shell/session-context';
import { SourceRow } from './source-row';

const GROUPS: ReadonlyArray<{ readonly id: Modality; readonly title: string }> = [
  { id: 'document', title: 'Documents' },
  { id: 'image', title: 'Images' },
  { id: 'video', title: 'Videos' },
  { id: 'audio', title: 'Audio' },
  { id: 'database', title: 'Databases' },
];

const SOURCE_TYPES: readonly SourceType[] = [
  'local_folder',
  's3',
  'postgres',
  'mysql',
  'sqlite',
  'rest_api',
  'upload',
];

const ALL_MODALITIES: readonly Modality[] = [
  'document',
  'image',
  'video',
  'audio',
  'database',
];

function groupFor(source: SourceDescriptor): Modality {
  if (source.type === 'postgres' || source.type === 'mysql' || source.type === 'sqlite') {
    return 'database';
  }
  return source.modalities[0] ?? 'document';
}

function AddSourceForm({ onDone }: { onDone: () => void }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState('');
  const [type, setType] = useState<SourceType>('local_folder');
  const [connection, setConnection] = useState('');
  const [modalities, setModalities] = useState<readonly Modality[]>(['document']);

  const create = useMutation({
    mutationFn: () =>
      createSource({
        name: name.trim(),
        type,
        modalities: [...modalities],
        connection: connection.trim() ? { path: connection.trim() } : {},
        enabled: true,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.sources });
      onDone();
    },
  });

  return (
    <div className="flex flex-col gap-3 border-t border-rule p-3">
      <div className="grid gap-3 md:grid-cols-3">
        <TextField
          label="Name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Incident reports"
        />
        <SelectField
          label="Type"
          value={type}
          onChange={(event) => setType(event.target.value as SourceType)}
        >
          {SOURCE_TYPES.map((candidate) => (
            <option key={candidate} value={candidate}>
              {SOURCE_TYPE_LABEL[candidate]}
            </option>
          ))}
        </SelectField>
        <TextField
          label="Location"
          hint="path, bucket or DSN host"
          value={connection}
          mono
          onChange={(event) => setConnection(event.target.value)}
          placeholder="/data/incident-reports"
        />
      </div>

      <div className="flex flex-col gap-1">
        <span className="text-micro font-semibold uppercase tracking-[0.08em] text-ink-1">
          Modalities
        </span>
        <div className="flex flex-wrap gap-1.5">
          {ALL_MODALITIES.map((modality) => (
            <SegmentButton
              key={modality}
              selected={modalities.includes(modality)}
              onClick={() =>
                setModalities((current) =>
                  current.includes(modality)
                    ? current.filter((value) => value !== modality)
                    : [...current, modality],
                )
              }
            >
              {MODALITY_LABEL[modality]}
            </SegmentButton>
          ))}
        </div>
      </div>

      <p className="max-w-prose text-micro text-ink-2">
        Credentials are never sent through this form. The API stores secrets in its credential store
        and returns only a reference, so nothing sensitive is held in the source record.
      </p>

      <div className="flex items-center gap-2">
        <Button
          variant="primary"
          onClick={() => create.mutate()}
          disabled={!name.trim() || modalities.length === 0 || create.isPending}
        >
          {create.isPending ? 'Registering…' : 'Register source'}
        </Button>
        <Button variant="quiet" onClick={onDone}>
          Cancel
        </Button>
      </div>

      {create.isError && <ErrorState error={create.error} context="Registering the source" className="px-0" />}
    </div>
  );
}

export function SourcesDivision() {
  const session = useSession();
  const [adding, setAdding] = useState(false);

  const query = useQuery({
    queryKey: queryKeys.sources,
    queryFn: ({ signal }) => listSources(signal),
  });

  const sources = query.data ?? [];

  return (
    <Division>
      <DivisionIntro
        title="Sources"
        lede="Everything SPECTRA is allowed to read, grouped by what it holds. Reliability scores on evidence come from here, so a source's status is part of the answer."
        actions={
          session.can('manage_sources') && (
            <Button variant="primary" onClick={() => setAdding((value) => !value)}>
              {adding ? 'Close form' : 'Add source'}
            </Button>
          )
        }
      />

      <div className="flex flex-col gap-3">
        {adding && (
          <Leaf>
            <LeafHead title="Register a source" />
            <AddSourceForm onDone={() => setAdding(false)} />
          </Leaf>
        )}

        {query.isPending && (
          <Leaf>
            <LeafHead title="Loading registry" />
            <SkeletonRows rows={5} />
          </Leaf>
        )}

        {query.isError && (
          <ErrorState error={query.error} context="Source registry" onRetry={() => query.refetch()} />
        )}

        {query.isSuccess && sources.length === 0 && (
          <Leaf>
            <EmptyState
              title="The registry is empty"
              body="SPECTRA has nothing to read. Register a folder, a bucket, a database or an API and run a sync to populate the index."
              action={
                session.can('manage_sources') && (
                  <Button variant="primary" onClick={() => setAdding(true)}>
                    Add the first source
                  </Button>
                )
              }
            />
          </Leaf>
        )}

        {GROUPS.map((group) => {
          const rows = sources.filter((source) => groupFor(source) === group.id);
          if (rows.length === 0) return null;
          return (
            <Leaf key={group.id}>
              <LeafHead title={group.title} count={rows.length} />
              <ul className="flex flex-col">
                {rows.map((source) => (
                  <SourceRow key={source.source_id} source={source} />
                ))}
              </ul>
            </Leaf>
          );
        })}
      </div>
    </Division>
  );
}
