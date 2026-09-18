'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

import {
  DEFAULT_ROLE,
  DEFAULT_USER_ID,
  can,
  readStoredRole,
  readStoredTheme,
  readStoredUserId,
  writeStoredRole,
  writeStoredTheme,
  writeStoredUserId,
  type Role,
  type ThemePreference,
} from '@/lib/role';

interface SessionValue {
  readonly role: Role;
  readonly userId: string;
  readonly theme: ThemePreference;
  readonly hydrated: boolean;
  readonly setRole: (role: Role) => void;
  readonly setUserId: (userId: string) => void;
  readonly setTheme: (theme: ThemePreference) => void;
  readonly can: (capability: string) => boolean;
}

const SessionContext = createContext<SessionValue | null>(null);

/**
 * The operator's seat. Role is not cosmetic — it is sent as `X-Spectra-Role` on
 * every request, so changing it changes what the API is willing to return.
 * Queries are keyed off it in `providers.tsx` and refetched on change.
 */
export function SessionProvider({
  children,
  onRoleChange,
}: {
  children: ReactNode;
  onRoleChange?: () => void;
}) {
  const [role, setRoleState] = useState<Role>(DEFAULT_ROLE);
  const [userId, setUserIdState] = useState<string>(DEFAULT_USER_ID);
  const [theme, setThemeState] = useState<ThemePreference>('light');
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    setRoleState(readStoredRole());
    setUserIdState(readStoredUserId());
    setThemeState(readStoredTheme());
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    const root = document.documentElement;
    if (theme === 'system') root.removeAttribute('data-theme');
    else root.setAttribute('data-theme', theme);
  }, [theme, hydrated]);

  const setRole = useCallback(
    (next: Role) => {
      setRoleState(next);
      writeStoredRole(next);
      onRoleChange?.();
    },
    [onRoleChange],
  );

  const setUserId = useCallback(
    (next: string) => {
      const trimmed = next.trim() || DEFAULT_USER_ID;
      setUserIdState(trimmed);
      writeStoredUserId(trimmed);
      onRoleChange?.();
    },
    [onRoleChange],
  );

  const setTheme = useCallback((next: ThemePreference) => {
    setThemeState(next);
    writeStoredTheme(next);
  }, []);

  const value = useMemo<SessionValue>(
    () => ({
      role,
      userId,
      theme,
      hydrated,
      setRole,
      setUserId,
      setTheme,
      can: (capability: string) => can(role, capability),
    }),
    [role, userId, theme, hydrated, setRole, setUserId, setTheme],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error('useSession must be used inside SessionProvider');
  return value;
}
