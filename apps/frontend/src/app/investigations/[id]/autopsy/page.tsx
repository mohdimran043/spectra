import { AutopsyDivision } from '@/features/autopsy/autopsy-division';

export const metadata = { title: 'Search autopsy' };

export default function AutopsyPage({ params }: { params: { id: string } }) {
  return <AutopsyDivision investigationId={params.id} />;
}
