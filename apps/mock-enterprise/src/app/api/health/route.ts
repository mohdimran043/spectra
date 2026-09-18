import { NextResponse } from 'next/server';

import { activeBackend, activeBackendDescription } from '@/lib/db';
import { countEntities } from '@/lib/queries';
import { attempt } from '@/lib/result';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

const NO_STORE = { 'Cache-Control': 'no-store' } as const;

/** Liveness plus a real round-trip to the enterprise database. */
export async function GET() {
  let database: string;
  try {
    database = activeBackend();
  } catch (error) {
    return NextResponse.json(
      {
        status: 'error',
        database: null,
        counts: null,
        detail: error instanceof Error ? error.message : 'Invalid database configuration.',
      },
      { status: 503, headers: NO_STORE },
    );
  }

  const result = await attempt(countEntities);
  if (!result.ok) {
    return NextResponse.json(
      { status: 'error', database, counts: null, detail: result.detail ?? result.message },
      { status: 503, headers: NO_STORE },
    );
  }

  return NextResponse.json(
    {
      status: 'ok',
      database,
      source: activeBackendDescription(),
      counts: result.value,
    },
    { headers: NO_STORE },
  );
}
