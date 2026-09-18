'use client';

import { useMutation, useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import { Button } from '@/components/button';
import { Mark, StatusChip } from '@/components/chip';
import { Disclosure } from '@/components/disclosure';
import { IconLinkOut, IconSql } from '@/components/icons';
import { Leaf, LeafHead } from '@/components/leaf';
import { SelectField, TextField } from '@/components/field';
import { EmptyState, ErrorState, LoadingRule } from '@/components/states';
import { listSources, runDatabaseQuery } from '@/lib/api';
import { formatLatency } from '@/lib/format';
import { queryKeys } from '@/lib/query-keys';

const SQL_SOURCE_TYPES = new Set(['postgres', 'mysql', 'sqlite']);

/**
 * The database tab shows the generated SQL every time, not on request only —
 * `docs/api.md` returns `sql` for exactly this reason. An operator who cannot
 * read the query cannot vouch for the row.
 */
export function DatabasePanel() {
  const [sourceId, setSourceId] = useState('');
  const [question, setQuestion] = useState('');

  const sources = useQuery({
    queryKey: queryKeys.sources,
    queryFn: ({ signal }) => listSources(signal),
  });

  const sqlSources = (sources.data ?? []).filter((source) => SQL_SOURCE_TYPES.has(source.type));
  const effectiveSourceId = sourceId || sqlSources[0]?.source_id || '';

  const mutation = useMutation({
    mutationFn: () => runDatabaseQuery({ source_id: effectiveSourceId, question, sql: null, params: {} }),
  });

  const result = mutation.data;

  return (
    <div className="flex flex-col gap-3">
      <Leaf>
        <LeafHead title="Ask the database" hint="Natural language is translated to a read-only SELECT" />
        <div className="grid gap-3 p-3 md:grid-cols-[14rem_minmax(0,1fr)_auto] md:items-end">
          <SelectField
            label="Source"
            value={effectiveSourceId}
            onChange={(event) => setSourceId(event.target.value)}
            disabled={sqlSources.length === 0}
          >
            {sqlSources.length === 0 && <option value="">No SQL source registered</option>}
            {sqlSources.map((source) => (
              <option key={source.source_id} value={source.source_id}>
                {source.name}
              </option>
            ))}
          </SelectField>
          <TextField
            label="Question"
            value={question}
            placeholder="failed transactions for C82731"
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && question.trim() && effectiveSourceId) mutation.mutate();
            }}
          />
          <Button
            variant="primary"
            size="md"
            onClick={() => mutation.mutate()}
            disabled={!question.trim() || !effectiveSourceId || mutation.isPending}
          >
            <IconSql size={12} />
            {mutation.isPending ? 'Querying…' : 'Run query'}
          </Button>
        </div>
      </Leaf>

      {sources.isError && <ErrorState error={sources.error} context="Source registry" />}
      {mutation.isPending && <LoadingRule label="Generating and executing SQL" />}
      {mutation.isError && (
        <ErrorState error={mutation.error} context="Database query" onRetry={() => mutation.mutate()} />
      )}

      {result && (
        <Leaf>
          <LeafHead
            title="Result"
            count={`${result.row_count} ${result.row_count === 1 ? 'row' : 'rows'}`}
            actions={
              <>
                {result.truncated && <StatusChip tone="caution">Truncated</StatusChip>}
                <Mark mono>{formatLatency(result.latency_ms)}</Mark>
              </>
            }
          />

          {result.rows.length === 0 ? (
            <EmptyState
              title="The query returned no rows"
              body="The SQL below ran successfully against the source and matched nothing. Check the generated predicate."
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-full border-collapse text-mark">
                <thead>
                  <tr className="border-b border-rule-strong">
                    {result.columns.map((column) => (
                      <th
                        key={column}
                        scope="col"
                        className="whitespace-nowrap px-3 py-1.5 text-left text-micro font-semibold uppercase tracking-[0.08em] text-ink-2"
                      >
                        {column}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.rows.map((row, index) => (
                    <tr key={index} className="border-b border-rule last:border-b-0">
                      {result.columns.map((column) => (
                        <td key={column} className="whitespace-nowrap px-3 py-1 font-mono tabular text-ink">
                          {row[column] === null || row[column] === undefined
                            ? '—'
                            : String(row[column])}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <Disclosure summary="View generated SQL" defaultOpen>
            <pre className="overflow-x-auto px-3 py-2 font-mono text-mark leading-[1.35rem] text-ink">
              {result.sql}
            </pre>
            {Object.keys(result.params).length > 0 && (
              <div className="border-t border-rule px-3 py-2">
                <p className="text-micro uppercase tracking-[0.08em] text-ink-2">Bound parameters</p>
                <ul className="mt-1 flex flex-col gap-0.5">
                  {Object.entries(result.params).map(([key, value]) => (
                    <li key={key} className="font-mono text-mark tabular text-ink">
                      <span className="text-ink-2">{key}</span> = {JSON.stringify(value)}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </Disclosure>

          {result.application_links.length > 0 && (
            <div className="flex flex-wrap items-center gap-2 border-t border-rule px-3 py-2">
              <span className="text-micro uppercase tracking-[0.08em] text-ink-2">Open in application</span>
              {result.application_links.map((link) => (
                <a
                  key={`${link.entity_id}-${link.url}`}
                  href={link.url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1.5 rounded-sm border border-rule-strong bg-leaf px-2 py-0.5 text-mark text-ink hover:bg-board-sunk"
                >
                  <IconLinkOut size={11} />
                  {link.label}
                  <span className="font-mono text-micro tabular text-ink-2">{link.record_id}</span>
                  {!link.verified_in_database && (
                    <StatusChip tone="caution">Unverified</StatusChip>
                  )}
                </a>
              ))}
            </div>
          )}
        </Leaf>
      )}
    </div>
  );
}
