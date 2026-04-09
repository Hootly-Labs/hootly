import { useEffect, useState, ReactNode } from "react";
import { useRouter } from "next/router";
import { AuthContext } from "./auth";
import { getMe, login as apiLogin, register as apiRegister, type AuthUser } from "./api";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    const token = localStorage.getItem("hl_token");
    if (!token) {
      setLoading(false);
      return;
    }
    getMe()
      .then(setUser)
      .catch(() => {
        localStorage.removeItem("hl_token");
      })
      .finally(() => setLoading(false));
  }, []);

  async function login(email: string, password: string): Promise<AuthUser> {
    const { token, user: u } = await apiLogin(email, password);
    localStorage.setItem("hl_token", token);
    setUser(u);
    return u;
  }

  async function register(email: string, password: string, turnstile_token?: string): Promise<AuthUser> {
    const { token, user: u } = await apiRegister(email, password, turnstile_token);
    localStorage.setItem("hl_token", token);
    setUser(u);
    return u;
  }

  function logout() {
    localStorage.removeItem("hl_token");
    setUser(null);
    // Clear refresh cookie on the server
    fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/auth/logout`, {
      method: "POST",
      credentials: "include",
    }).catch(() => {});
    router.push("/");
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}
