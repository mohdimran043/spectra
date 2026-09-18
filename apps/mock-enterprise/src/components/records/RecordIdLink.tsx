import Link from 'next/link';

import { EMPTY_VALUE } from '@/lib/format';
import { recordHref } from '@/lib/links';
import type { RecordType } from '@/lib/types';

interface RecordIdLinkProps {
  type: RecordType;
  id: string | null | undefined;
}

/** Monospaced identifier link. The id always originates from a query result. */
export function RecordIdLink({ type, id }: RecordIdLinkProps) {
  if (!id) return <span className="text-ink-faint">{EMPTY_VALUE}</span>;
  return (
    <Link href={recordHref(type, id)} className="font-mono">
      {id}
    </Link>
  );
}
