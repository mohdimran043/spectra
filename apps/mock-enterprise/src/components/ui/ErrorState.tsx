interface ErrorStateProps {
  message: string;
  detail?: string;
}

/**
 * Explicit failure surface. The application never substitutes fallback data:
 * if the database cannot be read, it says so.
 */
export function ErrorState({ message, detail }: ErrorStateProps) {
  return (
    <div role="alert" className="border border-red-700 bg-red-50 p-4 text-red-900">
      <h2 className="text-sm font-bold">Data unavailable</h2>
      <p className="mt-1">{message}</p>
      {detail ? (
        <p className="mt-2 font-mono text-xxs leading-4 text-red-800">{detail}</p>
      ) : null}
      <p className="mt-2 text-xxs">
        No cached or sample records are shown in place of live data. Check the database
        connection settings and reload.
      </p>
    </div>
  );
}
