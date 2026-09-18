import { roleSchema, type Role } from './schemas/primitives';

const ROLE_STORAGE_KEY = 'spectra.role';
const USER_STORAGE_KEY = 'spectra.user';
const THEME_STORAGE_KEY = 'spectra.theme';

export const DEFAULT_ROLE: Role = 'analyst';
export const DEFAULT_USER_ID = 'local-user';

export const ROLE_CAPABILITIES: Record<Role, readonly string[]> = {
  admin: [
    'search',
    'investigate',
    'upload',
    'manage_sources',
    'manage_agents',
    'manage_models',
    'run_sql',
    'view_autopsy',
    'export',
  ],
  analyst: ['search', 'investigate', 'upload', 'run_sql', 'view_autopsy', 'export'],
  viewer: ['search', 'view_autopsy'],
};

export const ROLE_SUMMARY: Record<Role, string> = {
  admin: 'Manages sources, agents and model runtime in addition to investigating.',
  analyst: 'Investigates, uploads evidence and runs SQL. Cannot change system configuration.',
  viewer: 'Reads search results and the search autopsy. Cannot investigate or upload.',
};

export function can(role: Role, capability: string): boolean {
  return ROLE_CAPABILITIES[role].includes(capability);
}

/** Role lives in localStorage so a reload keeps the operator in the same seat. */
export function readStoredRole(): Role {
  if (typeof window === 'undefined') return DEFAULT_ROLE;
  try {
    const parsed = roleSchema.safeParse(window.localStorage.getItem(ROLE_STORAGE_KEY));
    return parsed.success ? parsed.data : DEFAULT_ROLE;
  } catch {
    return DEFAULT_ROLE;
  }
}

export function writeStoredRole(role: Role): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(ROLE_STORAGE_KEY, role);
  } catch {
    /* Storage can be blocked; the in-memory role still applies for this session. */
  }
}

export function readStoredUserId(): string {
  if (typeof window === 'undefined') return DEFAULT_USER_ID;
  try {
    return window.localStorage.getItem(USER_STORAGE_KEY)?.trim() || DEFAULT_USER_ID;
  } catch {
    return DEFAULT_USER_ID;
  }
}

export function writeStoredUserId(userId: string): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(USER_STORAGE_KEY, userId);
  } catch {
    /* Ignored: see readStoredRole. */
  }
}

export type ThemePreference = 'system' | 'light' | 'dark';

export function readStoredTheme(): ThemePreference {
  if (typeof window === 'undefined') return 'system';
  try {
    const value = window.localStorage.getItem(THEME_STORAGE_KEY);
    return value === 'light' || value === 'dark' ? value : 'system';
  } catch {
    return 'system';
  }
}

export function writeStoredTheme(theme: ThemePreference): void {
  if (typeof window === 'undefined') return;
  try {
    if (theme === 'system') window.localStorage.removeItem(THEME_STORAGE_KEY);
    else window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    /* Ignored: see readStoredRole. */
  }
}

export { THEME_STORAGE_KEY };
export type { Role };
