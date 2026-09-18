import { NextResponse } from 'next/server';

import { recordHref } from '@/lib/links';
import { loadRecord } from '@/lib/records';
import { attempt } from '@/lib/result';
import { idPatternSource, isRecordType, parseRecordId, RECORD_TYPES } from '@/lib/validation';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

const NO_STORE = { 'Cache-Control': 'no-store' } as const;

interface RouteContext {
  params: { type: string; id: string };
}

/**
 * Existence check used by SPECTRA's application resolver before it emits a
 * deep link. The record type is checked against an allow-list and the id
 * against a strict per-type pattern; neither reaches the database otherwise.
 */
export async function GET(_request: Request, { params }: RouteContext) {
  const type = params.type.toLowerCase();
  if (!isRecordType(type)) {
    return NextResponse.json(
      {
        exists: false,
        record: null,
        error: `Unknown record type "${params.type}".`,
        allowed: RECORD_TYPES,
      },
      { status: 400, headers: NO_STORE },
    );
  }

  const id = parseRecordId(type, params.id);
  if (!id) {
    return NextResponse.json(
      {
        exists: false,
        record: null,
        error: `Malformed ${type} identifier.`,
        expectedPattern: idPatternSource(type),
      },
      { status: 400, headers: NO_STORE },
    );
  }

  const result = await attempt(() => loadRecord(type, id));
  if (!result.ok) {
    return NextResponse.json(
      { exists: false, record: null, error: result.message, detail: result.detail },
      { status: 503, headers: NO_STORE },
    );
  }

  return NextResponse.json(
    {
      exists: result.value !== null,
      type,
      id,
      url: result.value !== null ? recordHref(type, id) : null,
      record: result.value,
    },
    { headers: NO_STORE },
  );
}
