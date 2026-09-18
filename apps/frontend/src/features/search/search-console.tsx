'use client';

import { useMutation, useQuery } from '@tanstack/react-query';
import { useSearchParams } from 'next/navigation';
import { useEffect, useRef, useState, type FormEvent } from 'react';

import { cn } from '@/components/cn';
import { IconSearch } from '@/components/icons';
import { ErrorState } from '@/components/states';
import { listSources, runAnswer } from '@/lib/api';
import type { SourceDescriptor } from '@/lib/schemas/system';
import type { AnswerResponse } from '@/lib/schemas/search';

import { ResultCard } from './result-card';

/**
 * The product, on one screen.
 *
 * Ask a question; get the passages that answer it, and - when a model can write
 * one grounded in those passages - a short answer above them. Nothing else.
 *
 * The screen has exactly three states and each one says something true: nothing
 * asked yet, nothing matched, or these results. "Nothing matched" is a real
 * answer here, not an error: search screens every candidate and returns none
 * when none of them carry the query's words, its identifiers, or a strong
 * enough reading from the cross-encoder.
 */
export function SearchConsole() {
  const [query, setQuery] = useState('');
  const [asked, setAsked] = useState('');
  /** Empty means every source; the picker never silently narrows a search. */
  const [chosen, setChosen] = useState<readonly string[]>([]);

  const sources = useQuery({
    queryKey: ['sources'],
    queryFn: ({ signal }) => listSources(signal),
    staleTime: 60_000,
  });
  const available = (sources.data ?? []).filter((source) => source.enabled);

  const search = useMutation({
    mutationFn: (q: string) => runAnswer(q, chosen),
    onSuccess: (_data, q) => setAsked(q),
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const trimmed = query.trim();
    if (!trimmed || search.isPending) return;
    search.mutate(trimmed);
  };

  // `/?q=...` re-runs a search from the Activity page. It fires once per
  // distinct query so a re-render never resubmits.
  const params = useSearchParams();
  const deepLink = params.get('q')?.trim() ?? '';
  const ran = useRef<string | null>(null);
  useEffect(() => {
    if (!deepLink || ran.current === deepLink) return;
    ran.current = deepLink;
    setQuery(deepLink);
    search.mutate(deepLink);
    // `search` is a stable mutation object; re-running on its identity would loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deepLink]);

  const data = search.data;
  const hits = data?.results.hits ?? [];
  const settled = search.isSuccess && !search.isPending;

  return (
    <div className="mx-auto w-full max-w-3xl px-5 pb-24">
      <header className={cn('transition-all duration-300', data ? 'pt-8' : 'pt-[16vh]')}>
        {!data && (
          <h1 className="mb-6 text-balance text-2xl font-semibold tracking-[-0.02em] text-ink">
            Search everything you have indexed.
          </h1>
        )}

        <form onSubmit={submit} role="search">
          <label htmlFor="q" className="sr-only">
            Search query
          </label>
          <div
            className={cn(
              'flex items-center gap-3 border border-rule-strong bg-leaf-raised px-4',
              'shadow-leaf transition-shadow focus-within:border-focus',
              'focus-within:shadow-[0_0_0_3px_color-mix(in_srgb,var(--focus)_18%,transparent)]',
            )}
          >
            <IconSearch size={17} className="shrink-0 text-ink-3" aria-hidden="true" />
            <input
              id="q"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Ask a question, or type what you are looking for"
              autoComplete="off"
              className={cn(
                'min-w-0 flex-1 bg-transparent py-3.5 text-body text-ink',
                'placeholder:text-ink-3 focus:outline-none',
              )}
            />
            <button
              type="submit"
              disabled={!query.trim() || search.isPending}
              className={cn(
                'shrink-0 py-1.5 text-mark font-semibold uppercase tracking-[0.06em]',
                'text-focus transition-opacity hover:opacity-70',
                'disabled:cursor-not-allowed disabled:text-ink-3 disabled:hover:opacity-100',
                'focus-visible:outline focus-visible:outline-1 focus-visible:outline-offset-2 focus-visible:outline-focus',
              )}
            >
              {search.isPending ? 'Searching' : 'Search'}
            </button>
          </div>
        </form>

        {available.length > 1 && (
          <SourcePicker sources={available} chosen={chosen} onChange={setChosen} />
        )}

        {!data && !search.isError && (
          <p className="mt-3 max-w-[60ch] text-mark text-ink-2">
            Documents, images, video, audio and records are searched together. If nothing in the
            index matches, you will be told so rather than shown the nearest thing.
          </p>
        )}
      </header>

      {search.isPending && <Searching />}

      {search.isError && (
        <div className="mt-8">
          <ErrorState error={search.error} onRetry={() => search.mutate(asked || query)} />
        </div>
      )}

      {settled && data && (
        <section className="mt-8" aria-live="polite">
          {hits.length === 0 ? (
            <NothingMatched
              query={asked}
              screened={data.results.total_candidates}
              narrowed={chosen.length > 0 ? chosen.length : null}
              total={available.length}
            />
          ) : (
            <>
              {data.answer && <AnswerPanel answer={data} />}
              <ResultSummary
                count={hits.length}
                screened={data.results.total_candidates}
                ms={data.results.latency_ms}
                narrowed={chosen.length > 0 ? chosen.length : null}
                total={available.length}
              />
              <ol className="mt-1">
                {hits.map((hit, index) => (
                  <ResultCard key={hit.chunk_id} hit={hit} rank={index + 1} />
                ))}
              </ol>
            </>
          )}
        </section>
      )}
    </div>
  );
}

/** A short answer, and the numbers of the results it was written from. */
function AnswerPanel({ answer }: { answer: AnswerResponse }) {
  return (
    <div className="mb-8 border-l border-focus bg-leaf-raised py-3.5 pl-4 pr-4">
      <p className="max-w-[68ch] text-prose text-ink">{answer.answer}</p>
      {answer.citations.length > 0 && (
        <p className="mt-2 text-micro text-ink-2">
          Written from {answer.citations.length === 1 ? 'result' : 'results'}{' '}
          <span className="font-mono tabular text-ink-1">{answer.citations.join(', ')}</span> below.
          Check them.
        </p>
      )}
    </div>
  );
}

/**
 * Which sources to search.
 *
 * Nothing selected means everything, which is both the default and the honest
 * reading of an empty filter - a picker that silently narrowed the search would
 * make an empty result set impossible to explain.
 */
function SourcePicker({
  sources,
  chosen,
  onChange,
}: {
  sources: readonly SourceDescriptor[];
  chosen: readonly string[];
  onChange: (next: readonly string[]) => void;
}) {
  const toggle = (id: string) =>
    onChange(chosen.includes(id) ? chosen.filter((s) => s !== id) : [...chosen, id]);

  return (
    <fieldset className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1.5">
      <legend className="sr-only">Sources to search</legend>
      <span className="mr-0.5 text-micro uppercase tracking-[0.07em] text-ink-3">Sources</span>

      <SourceChip
        label="All"
        selected={chosen.length === 0}
        onClick={() => onChange([])}
      />
      {sources.map((source) => (
        <SourceChip
          key={source.source_id}
          label={source.name}
          detail={source.asset_count ? `${source.asset_count.toLocaleString()} items` : undefined}
          selected={chosen.includes(source.source_id)}
          onClick={() => toggle(source.source_id)}
        />
      ))}
    </fieldset>
  );
}

function SourceChip({
  label,
  detail,
  selected,
  onClick,
}: {
  label: string;
  detail?: string;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={selected}
      title={detail}
      className={cn(
        'rounded-full border px-2.5 py-1 text-micro transition-colors',
        'focus-visible:outline focus-visible:outline-1 focus-visible:outline-offset-2 focus-visible:outline-focus',
        selected
          ? 'border-focus bg-held-weak font-semibold text-ink'
          : 'border-rule bg-leaf text-ink-2 hover:border-rule-strong hover:text-ink-1',
      )}
    >
      {label}
    </button>
  );
}

/** How many sources a narrowed search actually looked at. */
function scopeNote(narrowed: number | null, total: number): string {
  return narrowed === null ? '' : ` across ${narrowed} of ${total} sources`;
}

function ResultSummary({
  count,
  screened,
  ms,
  narrowed,
  total,
}: {
  count: number;
  screened: number;
  ms: number;
  narrowed: number | null;
  total: number;
}) {
  return (
    <p className="border-b border-rule pb-2 text-micro text-ink-2">
      <span className="font-mono tabular text-ink-1">{count}</span>{' '}
      {count === 1 ? 'result' : 'results'} from{' '}
      <span className="font-mono tabular">{screened.toLocaleString()}</span> candidates screened in{' '}
      <span className="font-mono tabular">{(ms / 1000).toFixed(2)}s</span>
      {scopeNote(narrowed, total)}
    </p>
  );
}

/**
 * Not an error. The index was searched in full and nothing in it qualified,
 * which is the honest outcome for a term the corpus does not contain.
 */
function NothingMatched({
  query,
  screened,
  narrowed,
  total,
}: {
  query: string;
  screened: number;
  narrowed: number | null;
  total: number;
}) {
  return (
    <div className="border border-rule bg-leaf-raised px-5 py-10 text-center">
      <p className="text-body font-semibold text-ink">Nothing matched &ldquo;{query}&rdquo;.</p>
      <p className="mx-auto mt-2 max-w-[52ch] text-mark text-ink-2">
        All <span className="font-mono tabular">{screened.toLocaleString()}</span> candidates were
        screened{scopeNote(narrowed, total)} and none carry this term, a matching identifier, or a
        close enough reading to be worth showing.{' '}
        {narrowed !== null
          ? 'Widen to all sources, or try different words.'
          : 'Try different words, or check Sources for what is indexed.'}
      </p>
    </div>
  );
}

function Searching() {
  return (
    <div className="mt-8" aria-live="polite">
      <p className="sr-only">Searching</p>
      <div className="border-b border-rule pb-2">
        <span className="block h-2 w-40 animate-pulse bg-board-sunk" />
      </div>
      {[0, 1, 2, 3].map((row) => (
        <div key={row} className="flex gap-4 border-b border-rule px-2 py-4">
          <span className="mt-px h-3 w-5 shrink-0 animate-pulse bg-board-sunk" />
          <span className="flex-1 space-y-2">
            <span className="block h-2.5 w-28 animate-pulse bg-board-sunk" />
            <span className="block h-3 w-full animate-pulse bg-board-sunk" />
            <span className="block h-3 w-4/5 animate-pulse bg-board-sunk" />
          </span>
        </div>
      ))}
    </div>
  );
}
