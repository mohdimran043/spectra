import type { ComponentType } from 'react';

import {
  IconAgent,
  IconDemo,
  IconDatabase,
  IconGpu,
  IconGraph,
  IconHome,
  IconSearch,
  IconSettings,
  type IconProps,
} from '@/components/icons';

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

/**
 * The binder's tab rail. Divisions are ordered the way an investigation runs:
 * ask, retrieve, connect — then the machine that did it.
 */
export const NAV_DIVISIONS: readonly NavDivision[] = [
  { href: '/', label: 'Record', icon: IconHome, group: 'record', address: '100' },
  { href: '/search', label: 'Search', icon: IconSearch, group: 'record', address: '200' },
  { href: '/graph', label: 'Evidence Graph', icon: IconGraph, group: 'record', address: '300' },
  { href: '/demo', label: 'Guided Demo', icon: IconDemo, group: 'record', address: '400' },
  {
    href: '/sources',
    label: 'Sources',
    icon: IconDatabase,
    group: 'system',
    address: '500',
  },
  {
    href: '/agents',
    label: 'Agents',
    icon: IconAgent,
    group: 'system',
    address: '600',
  },
  {
    href: '/models',
    label: 'Models',
    icon: IconGpu,
    group: 'system',
    address: '700',
  },
  { href: '/settings', label: 'Settings', icon: IconSettings, group: 'system', address: '800' },
];

export const NAV_GROUP_LABEL: Record<NavDivision['group'], string> = {
  record: 'The record',
  system: 'The machine',
};
