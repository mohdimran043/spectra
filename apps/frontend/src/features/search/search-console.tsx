'use client';

import { useMutation, useQuery } from '@tanstack/react-query';
import { useRouter, useSearchParams } from 'next/navigation';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { Button, SegmentButton } from '@/components/button';
import { Mark, StatusChip } from '@/components/chip';
import { cn } from '@/components/cn';
import { IconSearch, IconUpload } from '@/components/icons';
import { Leaf, LeafHead } from '@/components/leaf';
import { DegradedBand, EmptyState, ErrorState, SkeletonRows } from '@/components/states';
import { listSources, runImageSearch, runSearch, type SearchScope } from '@/lib/api';
import { formatLatency } from '@/lib/format';
import { queryKeys } from '@/lib/query-keys';
import type { Modality, SearchMode } from '@/lib/schemas/primitives';
import type { SearchResponse } from '@/lib/schemas/search';
import { MODALITY_LABEL } from '@/lib/vocab';
import { DatabasePanel } from './database-panel';
import { ResultCard } from './result-card';
import { StageStrip } from './stage-strip';

interface TabSpec {
  readonly id: string;
  readonly label: string;
  readonly scope: SearchScope | 'database';
  readonly modality?: Modality;
}

const TABS: readonly TabSpec[] = [
  { id: 'unified', label: 'Unified', scope: 'unified' },
  { id: 'documents', label: 'Documents', scope: 'document', modality: 'document' },
  { id: 'images', label: 'Images', scope: 'image', modality: 'image' },
  { id: 'videos', label: 'Videos', scope: 'video', modality: 'video' },
  { id: 'audio', label: 'Audio', scope: 'audio', modality: 'audio' },
  { id: 'database', label: 'Database', scope: 'database' },
];

const DEFAULT_TOP_K = 20;

function emptyFilters() {
  return {
    source_ids: [] as string[],
    modalities: [] as Modality[],
    asset_ids: [] as string[],
    entity_ids: [] as string[],
    occurred_after: null,
    occurred_before: null,
    media_types: [] as string[],
  };
}

/**
 * The search console. Tabs are retrieval scopes, not view filters: each one
 * calls its own endpoint, so "Videos" is a video search rather than a
 * client-side subset of a unified one.
 */
export function SearchConsole() {
  const router = useRouter();
  const params = useSearchParams();
  const fileInput = useRef<HTMLInputElement>(null);

  const initialTab = params.get('tab') ?? 'unified';
  const [tabId, setTabId] = useState(TABS.some((tab) => tab.id === initialTab) ? initialTab : 'unified');
  const [query, setQuery] = useState(params.get('q') ?? '');
  const [mode, setMode] = useState<SearchMode>('fast');
  const [rerank, setRerank] = useState(true);
  const [sourceId, setSourceId] = useState('');
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const assetParam = params.get('asset');

  const activeTab = TABS.find((tab) => tab.id === tabId) ?? TABS[0]!;

  const sources = useQuery({
    queryKey: queryKeys.sources,
    queryFn: ({ signal }) => listSources(signal),
  });

  const search = useMutation({
    mutationFn: ({ imageAssetId }: { imageAssetId?: string } = {}) => {
      if (activeTab.scope === 'database') throw new Error('unreachable');
      return runSearch(activeTab.scope, {
        query,
        mode,
        top_k: DEFAULT_TOP_K,
        rerank,
        include_text: false,
        image_asset_id: imageAssetId ?? null,
        filters: {
          ...emptyFilters(),
          source_ids: sourceId ? [sourceId] : [],
          modalities: activeTab.modality ? [activeTab.modality] : [],
          asset_ids: [],
        },
      });
    },
    onSuccess: setResponse,
  });

  const imageSearch = useMutation({
    mutationFn: (file: File) => runImageSearch(file),
    onSuccess: setResponse,
  });

  const runQuery = useCallback(
    (imageAssetId?: string) => {
      if (activeTab.scope === 'database') return;
      if (!query.trim() && !imageAssetId) return;
      search.mutate({ imageAssetId });
    },
    [activeTab.scope, query, search],
  );

  /** An asset id arriving from an upload runs an image-to-everything search. */
  const startedForAsset = useRef<string | null>(null);
  useEffect(() => {
    if (!assetParam || startedForAsset.current === assetParam) return;
    startedForAsset.current = assetParam;
    setTabId('images');
    search.mutate({ imageAssetId: assetParam });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assetParam]);

  const syncUrl = (nextTab: string, nextQuery: string) => {
    const next = new URLSearchParams();
    if (nextQuery.trim()) next.set('q', nextQuery.trim());
    if (nextTab !== 'unified') next.set('tab', nextTab);
    router.replace(next.toString() ? `/search?${next}` : '/search', { scroll: false });
  };

  const pending = search.isPending || imageSearch.isPending;
  const error = search.error ?? imageSearch.error;
  const understanding = response?.understanding;

  const hits = useMemo(() => response?.hits ?? [], [response]);

  return (
    <div className="flex flex-col gap-3">
      <Leaf>
        <div
          role="tablist"
          aria-label="Retrieval scope"
          className="flex flex-wrap items-stretch border-b border-rule"
        >
          {TABS.map((tab) => {
            const selected = tab.id === tabId;
            return (
              <button
                key={tab.id}
                role="tab"
                type="button"
                aria-selected={selected}
                onClick={() => {
                  setTabId(tab.id);
                  setResponse(null);
                  syncUrl(tab.id, query);
                }}
                className={cn(
                  'relative px-3 py-2 text-mark transition-colors duration-100 ease-step',
                  selected
                    ? 'bg-board font-semibold text-ink after:absolute after:inset-x-0 after:bottom-[-1px] after:h-0.5 after:bg-ink'
                    : 'text-ink-1 hover:bg-board-sunk hover:text-ink',
                )}
              >
                {tab.label}
              </button>
            );
          })}
        </div>

        {activeTab.scope !== 'database' && (
          <div className="flex flex-col gap-2 p-3">
            <div className="flex flex-wrap items-end gap-2">
              <div className="min-w-[16rem] flex-1">
                <label htmlFor="search-query" className="sr-only">
                  Search query
                </label>
                <input
                  id="search-query"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') {
                      syncUrl(tabId, query);
                      runQuery();
                    }
                  }}
                  placeholder={`Search ${activeTab.label.toLowerCase()}…`}
                  className="h-9 w-full rounded-sm border border-rule-strong bg-leaf px-2.5 text-prose text-ink placeholder:text-ink-2"
                />
              </div>
              <div className="flex items-center gap-1.5" role="group" aria-label="Retrieval depth">
                <SegmentButton selected={mode === 'fast'} onClick={() => setMode('fast')}>
                  Fast
                </SegmentButton>
                <SegmentButton selected={mode === 'deep'} onClick={() => setMode('deep')}>
                  Deep
                </SegmentButton>
              </div>
              <SegmentButton selected={rerank} onClick={() => setRerank((value) => !value)}>
                Rerank
              </SegmentButton>
              <Button
                variant="primary"
                size="lg"
                onClick={() => {
                  syncUrl(tabId, query);
                  runQuery();
                }}
                disabled={pending || !query.trim()}
              >
                <IconSearch size={13} />
                {pending ? 'Searching…' : 'Search'}
              </Button>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <label htmlFor="search-source" className="text-micro uppercase tracking-[0.08em] text-ink-2">
                Source
              </label>
              <select
                id="search-source"
                value={sourceId}
                onChange={(event) => setSourceId(event.target.value)}
                className="h-6 rounded-sm border border-rule-strong bg-leaf px-1.5 text-mark text-ink"
              >
                <option value="">All permitted sources</option>
                {(sources.data ?? []).map((source) => (
                  <option key={source.source_id} value={source.source_id}>
                    {source.name}
                  </option>
                ))}
              </select>

              {activeTab.id === 'images' && (
                <>
                  <Button size="sm" variant="secondary" onClick={() => fileInput.current?.click()}>
                    <IconUpload size={11} />
                    Search by image
                  </Button>
                  <input
                    ref={fileInput}
                    type="file"
                    accept="image/*"
                    className="sr-only"
                    aria-label="Search by image file"
                    onChange={(event) => {
                      const file = event.target.files?.[0];
                      if (file) imageSearch.mutate(file);
                      event.target.value = '';
                    }}
                  />
                </>
              )}
            </div>
          </div>
        )}
      </Leaf>

      {activeTab.scope === 'database' ? (
        <DatabasePanel />
      ) : (
        <>
          {error && (
            <ErrorState error={error} context="Search" onRetry={() => runQuery()} />
          )}

          {pending && (
            <Leaf>
              <LeafHead title="Retrieving" />
              <SkeletonRows rows={5} />
            </Leaf>
          )}

          {!pending && response && (
            <>
              {response.degraded && <DegradedBand reasons={response.degraded_reasons} />}

              {understanding && (
                <Leaf>
                  <LeafHead title="Image understanding" hint="What the vision path read before searching" />
                  <div className="flex flex-col gap-2 p-3">
                    {understanding.caption && (
                      <p className="text-body text-ink">
                        <span className="text-ink-2">Caption </span>
                        {understanding.caption}
                      </p>
                    )}
                    {understanding.ocr_text && (
                      <p className="whitespace-pre-wrap font-mono text-mark text-ink-1">
                        {understanding.ocr_text}
                      </p>
                    )}
                    {understanding.detected_entities.length > 0 && (
                      <p className="text-mark text-ink-2">
                        {understanding.detected_entities.length} entities detected
                      </p>
                    )}
                  </div>
                </Leaf>
              )}

              <StageStrip response={response} />

              <Leaf>
                <LeafHead
                  title="Results"
                  count={hits.length}
                  actions={
                    <>
                      <Mark mono>{response.total_candidates} candidates</Mark>
                      <Mark mono>{formatLatency(response.latency_ms)}</Mark>
                      <StatusChip tone="quiet">{response.mode}</StatusChip>
                    </>
                  }
                />
                {hits.length === 0 ? (
                  <EmptyState
                    title="Nothing matched"
                    body={`${response.total_candidates} candidates were generated and none survived ranking. Widen the source filter, switch to Deep mode, or check that the relevant source has finished indexing.`}
                  />
                ) : (
                  <div>
                    {hits.map((hit) => (
                      <ResultCard key={hit.chunk_id} hit={hit} />
                    ))}
                  </div>
                )}
              </Leaf>
            </>
          )}

          {!pending && !response && !error && (
            <Leaf>
              <EmptyState
                title={`${MODALITY_LABEL[activeTab.modality ?? 'external']} search is ready`}
                body={
                  activeTab.id === 'unified'
                    ? 'Ask across every permitted source at once. Matches come back marked, scored and openable at their exact page, frame, segment or row.'
                    : `Scoped to ${activeTab.label.toLowerCase()}. The same ranking signals apply; only the candidate pool changes.`
                }
              />
            </Leaf>
          )}
        </>
      )}
    </div>
  );
}
