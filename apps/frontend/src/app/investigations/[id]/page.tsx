import { InvestigationWorkspace } from '@/features/investigation/workspace';

export const metadata = { title: 'Investigation' };

export default function InvestigationPage({ params }: { params: { id: string } }) {
  return <InvestigationWorkspace investigationId={params.id} />;
}
