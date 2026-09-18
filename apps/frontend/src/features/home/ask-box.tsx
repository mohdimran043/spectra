'use client';

import { useMutation } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { useRef, useState } from 'react';

import { Button, SegmentButton } from '@/components/button';
import { cn } from '@/components/cn';
import { IconChevronRight } from '@/components/icons';
import { ErrorState } from '@/components/states';
import { createInvestigation } from '@/lib/api';
import type { SearchMode } from '@/lib/schemas/primitives';
import { useSession } from '@/features/shell/session-context';

const MODE_EXPLANATION: Record<SearchMode, string> = {
  fast: 'One retrieval pass over the fastest sources. Answers a lookup in seconds.',
  deep: 'Claims weighed one by one, disproof probes and verification. Minutes, not seconds.',
};

const EXAMPLES: readonly string[] = [
  'Investigate why transaction TX82931 failed and show me the supporting evidence.',
  'Which incidents mention the same authentication service as INC1829?',
  'Reconstruct the timeline for customer C82731 across every source.',
];

/**
 * The ask field is the first viewport's thesis, not a search bar. It is set at
 * reading scale, it names what each mode actually costs, and it hands the
 * operator straight to a live investigation record.
 */
export function AskBox({ assetIds = [] }: { assetIds?: readonly string[] }) {
  const router = useRouter();
  const session = useSession();
  const [question, setQuestion] = useState('');
  const [mode, setMode] = useState<SearchMode>('deep');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const mutation = useMutation({
    mutationFn: (input: { question: string; mode: SearchMode }) =>
      createInvestigation({
        question: input.question,
        mode: input.mode,
        asset_ids: [...assetIds],
        stream: true,
      }),
    onSuccess: (result) => router.push(`/investigations/${result.investigation_id}`),
  });

  const canInvestigate = session.can('investigate');
  const trimmed = question.trim();
  const disabled = !canInvestigate || trimmed.length === 0 || mutation.isPending;

  const submit = () => {
    if (disabled) return;
    mutation.mutate({ question: trimmed, mode });
  };

  return (
    <div className="flex flex-col">
      <div className="ruled border border-rule-strong bg-leaf">
        <label htmlFor="ask-question" className="sr-only">
          Ask an investigative question
        </label>
        <textarea
          id="ask-question"
          ref={textareaRef}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
              event.preventDefault();
              submit();
            }
          }}
          rows={3}
          spellCheck={false}
          placeholder="Ask what happened, and to what."
          disabled={!canInvestigate}
          className={cn(
            'w-full resize-none bg-transparent px-4 pt-3 text-prose leading-[1.4rem] text-ink',
            'placeholder:text-ink-2 focus:outline-none disabled:cursor-not-allowed',
          )}
        />
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-rule px-3 py-2">
          <div className="flex items-center gap-1.5" role="group" aria-label="Investigation depth">
            <SegmentButton selected={mode === 'fast'} onClick={() => setMode('fast')}>
              Fast
            </SegmentButton>
            <SegmentButton selected={mode === 'deep'} onClick={() => setMode('deep')}>
              Deep
            </SegmentButton>
          </div>
          <p className="min-w-0 flex-1 text-micro text-ink-2">{MODE_EXPLANATION[mode]}</p>
          {assetIds.length > 0 && (
            <span className="font-mono text-micro tabular text-ink-1">
              {assetIds.length} uploaded {assetIds.length === 1 ? 'asset' : 'assets'} attached
            </span>
          )}
          <Button variant="primary" size="lg" onClick={submit} disabled={disabled}>
            {mutation.isPending ? 'Opening record…' : 'Open investigation'}
            <IconChevronRight size={13} />
          </Button>
        </div>
      </div>

      {!canInvestigate && (
        <p className="mt-2 text-mark text-caution">
          The viewer role cannot open investigations. Switch to analyst or admin in the record line
          to ask a question.
        </p>
      )}

      {mutation.isError && (
        <ErrorState
          error={mutation.error}
          context="Opening the investigation"
          onRetry={() => mutation.reset()}
          className="px-0"
        />
      )}

      <div className="mt-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-micro uppercase tracking-[0.08em] text-ink-2">Try</span>
        {EXAMPLES.map((example) => (
          <button
            key={example}
            type="button"
            onClick={() => {
              setQuestion(example);
              textareaRef.current?.focus();
            }}
            disabled={!canInvestigate}
            className="text-left text-mark text-ink-1 underline decoration-rule-strong underline-offset-2 hover:text-ink hover:decoration-ink disabled:text-ink-3 disabled:no-underline"
          >
            {example}
          </button>
        ))}
      </div>
    </div>
  );
}
