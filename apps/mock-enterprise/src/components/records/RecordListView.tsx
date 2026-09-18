import type { ReactNode } from 'react';

import { ErrorState } from '@/components/ui/ErrorState';
import { PageHeader } from '@/components/ui/PageHeader';
import { Pagination } from '@/components/ui/Pagination';
import { Panel } from '@/components/ui/Panel';
import { SearchBox } from '@/components/ui/SearchBox';
import { formatNumber } from '@/lib/format';
import type { Result } from '@/lib/result';
import type { Page } from '@/lib/types';

interface RecordListViewProps<T> {
  title: string;
  description: string;
  basePath: string;
  result: Result<Page<T>>;
  renderTable: (rows: T[]) => ReactNode;
}

/** Shared shell for the four list pages: header, search, table, pagination. */
export function RecordListView<T>({
  title,
  description,
  basePath,
  result,
  renderTable,
}: RecordListViewProps<T>) {
  return (
    <>
      <PageHeader
        title={title}
        subtitle={description}
        crumbs={[{ label: 'Overview', href: '/' }, { label: title }]}
      />
      <div className="mb-4 max-w-xl">
        <SearchBox label="Search all records" />
      </div>
      {result.ok ? (
        <Panel title={title} note={`${formatNumber(result.value.total)} records`}>
          {renderTable(result.value.rows)}
          <Pagination
            basePath={basePath}
            page={result.value.page}
            pageCount={result.value.pageCount}
            total={result.value.total}
          />
        </Panel>
      ) : (
        <ErrorState message={result.message} detail={result.detail} />
      )}
    </>
  );
}
