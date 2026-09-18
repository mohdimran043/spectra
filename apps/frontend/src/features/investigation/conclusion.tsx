'use client';

import Link from 'next/link';

import { Mark, StatusChip } from '@/components/chip';
import { cn } from '@/components/cn';
import { IconLinkOut, IconWarning } from '@/components/icons';
import { Leaf, LeafHead, Reading, Rule } from '@/components/leaf';
import { Gauge } from '@/components/meter';
import { formatPercent, formatScore } from '@/lib/format';
import type { InvestigationAnswer } from '@/lib/schemas/investigation';
import {
  ANSWER_STATUS_LABEL,
  ANSWER_STATUS_TONE,
  CONFIDENCE_LABEL_TEXT,
  CONFIDENCE_TONE,
} from '@/lib/vocab';

function independentSourceCount(answer: InvestigationAnswer): number {
  return new Set(answer.evidence.map((item) => item.provenance.source_id)).size;
}

/**
 * Abstention is rendered as abstention. When the API returns
 * `insufficient_evidence` the screen leads with that fact and with what is
 * missing — it does not dress a non-answer as an answer, and it does not bury
 * the status under a paragraph of prose.
 */
function Abstention({ answer }: { answer: InvestigationAnswer }) {
  return (
    <section className="border border-stamp bg-stamp-weak" aria-labelledby="abstention-heading">
      <div className="flex flex-wrap items-center gap-2 border-b border-stamp/40 px-3 py-2">
        <IconWarning size={15} className="text-stamp" />
        <h2
          id="abstention-heading"
          className="text-mark font-semibold uppercase tracking-[0.14em] text-stamp"
        >
          Insufficient evidence — no conclusion offered
        </h2>
      </div>
      <div className="flex flex-col gap-2 px-3 py-3">
        <p className="max-w-[68ch] text-prose text-ink">
          {answer.answer ||
            'SPECTRA did not find enough independent, reliable evidence to answer this question, and is declining to state one.'}
        </p>
        <div className="flex flex-wrap gap-x-6 gap-y-2">
          <Reading
            label="Confidence"
            value={`${CONFIDENCE_LABEL_TEXT[answer.confidence_label]} · ${formatScore(answer.confidence)}`}
          />
          <Reading label="Evidence gathered" value={String(answer.evidence.length)} />
          <Reading label="Independent sources" value={String(independentSourceCount(answer))} />
          <Reading label="Hypotheses tested" value={String(answer.hypotheses.length)} />
        </div>
        {answer.followups.length > 0 && (
          <div>
            <p className="text-micro font-semibold uppercase tracking-[0.08em] text-ink-1">
              What would settle it
            </p>
            <ul className="mt-1 flex list-disc flex-col gap-0.5 pl-4">
              {answer.followups.map((followup) => (
                <li key={followup} className="text-body text-ink">
                  {followup}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </section>
  );
}

export function Conclusion({ answer }: { answer: InvestigationAnswer }) {
  if (answer.status === 'insufficient_evidence') return <Abstention answer={answer} />;

  const sources = independentSourceCount(answer);
  const contradictions = answer.contradictions.length;

  return (
    <Leaf>
      <LeafHead
        title="Conclusion"
        actions={
          <>
            <StatusChip tone={ANSWER_STATUS_TONE[answer.status]}>
              {ANSWER_STATUS_LABEL[answer.status]}
            </StatusChip>
            <StatusChip tone={CONFIDENCE_TONE[answer.confidence_label]}>
              {CONFIDENCE_LABEL_TEXT[answer.confidence_label]} · {formatScore(answer.confidence)}
            </StatusChip>
          </>
        }
      />

      <div className="flex flex-col gap-3 p-3">
        <p className="max-w-[72ch] whitespace-pre-wrap text-prose text-ink">{answer.answer}</p>

        <div className="max-w-[22rem]">
          <Gauge
            value={answer.confidence}
            tone={CONFIDENCE_TONE[answer.confidence_label]}
            label="Confidence"
            reading={`${CONFIDENCE_LABEL_TEXT[answer.confidence_label]} · ${formatPercent(answer.confidence, 0)}`}
          />
        </div>

        <div className="flex flex-wrap gap-x-6 gap-y-2">
          <Reading
            label="Supported by"
            value={`${sources} independent ${sources === 1 ? 'source' : 'sources'}`}
            mono={false}
          />
          <Reading
            label="Contradictions"
            value={contradictions === 0 ? 'none detected' : `${contradictions} on the record`}
            mono={false}
            tone={contradictions > 0 ? 'text-stamp font-semibold' : undefined}
          />
          <Reading label="Evidence used" value={String(answer.evidence.length)} />
          <Reading label="Claims" value={String(answer.claims.length)} />
        </div>

        {answer.claims.length > 0 && (
          <>
            <Rule />
            <div>
              <p className="text-micro font-semibold uppercase tracking-[0.08em] text-ink-1">
                Claims and their exhibits
              </p>
              <ul className="mt-1.5 flex flex-col gap-1.5">
                {answer.claims.map((claim) => (
                  <li key={claim.claim_id} className="flex flex-wrap items-baseline gap-2">
                    <span className="min-w-0 flex-1 text-body text-ink">{claim.text}</span>
                    <Mark mono>{formatScore(claim.confidence)}</Mark>
                    <span className="font-mono text-micro tabular text-ink-2">
                      {claim.evidence_ids.length} exhibit
                      {claim.evidence_ids.length === 1 ? '' : 's'}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          </>
        )}

        {answer.application_links.length > 0 && (
          <>
            <Rule />
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-micro font-semibold uppercase tracking-[0.08em] text-ink-1">
                Open in the application
              </span>
              {answer.application_links.map((link) => (
                <a
                  key={`${link.entity_id}-${link.url}`}
                  href={link.url}
                  target="_blank"
                  rel="noreferrer"
                  className={cn(
                    'inline-flex items-center gap-1.5 rounded-sm border px-2 py-0.5 text-mark hover:bg-board-sunk',
                    link.verified_in_database ? 'border-seal text-ink' : 'border-caution text-ink',
                  )}
                >
                  <IconLinkOut size={11} />
                  {link.label}
                  <span className="font-mono text-micro tabular text-ink-2">{link.record_id}</span>
                  {!link.verified_in_database && (
                    <StatusChip tone="caution">Not verified in database</StatusChip>
                  )}
                </a>
              ))}
            </div>
          </>
        )}

        {answer.explanation.reasons.length > 0 && (
          <>
            <Rule />
            <div>
              <p className="text-micro font-semibold uppercase tracking-[0.08em] text-ink-1">
                Why these sources
              </p>
              <ul className="mt-1 flex list-disc flex-col gap-0.5 pl-4">
                {answer.explanation.reasons.map((reason) => (
                  <li key={reason} className="text-body text-ink-1">
                    {reason}
                  </li>
                ))}
              </ul>
              <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1">
                {answer.explanation.sources_selected.length > 0 && (
                  <span className="text-micro text-ink-2">
                    Selected:{' '}
                    <span className="font-mono text-ink-1">
                      {answer.explanation.sources_selected.join(', ')}
                    </span>
                  </span>
                )}
                {answer.explanation.sources_skipped.map((skipped, index) => (
                  <span key={index} className="text-micro text-caution">
                    Skipped {skipped.source ?? 'source'} — {skipped.reason ?? 'no reason given'}
                  </span>
                ))}
              </div>
            </div>
          </>
        )}

        {answer.followups.length > 0 && (
          <>
            <Rule />
            <div>
              <p className="text-micro font-semibold uppercase tracking-[0.08em] text-ink-1">
                Suggested follow-ups
              </p>
              <ul className="mt-1 flex list-disc flex-col gap-0.5 pl-4">
                {answer.followups.map((followup) => (
                  <li key={followup} className="text-body text-ink-1">
                    {followup}
                  </li>
                ))}
              </ul>
            </div>
          </>
        )}

        <Rule />
        <div className="flex flex-wrap gap-3">
          <Link
            href={`/investigations/${answer.investigation_id}/autopsy`}
            className="text-mark text-ink-1 underline decoration-rule-strong underline-offset-2 hover:text-ink"
          >
            Search autopsy
          </Link>
          <Link
            href={`/investigations/${answer.investigation_id}/trace`}
            className="text-mark text-ink-1 underline decoration-rule-strong underline-offset-2 hover:text-ink"
          >
            Full agent trace
          </Link>
        </div>
      </div>
    </Leaf>
  );
}
