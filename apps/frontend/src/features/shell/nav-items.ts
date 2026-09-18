import type { ComponentType } from 'react';

import { IconDatabase, IconGpu, IconSearch, type IconProps } from '@/components/icons';

export interface NavDivision {
  readonly href: string;
  readonly label: string;
  readonly icon: ComponentType<IconProps>;
  /** Capability required to reach this division; undefined means everyone. */
  readonly capability?: string;
  readonly group: 'record' | 'system';
  /** Keyboard address, shown in the command palette. */
  readonly address: string;
}

/** Search is the product; the other two say what it is searching and with what. */
export const NAV_DIVISIONS: readonly NavDivision[] = [
  { href: '/', label: 'Search', icon: IconSearch, group: 'record', address: '100' },
  { href: '/sources', label: 'Sources', icon: IconDatabase, group: 'system', address: '200' },
  { href: '/models', label: 'Models', icon: IconGpu, group: 'system', address: '300' },
];

export const NAV_GROUP_LABEL: Record<NavDivision['group'], string> = {
  record: 'Search',
  system: 'The index',
};
