import Link from 'next/link';

export default function NotFound() {
  return (
    <div className="border border-line bg-surface p-6">
      <h1 className="text-lg font-bold">Record not found</h1>
      <p className="mt-2 text-ink-muted">
        No record with that identifier exists in the enterprise database. It may have been
        removed, or the identifier may belong to a different environment.
      </p>
      <p className="mt-4">
        <Link href="/">Return to the operations overview</Link>
      </p>
    </div>
  );
}
