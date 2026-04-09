import { useState, FormEvent } from "react";
import { useRouter } from "next/router";
import Head from "next/head";
import Link from "next/link";
import { resetPassword } from "../lib/api";
import OwlLogo from "../components/OwlLogo";

export default function ResetPasswordPage() {
  const router = useRouter();
  const token = typeof router.query.token === "string" ? router.query.token : "";

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    if (password.length < 10 || !/[A-Z]/.test(password) || !/[a-z]/.test(password) || !/[0-9]/.test(password) || !/[^A-Za-z0-9]/.test(password)) {
      setError("Password must be at least 10 characters with uppercase, lowercase, number, and special character.");
      return;
    }
    setError("");
    setSubmitting(true);
    try {
      await resetPassword(token, password);
      router.replace("/login?reset=1");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Something went wrong. The link may have expired.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <Head>
        <title>Reset password — Hootly</title>
      </Head>
      <div className="min-h-screen bg-slate-50 flex flex-col items-center justify-center px-4">
        <div className="w-full max-w-sm">
          <div className="text-center mb-8">
            <Link href="/" className="inline-flex items-center gap-2 text-slate-700 hover:text-slate-900 transition-colors">
              <OwlLogo size={64} />
            </Link>
          </div>

          <div className="bg-white border border-slate-200 rounded-2xl p-8 shadow-sm">
            <h1 className="text-xl font-bold text-slate-900 mb-2">Set a new password</h1>
            <p className="text-sm text-slate-500 mb-6">Choose a strong password for your account.</p>

            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">New password</label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Min. 8 characters"
                  required
                  autoComplete="new-password"
                  className="w-full border border-slate-300 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">Confirm password</label>
                <input
                  type="password"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  placeholder="Repeat new password"
                  required
                  autoComplete="new-password"
                  className="w-full border border-slate-300 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
              </div>

              {error && (
                <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-4 py-2">
                  {error}
                </p>
              )}

              <button
                type="submit"
                disabled={submitting || !token}
                className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white font-semibold py-2.5 rounded-xl text-sm transition-colors"
              >
                {submitting ? "Saving…" : "Set new password"}
              </button>
            </form>

            {!token && (
              <p className="mt-4 text-sm text-red-600 text-center">
                Invalid reset link. Please{" "}
                <Link href="/forgot-password" className="underline">request a new one</Link>.
              </p>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
