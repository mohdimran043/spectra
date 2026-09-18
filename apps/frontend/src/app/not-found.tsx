import Link from 'next/link';

import { linkButtonClasses } from '@/components/button-styles';
import { Leaf, LeafHead } from '@/components/leaf';
import { Division } from '@/components/page';
import { EmptyState } from '@/components/states';

export default function NotFound() {
  return (
    <Division width="reading">
      <Leaf>
        <LeafHead title="No such division" />
        <EmptyState
          title="This address is not part of the record"
          body="The page you asked for does not exist in this console. Investigation ids look like inv_ followed by sixteen hex characters; press Ctrl K anywhere to jump to one."
          action={
            <Link href="/" className={linkButtonClasses('secondary', 'md')}>
              Back to the record
            </Link>
          }
        />
      </Leaf>
    </Division>
  );
}
