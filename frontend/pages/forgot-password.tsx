import { useState, FormEvent } from "react";
import Head from "next/head";
import Link from "next/link";
import { forgotPassword } from "../lib/api";
import OwlLogo from "../components/OwlLogo";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      await forgotPassword(email.trim().toLowerCase());
    } catch {
      // Intentionally ignore errors — never reveal whether email exists
    } finally {
      setSubmitting(false);
      setSubmitted(true);
    }
  }

  return (
    <>
      <Head>
        <title>Forgot password — Hootly</title>
      </Head>
      <div className="min-h-screen bg-slate-50 flex flex-col items-center justify-center px-4">
        <div className="w-full max-w-sm">
          <div className="text-center mb-8">
            <Link href="/" className="inline-flex items-center gap-2 text-slate-700 hover:text-slate-900 transition-colors">
              <OwlLogo size={64} />
            </Link>
          </div>

          <div className="bg-white border border-slate-200 rounded-2xl p-8 shadow-sm">
            {submitted ? (
              <div className="text-center">
                <div className="text-4xl mb-4">📬</div>
                <h1 className="text-xl font-bold text-slate-900 mb-3">Check your inbox</h1>
                <p className="text-sm text-slate-500 leading-relaxed">
                  If an account exists for <strong>{email}</strong>, we&apos;ve sent a password
                  reset link. It expires in 1 hour.
                </p>
                <Link
                  href="/login"
                  className="mt-6 inline-block text-sm text-blue-600 hover:underline font-medium"
                >
                  ← Back to log in
                </Link>
              </div>
            ) : (
              <>
                <h1 className="text-xl font-bold text-slate-900 mb-2">Forgot your password?</h1>
                <p className="text-sm text-slate-500 mb-6">
                  Enter your email and we&apos;ll send you a reset link.
                </p>

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

                  <button
                    type="submit"
                    disabled={submitting}
                    className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white font-semibold py-2.5 rounded-xl text-sm transition-colors"
                  >
                    {submitting ? "Sending…" : "Send reset link"}
                  </button>
                </form>

                <p className="mt-6 text-center text-sm text-slate-500">
                  <Link href="/login" className="text-blue-600 hover:underline font-medium">
                    ← Back to log in
                  </Link>
                </p>
              </>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
