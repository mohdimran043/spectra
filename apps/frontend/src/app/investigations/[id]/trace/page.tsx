import { TraceDivision } from '@/features/investigation/trace-division';

export const metadata = { title: 'Agent trace' };

export default function TracePage({ params }: { params: { id: string } }) {
  return <TraceDivision investigationId={params.id} />;
}
