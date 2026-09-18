import { Suspense } from 'react';

import { LoadingRule } from '@/components/states';
import { GraphDivision } from '@/features/graph/graph-division';

export const metadata = { title: 'Evidence graph' };

export default function GraphPage() {
  return (
    <Suspense fallback={<LoadingRule label="Preparing the graph" />}>
      <GraphDivision />
    </Suspense>
  );
}
