'use client';

import { useMutation } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { useState } from 'react';

import { Button } from '@/components/button';
import { Mark } from '@/components/chip';
import { IconChevronRight, IconLinkOut } from '@/components/icons';
import { Leaf } from '@/components/leaf';
import { ErrorState } from '@/components/states';
import { continueInvestigation, investigationExportUrl } from '@/lib/api';
import { useSession } from '@/features/shell/session-context';

/**
 * The record's opening: the question as asked, the identifiers it can be cited
 * by, and the two things an operator does next — continue the line of enquiry,
 * or take the case report away.
 */
export function QuestionHeader({
  investigationId,
  question,
  caseId,
  mode,
  hasConclusion,
}: {
  investigationId: string;
  question: string | null;
  caseId: string | null;
  mode: string | null;
  hasConclusion: boolean;
}) {
  const router = useRouter();
  const session = useSession();
  const [followUp, setFollowUp] = useState('');

  const continuation = useMutation({
    mutationFn: (text: string) => continueInvestigation(investigationId, text),
    onSuccess: (result) => {
      setFollowUp('');
      if (result.investigation_id !== investigationId) {
        router.push(`/investigations/${result.investigation_id}`);
      } else {
        router.refresh();
      }
    },
  });

  return (
    <Leaf>
      <div className="flex flex-col gap-2 p-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-micro font-semibold uppercase tracking-[0.1em] text-ink-1">
            Question
          </span>
          <Mark mono>{investigationId}</Mark>
          {caseId && <Mark mono>{caseId}</Mark>}
          {mode && <Mark>{mode}</Mark>}
          <div className="ml-auto flex flex-wrap items-center gap-2">
            {hasConclusion && (
              <a
                href="#conclusion"
                className="text-micro uppercase tracking-[0.08em] text-ink-2 underline decoration-rule-strong underline-offset-2 hover:text-ink"
              >
                Jump to conclusion
              </a>
            )}
            {session.can('export') && (
              <>
                <a
                  href={investigationExportUrl(investigationId, 'markdown')}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-micro uppercase tracking-[0.08em] text-ink-2 underline decoration-rule-strong underline-offset-2 hover:text-ink"
                >
                  <IconLinkOut size={11} />
                  Markdown
                </a>
                <a
                  href={investigationExportUrl(investigationId, 'json')}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-micro uppercase tracking-[0.08em] text-ink-2 underline decoration-rule-strong underline-offset-2 hover:text-ink"
                >
                  <IconLinkOut size={11} />
                  JSON
                </a>
              </>
            )}
          </div>
        </div>

        <p className="max-w-[78ch] text-title font-semibold leading-[1.45] text-ink">
          {question ?? (
            <span className="text-ink-2">
              The question text is not carried on the answer contract for this investigation.
            </span>
          )}
        </p>

        {session.can('investigate') && (
          <div className="flex flex-wrap items-end gap-2 border-t border-rule pt-2">
            <div className="min-w-[16rem] flex-1">
              <label htmlFor="continue-question" className="sr-only">
                Continue this investigation
              </label>
              <input
                id="continue-question"
                value={followUp}
                onChange={(event) => setFollowUp(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && followUp.trim()) continuation.mutate(followUp.trim());
                }}
                placeholder="Continue this line of enquiry…"
                className="h-7 w-full rounded-sm border border-rule-strong bg-leaf px-2 text-body text-ink placeholder:text-ink-2"
              />
            </div>
            <Button
              variant="secondary"
              size="md"
              onClick={() => continuation.mutate(followUp.trim())}
              disabled={!followUp.trim() || continuation.isPending}
            >
              {continuation.isPending ? 'Resuming…' : 'Continue'}
              <IconChevronRight size={12} />
            </Button>
          </div>
        )}

        {continuation.isError && (
          <ErrorState error={continuation.error} context="Continuing the investigation" className="px-0" />
        )}
      </div>
    </Leaf>
  );
}
