import { useState, useEffect, useRef, useCallback, FormEvent } from "react";
import { useRouter } from "next/router";
import Head from "next/head";
import Link from "next/link";
import Script from "next/script";
import { useAuth } from "../lib/auth";
import { getGithubAuthUrl, verifyEmail, resendVerification } from "../lib/api";
import OwlLogo from "../components/OwlLogo";

const TURNSTILE_SITE_KEY = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY || "";

export default function SignupPage() {
  const { register, user, loading } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  // Verification step
  const [step, setStep] = useState<"register" | "verify">("register");
  const [code, setCode] = useState("");
  const [verifyError, setVerifyError] = useState("");
  const [verifying, setVerifying] = useState(false);
  const [resent, setResent] = useState(false);
  const [resentLoading, setResentLoading] = useState(false);
  const [resendCooldown, setResendCooldown] = useState(0);
  const [turnstileToken, setTurnstileToken] = useState("");
  const turnstileRef = useRef<HTMLDivElement>(null);

  const renderTurnstile = useCallback(() => {
    if (!TURNSTILE_SITE_KEY || !turnstileRef.current) return;
    if (turnstileRef.current.childElementCount > 0) return;
    (window as any).turnstile?.render(turnstileRef.current, {
      sitekey: TURNSTILE_SITE_KEY,
      callback: (token: string) => setTurnstileToken(token),
      "expired-callback": () => setTurnstileToken(""),
    });
  }, []);

  const rawNext = typeof router.query.next === "string" ? router.query.next : "/";
  // Reject absolute URLs and protocol-relative paths to prevent open redirect
  const next = rawNext.startsWith("/") && !rawNext.startsWith("//") ? rawNext : "/";

  useEffect(() => {
    if (!loading && user?.is_verified) {
      router.replace(next);
    }
  }, [user, loading, next, router]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    if (password !== confirm) { setError("Passwords do not match"); return; }
    if (TURNSTILE_SITE_KEY && !turnstileToken) { setError("Please complete the CAPTCHA"); return; }
    setSubmitting(true);
    try {
      const u = await register(email, password, turnstileToken || undefined);
      if (!u.is_verified) {
        setStep("verify");
      } else {
        router.replace(next);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Registration failed");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleVerify(e: FormEvent) {
    e.preventDefault();
    setVerifyError("");
    setVerifying(true);
    try {
      await verifyEmail(code.trim());
      window.location.href = next;
    } catch (err: unknown) {
      setVerifyError(err instanceof Error ? err.message : "Invalid code");
      setVerifying(false);
    }
  }

  async function handleResend() {
    setResentLoading(true);
    setResent(false);
    setVerifyError("");
    try {
      await resendVerification();
      setResent(true);
      setResendCooldown(60);
    } catch (err: unknown) {
      setVerifyError(err instanceof Error ? err.message : "Failed to resend");
    }
    setResentLoading(false);
  }

  useEffect(() => {
    if (resendCooldown <= 0) return;
    const t = setTimeout(() => setResendCooldown((c) => c - 1), 1000);
    return () => clearTimeout(t);
  }, [resendCooldown]);

  return (
    <>
      <Head>
        <title>Sign up — Hootly</title>
      </Head>
      {TURNSTILE_SITE_KEY && (
        <Script
          src="https://challenges.cloudflare.com/turnstile/v0/api.js?onload=onTurnstileLoad"
          strategy="afterInteractive"
          onLoad={() => renderTurnstile()}
        />
      )}
      <div className="min-h-screen bg-slate-50 flex flex-col items-center justify-center px-4">
        <div className="w-full max-w-sm">
          <div className="text-center mb-8">
            <Link href="/" className="inline-flex items-center gap-2 text-slate-700 hover:text-slate-900 transition-colors">
              <OwlLogo size={64} />
            </Link>
          </div>

          <div className="bg-white border border-slate-200 rounded-2xl p-8 shadow-sm">

            {step === "register" ? (
              <>
                <h1 className="text-xl font-bold text-slate-900 mb-1">Create your account</h1>
                <p className="text-sm text-slate-500 mb-6">Free plan: 1 analysis/month</p>

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
                  <div className="relative flex justify-center"><span className="bg-white px-3 text-xs text-slate-400">or sign up with email</span></div>
                </div>

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
                    <label className="block text-sm font-medium text-slate-700 mb-1">Password</label>
                    <input
                      type="password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder="10+ chars, upper, lower, number, symbol"
                      required
                      minLength={10}
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
                      placeholder="••••••••••"
                      required
                      autoComplete="new-password"
                      className="w-full border border-slate-300 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    />
                  </div>

                  {TURNSTILE_SITE_KEY && (
                    <div ref={turnstileRef} className="flex justify-center" />
                  )}

                  {error && (
                    <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-4 py-2">{error}</p>
                  )}

                  <button
                    type="submit"
                    disabled={submitting}
                    className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white font-semibold py-2.5 rounded-xl text-sm transition-colors"
                  >
                    {submitting ? "Creating account…" : "Create account"}
                  </button>
                </form>

                <p className="mt-6 text-center text-sm text-slate-500">
                  Already have an account?{" "}
                  <Link href={`/login${next !== "/" ? `?next=${encodeURIComponent(next)}` : ""}`} className="text-blue-600 hover:underline font-medium">
                    Log in
                  </Link>
                </p>
              </>
            ) : (
              <>
                <div className="text-center mb-6">
                  <div className="text-4xl mb-3">📬</div>
                  <h1 className="text-xl font-bold text-slate-900 mb-2">Check your inbox</h1>
                  <p className="text-sm text-slate-500">
                    We sent an 8-digit code to{" "}
                    <span className="font-medium text-slate-700">{email}</span>
                  </p>
                </div>

                <form onSubmit={handleVerify} className="space-y-4">
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-1 text-center">
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

                  {verifyError && (
                    <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-4 py-2">{verifyError}</p>
                  )}
                  {resent && (
                    <p className="text-sm text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-lg px-4 py-2">
                      New code sent — check your inbox.
                    </p>
                  )}

                  <button
                    type="submit"
                    disabled={verifying || code.length !== 8}
                    className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white font-semibold py-2.5 rounded-xl text-sm transition-colors"
                  >
                    {verifying ? "Verifying…" : "Verify email"}
                  </button>
                </form>

                <div className="mt-5 text-center text-sm text-slate-500">
                  Didn&apos;t get it?{" "}
                  <button
                    onClick={handleResend}
                    disabled={resentLoading || resendCooldown > 0}
                    className="text-blue-600 hover:underline font-medium disabled:opacity-50 disabled:no-underline"
                  >
                    {resentLoading ? "Sending…" : resendCooldown > 0 ? `Resend in ${resendCooldown}s` : "Resend code"}
                  </button>
                </div>

                <div className="mt-2 text-center">
                  <button
                    onClick={() => { setStep("register"); setCode(""); setVerifyError(""); }}
                    className="text-xs text-slate-400 hover:text-slate-600 transition-colors"
                  >
                    ← Back
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
