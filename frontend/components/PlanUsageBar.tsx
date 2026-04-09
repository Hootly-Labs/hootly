import { useEffect, useState } from "react";
import { getBillingUsage, createCheckoutSession } from "../lib/api";
import { useRouter } from "next/router";

export default function PlanUsageBar() {
  const router = useRouter();
  const [usage, setUsage] = useState<{ analyses_this_month: number; limit: number | null } | null>(null);
  const [upgrading, setUpgrading] = useState(false);

  useEffect(() => {
    getBillingUsage()
      .then(setUsage)
      .catch(() => {});
  }, []);

  if (!usage || usage.limit === null) return null;

  const { analyses_this_month: used, limit } = usage;
  const pct = Math.min((used / limit) * 100, 100);

  async function handleUpgrade() {
    setUpgrading(true);
    try {
      const { url } = await createCheckoutSession();
      window.location.href = url;
    } catch {
      router.push("/signup");
    }
  }

  return (
    <div className="mb-3 bg-slate-50 border border-slate-200 rounded-xl px-4 py-3 flex flex-col gap-2">
      <div className="flex items-center justify-between text-sm">
        <span className="text-slate-600">
          <span className="font-semibold text-slate-900">{used}</span> of{" "}
          <span className="font-semibold text-slate-900">{limit}</span> analyses used this month
        </span>
        <button
          onClick={handleUpgrade}
          disabled={upgrading}
          className="text-blue-600 hover:underline text-xs font-medium shrink-0 ml-3 disabled:opacity-50"
        >
          {upgrading ? "Loading…" : "Upgrade for unlimited →"}
        </button>
      </div>

      {/* Progress bar */}
      <div className="flex gap-1">
        {Array.from({ length: limit }).map((_, i) => (
          <div
            key={i}
            className={`h-1.5 flex-1 rounded-full transition-colors ${
              i < used ? "bg-blue-500" : "bg-slate-200"
            }`}
          />
        ))}
      </div>
    </div>
  );
}
