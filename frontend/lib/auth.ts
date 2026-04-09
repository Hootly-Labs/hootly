import { createContext, useContext, useEffect, useState } from "react";
import { useRouter } from "next/router";
import { getMe, login as apiLogin, register as apiRegister, type AuthUser } from "./api";

interface AuthContextValue {
  user: AuthUser | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<AuthUser>;
  register: (email: string, password: string, turnstile_token?: string) => Promise<AuthUser>;
  logout: () => void;
}

export const AuthContext = createContext<AuthContextValue>({
  user: null,
  loading: true,
  login: async () => { throw new Error("AuthProvider not mounted"); },
  register: async () => { throw new Error("AuthProvider not mounted"); },
  logout: () => {},
});

export function useAuth() {
  return useContext(AuthContext);
}

export function useRequireAuth() {
  const ctx = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (ctx.loading) return;
    if (!ctx.user) {
      router.replace(`/login?next=${encodeURIComponent(router.asPath)}`);
    } else if (!ctx.user.is_verified) {
      router.replace("/verify-email");
    }
  }, [ctx.user, ctx.loading, router]);

  return ctx;
}

// Re-export AuthUser for convenience
export type { AuthUser };

// AuthProvider is created in _app.tsx using React.createElement to avoid
// importing React JSX in a .ts file. This file exports the context + hooks only.
// See frontend/lib/AuthProvider.tsx for the provider component.
