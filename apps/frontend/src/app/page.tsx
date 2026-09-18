'use client';

import Link from 'next/link';

import { linkButtonClasses } from '@/components/button-styles';
import { IconDemo } from '@/components/icons';
import { Leaf, LeafHead } from '@/components/leaf';
import { Division } from '@/components/page';
import { Wordmark } from '@/components/wordmark';
import { AskBox } from '@/features/home/ask-box';
import { HealthStrip } from '@/features/home/health-strip';
import { RecentRecord } from '@/features/home/recent-record';
import { SourceSummary } from '@/features/home/source-summary';
import { DropTargets, UploadQueue } from '@/features/uploads/drop-targets';
import { useUploadQueue } from '@/features/uploads/use-upload-queue';
import { useSession } from '@/features/shell/session-context';

export default function HomePage() {
  const uploads = useUploadQueue();
  const session = useSession();

  return (
    <Division>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-4 border-b border-rule pb-4">
        <div>
          <Wordmark height={26} className="text-ink" />
          <p className="mt-1.5 text-body uppercase tracking-[0.22em] text-ink-2">
            AI Investigation Intelligence
          </p>
        </div>
        <Link href="/demo" className={linkButtonClasses('secondary', 'lg')}>
          <IconDemo size={13} />
          Launch guided demo
        </Link>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
        <div className="flex flex-col gap-4">
          <AskBox assetIds={uploads.readyAssetIds} />

          <Leaf>
            <LeafHead
              title="Add evidence"
              hint="Dropped files are ingested, indexed and attached to your next question"
            />
            <div className="p-2.5">
              <DropTargets onFiles={uploads.enqueue} disabled={!session.can('upload')} />
              {!session.can('upload') && (
                <p className="mt-2 px-0.5 text-micro text-caution">
                  The viewer role cannot upload. Switch to analyst or admin in the record line.
                </p>
              )}
            </div>
            <UploadQueue entries={uploads.entries} onDismiss={uploads.dismiss} />
          </Leaf>

          <RecentRecord />
        </div>

        <div className="flex flex-col gap-4">
          <HealthStrip />
          <SourceSummary />
        </div>
      </div>
    </Division>
  );
}
