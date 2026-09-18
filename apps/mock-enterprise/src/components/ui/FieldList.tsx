import type { ReactNode } from 'react';

export interface Field {
  label: string;
  value: ReactNode;
  /** Render across the full width (long free text such as a root cause). */
  wide?: boolean;
}

/** Record detail rendered as a definition list - the LOB-app house style. */
export function FieldList({ fields }: { fields: readonly Field[] }) {
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-3 p-3 sm:grid-cols-2 lg:grid-cols-3">
      {fields.map((field) => (
        <div key={field.label} className={field.wide ? 'sm:col-span-2 lg:col-span-3' : ''}>
          <dt className="field-label">{field.label}</dt>
          <dd className="mt-0.5 break-words">{field.value}</dd>
        </div>
      ))}
    </dl>
  );
}
