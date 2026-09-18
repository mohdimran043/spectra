'use client';

import { useMutation } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';

import { cn } from '@/components/cn';
import { IconSearch } from '@/components/icons';
import { ErrorState } from '@/components/states';
import { runAnswer } from '@/lib/api';
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

  const search = useMutation({
    mutationFn: (q: string) => runAnswer(q),
    onSuccess: (_data, q) => setAsked(q),
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const trimmed = query.trim();
    if (!trimmed || search.isPending) return;
    search.mutate(trimmed);
  };

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
            <NothingMatched query={asked} screened={data.results.total_candidates} />
          ) : (
            <>
              {data.answer && <AnswerPanel answer={data} />}
              <ResultSummary
                count={hits.length}
                screened={data.results.total_candidates}
                ms={data.results.latency_ms}
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

function ResultSummary({ count, screened, ms }: { count: number; screened: number; ms: number }) {
  return (
    <p className="border-b border-rule pb-2 text-micro text-ink-2">
      <span className="font-mono tabular text-ink-1">{count}</span>{' '}
      {count === 1 ? 'result' : 'results'} from{' '}
      <span className="font-mono tabular">{screened.toLocaleString()}</span> candidates screened in{' '}
      <span className="font-mono tabular">{(ms / 1000).toFixed(2)}s</span>
    </p>
  );
}

/**
 * Not an error. The index was searched in full and nothing in it qualified,
 * which is the honest outcome for a term the corpus does not contain.
 */
function NothingMatched({ query, screened }: { query: string; screened: number }) {
  return (
    <div className="border border-rule bg-leaf-raised px-5 py-10 text-center">
      <p className="text-body font-semibold text-ink">Nothing matched &ldquo;{query}&rdquo;.</p>
      <p className="mx-auto mt-2 max-w-[52ch] text-mark text-ink-2">
        All <span className="font-mono tabular">{screened.toLocaleString()}</span> candidates were
        screened and none carry this term, a matching identifier, or a close enough reading to be
        worth showing. Try different words, or check Sources for what is indexed.
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
