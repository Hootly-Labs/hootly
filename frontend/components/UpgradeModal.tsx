import { useState } from "react";
import { createCheckoutSession } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useRouter } from "next/router";

interface Props {
  onDismiss: () => void;
  reason?: "limit" | "size";
}

const PRO_FEATURES = [
  "Unlimited analyses every month",
  "Repos up to 10,000 files (5× larger)",
  "2× deeper file analysis",
  "Priority processing queue",
  "Private repo support (coming soon)",
  "Email support",
];

export default function UpgradeModal({ onDismiss, reason = "limit" }: Props) {
  const { user } = useAuth();
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleUpgrade() {
    if (!user) {
      router.push("/signup");
      return;
    }
    setError("");
    setLoading(true);
    try {
      const { url } = await createCheckoutSession();
      window.location.href = url;
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Something went wrong");
      setLoading(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm"
      onClick={(e) => { if (e.target === e.currentTarget) onDismiss(); }}
    >
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-sm p-8">
        <div className="text-center mb-6">
          <div className="text-4xl mb-3">🚀</div>
          <h2 className="text-xl font-bold text-slate-900 mb-2">
            {reason === "size"
              ? "This repo is too large for the Free plan"
              : "You\u2019ve used your 1 free analysis this month"}
          </h2>
          <p className="text-sm text-slate-500 leading-relaxed">
            {reason === "size"
              ? "Pro supports repos up to 10,000 files — 5× the Free limit."
              : "Upgrade to Pro for unlimited analyses and larger repo support."}
          </p>
        </div>

        <ul className="space-y-2 mb-6">
          {PRO_FEATURES.map((f) => (
            <li key={f} className="flex items-center gap-2 text-sm text-slate-700">
              <svg className="h-4 w-4 shrink-0 text-emerald-500" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
              </svg>
              {f}
            </li>
          ))}
        </ul>

        {error && (
          <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-4 py-2 mb-4">
            {error}
          </p>
        )}

        <button
          onClick={handleUpgrade}
          disabled={loading}
          className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white font-semibold py-3 rounded-xl text-sm transition-colors mb-3"
        >
          {loading ? "Redirecting to Stripe…" : "Upgrade to Pro — $15/mo"}
        </button>

        <button
          onClick={onDismiss}
          className="w-full text-sm text-slate-500 hover:text-slate-700 py-2 transition-colors"
        >
          Maybe later
        </button>
      </div>
    </div>
  );
}
