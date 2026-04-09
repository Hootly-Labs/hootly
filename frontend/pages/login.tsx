import { useState, useEffect, FormEvent } from "react";
import { useRouter } from "next/router";
import Head from "next/head";
import Link from "next/link";
import { useAuth } from "../lib/auth";
import { getGithubAuthUrl } from "../lib/api";
import OwlLogo from "../components/OwlLogo";

export default function LoginPage() {
  const { login, user, loading } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [resetSuccess, setResetSuccess] = useState(false);

  const rawNext = typeof router.query.next === "string" ? router.query.next : "/";
  // Reject absolute URLs and protocol-relative paths to prevent open redirect
  const next = rawNext.startsWith("/") && !rawNext.startsWith("//") ? rawNext : "/";

  useEffect(() => {
    if (router.query.reset === "1") {
      setResetSuccess(true);
    }
  }, [router.query.reset]);

  useEffect(() => {
    if (!loading && user) {
      router.replace(next);
    }
  }, [user, loading, next, router]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const u = await login(email, password);
      router.replace(!u.is_verified ? "/verify-email" : next);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <Head>
        <title>Log in — Hootly</title>
      </Head>
      <div className="min-h-screen bg-slate-50 flex flex-col items-center justify-center px-4">
        <div className="w-full max-w-sm">
          <div className="text-center mb-8">
            <Link href="/" className="inline-flex items-center gap-2 text-slate-700 hover:text-slate-900 transition-colors">
              <OwlLogo size={64} />
            </Link>
          </div>

          <div className="bg-white border border-slate-200 rounded-2xl p-8 shadow-sm">
            <h1 className="text-xl font-bold text-slate-900 mb-6">Log in to your account</h1>

            <button
              onClick={() => { window.location.href = getGithubAuthUrl(); }}
              className="w-full flex items-center justify-center gap-2 bg-slate-900 hover:bg-slate-700 text-white font-semibold py-2.5 rounded-xl text-sm transition-colors mb-4"
            >
              <svg className="h-4 w-4" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 0C5.374 0 0 5.373 0 12c0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23A11.509 11.509 0 0112 5.803c1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576C20.566 21.797 24 17.3 24 12c0-6.627-5.373-12-12-12z" />
              </svg>
              Continue with GitHub
            </button>

            <div className="relative mb-4">
              <div className="absolute inset-0 flex items-center"><div className="w-full border-t border-slate-200" /></div>
              <div className="relative flex justify-center"><span className="bg-white px-3 text-xs text-slate-400">or sign in with email</span></div>
            </div>

            {resetSuccess && (
              <div className="mb-4 text-sm text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-lg px-4 py-2">
                Password updated — please log in with your new password.
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">Email</label>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@example.com"
                  required
                  autoComplete="email"
                  className="w-full border border-slate-300 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">
                  <span>Password</span>
                </label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  required
                  autoComplete="current-password"
                  className="w-full border border-slate-300 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
                <div className="mt-1 text-right">
                  <Link href="/forgot-password" className="text-xs text-blue-600 hover:underline">
                    Forgot password?
                  </Link>
                </div>
              </div>

              {error && (
                <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-4 py-2">
                  {error}
                </p>
              )}

              <button
                type="submit"
                disabled={submitting}
                className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white font-semibold py-2.5 rounded-xl text-sm transition-colors"
              >
                {submitting ? "Logging in…" : "Log in"}
              </button>
            </form>

            <p className="mt-6 text-center text-sm text-slate-500">
              Don&apos;t have an account?{" "}
              <Link href={`/signup${next !== "/" ? `?next=${encodeURIComponent(next)}` : ""}`} className="text-blue-600 hover:underline font-medium">
                Sign up free
              </Link>
            </p>
          </div>
        </div>
      </div>
    </>
  );
}
