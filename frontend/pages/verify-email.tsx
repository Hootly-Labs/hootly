import { useState, useEffect, FormEvent } from "react";
import Head from "next/head";
import Link from "next/link";
import { useRouter } from "next/router";
import { useAuth } from "../lib/auth";
import { verifyEmail, resendVerification } from "../lib/api";
import OwlLogo from "../components/OwlLogo";

export default function VerifyEmailPage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [resent, setResent] = useState(false);
  const [resentLoading, setResentLoading] = useState(false);
  const [resendCooldown, setResendCooldown] = useState(0);

  useEffect(() => {
    if (!loading && !user) {
      router.replace("/login");
    }
    if (!loading && user?.is_verified) {
      router.replace("/");
    }
  }, [user, loading, router]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      await verifyEmail(code.trim());
      // Reload so AuthProvider re-fetches the updated user (is_verified=true)
      window.location.href = "/";
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Invalid code");
      setSubmitting(false);
    }
  }

  async function handleResend() {
    setResentLoading(true);
    setResent(false);
    setError("");
    try {
      await resendVerification();
      setResent(true);
      setResendCooldown(60);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to resend");
    }
    setResentLoading(false);
  }

  useEffect(() => {
    if (resendCooldown <= 0) return;
    const t = setTimeout(() => setResendCooldown((c) => c - 1), 1000);
    return () => clearTimeout(t);
  }, [resendCooldown]);

  if (loading || !user) return null;

  return (
    <>
      <Head><title>Verify your email — Hootly</title></Head>
      <div className="min-h-screen bg-slate-50 flex flex-col items-center justify-center px-4">
        <div className="w-full max-w-sm">
          <div className="text-center mb-8">
            <Link href="/" className="inline-flex items-center gap-2 text-slate-700 hover:text-slate-900 transition-colors">
              <OwlLogo size={64} />
            </Link>
          </div>

          <div className="bg-white border border-slate-200 rounded-2xl p-8 shadow-sm">
            <div className="text-center mb-6">
              <div className="text-4xl mb-3">📬</div>
              <h1 className="text-xl font-bold text-slate-900 mb-2">Check your inbox</h1>
              <p className="text-sm text-slate-500">
                We sent an 8-digit code to{" "}
                <span className="font-medium text-slate-700">{user.email}</span>
              </p>
            </div>

            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">
                  Verification code
                </label>
                <input
                  type="text"
                  inputMode="numeric"
                  pattern="[0-9]{8}"
                  maxLength={8}
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                  placeholder="00000000"
                  required
                  autoFocus
                  className="w-full border border-slate-300 rounded-xl px-4 py-3 text-center text-2xl font-mono tracking-widest focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
              </div>

              {error && (
                <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-4 py-2">
                  {error}
                </p>
              )}
              {resent && (
                <p className="text-sm text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-lg px-4 py-2">
                  New code sent — check your inbox.
                </p>
              )}

              <button
                type="submit"
                disabled={submitting || code.length !== 8}
                className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white font-semibold py-2.5 rounded-xl text-sm transition-colors"
              >
                {submitting ? "Verifying…" : "Verify email"}
              </button>
            </form>

            <div className="mt-6 text-center text-sm text-slate-500">
              Didn&apos;t get it?{" "}
              <button
                onClick={handleResend}
                disabled={resentLoading || resendCooldown > 0}
                className="text-blue-600 hover:underline font-medium disabled:opacity-50 disabled:no-underline"
              >
                {resentLoading ? "Sending…" : resendCooldown > 0 ? `Resend in ${resendCooldown}s` : "Resend code"}
              </button>
            </div>

            <div className="mt-3 text-center text-xs text-slate-400">
              Wrong account?{" "}
              <button
                onClick={() => { localStorage.removeItem("hl_token"); window.location.href = "/login"; }}
                className="text-slate-500 hover:underline"
              >
                Log out
              </button>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
