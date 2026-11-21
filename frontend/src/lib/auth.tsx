import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "./endpoints";
import { session } from "./api";
import type { Role, User } from "./schemas";

interface AuthState {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  hasRole: (...roles: Role[]) => boolean;
}

const AuthContext = createContext<AuthState | null>(null);

export const STAFF: Role[] = ["TRIAGE_ANALYST", "SUPPORT_ENGINEER", "ADMIN"];
export const ANALYST_ADMIN: Role[] = ["TRIAGE_ANALYST", "ADMIN"];

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState<boolean>(!!session.token);

  const logout = useCallback(() => {
    session.clear();
    setUser(null);
    qc.clear();
  }, [qc]);

  useEffect(() => {
    return session.onUnauthorized(() => logout());
  }, [logout]);

  useEffect(() => {
    if (!session.token) return;
    api
      .me()
      .then(setUser)
      .catch(() => session.clear())
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const token = await api.login(email, password);
    session.set(token.access_token);
    setUser(await api.me());
  }, []);

  const value = useMemo<AuthState>(
    () => ({ user, loading, login, logout, hasRole: (...roles) => !!user && roles.includes(user.role) }),
    [user, loading, login, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
