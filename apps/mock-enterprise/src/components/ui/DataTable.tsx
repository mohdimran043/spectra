import type { ReactNode } from 'react';

export interface Column<T> {
  key: string;
  header: string;
  cell: (row: T) => ReactNode;
  align?: 'left' | 'right';
}

interface DataTableProps<T> {
  /** Screen-reader caption describing the table contents. */
  caption: string;
  columns: ReadonlyArray<Column<T>>;
  rows: readonly T[];
  rowKey: (row: T) => string;
  emptyMessage: string;
}

/** Dense, semantic table: one header row, scoped headers, no decoration. */
export function DataTable<T>({ caption, columns, rows, rowKey, emptyMessage }: DataTableProps<T>) {
  if (rows.length === 0) {
    return <p className="px-3 py-3 text-ink-muted">{emptyMessage}</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="data-table">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                className={column.align === 'right' ? 'text-right' : 'text-left'}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={rowKey(row)}>
              {columns.map((column) => (
                <td
                  key={column.key}
                  className={column.align === 'right' ? 'text-right tabular-nums' : ''}
                >
                  {column.cell(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
