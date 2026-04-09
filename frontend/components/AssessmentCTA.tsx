import { useState } from "react";
import { createAssessment, createAssessmentCheckout, type AssessmentResult } from "../lib/api";
import { useAuth } from "../lib/auth";

interface AssessmentCTAProps {
  analysisId: string;
  assessment: AssessmentResult | null;
  onAssessmentCreated: (a: AssessmentResult) => void;
}

export default function AssessmentCTA({ analysisId, assessment, onAssessmentCreated }: AssessmentCTAProps) {
  const { user } = useAuth();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  if (assessment?.status === "completed" && assessment.result) {
    return <AssessmentReport result={assessment.result} tier={assessment.tier} />;
  }

  if (assessment?.status === "processing" || assessment?.status === "paid") {
    return (
      <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-700 rounded-2xl p-6 text-center">
        <div className="w-6 h-6 border-2 border-blue-600 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
        <p className="text-sm text-blue-700 dark:text-blue-300">Generating assessment report...</p>
        <p className="text-xs text-blue-500 dark:text-blue-400 mt-1">This takes 30-60 seconds.</p>
      </div>
    );
  }

  const isPro = user?.plan === "pro" || user?.is_admin;

  const handleCreate = async (tier: string) => {
    setLoading(true);
    setError("");
    try {
      if (isPro) {
        // Pro users get it included — directly create
        const result = await createAssessment(analysisId, tier);
        onAssessmentCreated(result);
      } else {
        // Free users — redirect to Stripe one-time checkout
        const { url } = await createAssessmentCheckout(analysisId, tier);
        window.location.href = url;
      }
    } catch (e: any) {
      setError(e.message);
    }
    setLoading(false);
  };

  return (
    <div className="bg-gradient-to-br from-slate-50 to-blue-50 dark:from-slate-800 dark:to-blue-900/20 border border-slate-200 dark:border-slate-700 rounded-2xl p-6">
      <h3 className="font-semibold text-slate-900 dark:text-slate-100 mb-1">Assessment Report</h3>
      <p className="text-sm text-slate-600 dark:text-slate-400 mb-4">
        Get a professional assessment with health narrative, tech debt analysis, and prioritized recommendations.
      </p>

      {error && <p className="text-sm text-red-500 mb-3">{error}</p>}

      <div className="grid sm:grid-cols-2 gap-3">
        <button
          onClick={() => handleCreate("basic")}
          disabled={loading}
          className="border border-slate-200 dark:border-slate-600 rounded-xl p-4 text-left hover:border-blue-400 dark:hover:border-blue-500 transition-colors disabled:opacity-50"
        >
          <div className="text-sm font-semibold text-slate-800 dark:text-slate-200">Basic Assessment</div>
          <div className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            Health narrative + tech debt analysis
          </div>
          <div className="text-lg font-bold text-blue-600 dark:text-blue-400 mt-2">
            {isPro ? "Included in Pro" : "$99"}
          </div>
        </button>
        <button
          onClick={() => handleCreate("full")}
          disabled={loading}
          className="border border-blue-200 dark:border-blue-600 bg-blue-50 dark:bg-blue-900/20 rounded-xl p-4 text-left hover:border-blue-400 dark:hover:border-blue-500 transition-colors disabled:opacity-50"
        >
          <div className="text-sm font-semibold text-slate-800 dark:text-slate-200">Full Assessment</div>
          <div className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            + Security analysis + industry comparison
          </div>
          <div className="text-lg font-bold text-blue-600 dark:text-blue-400 mt-2">
            {isPro ? "Included in Pro" : "$499"}
          </div>
        </button>
      </div>

      {!isPro && (
        <p className="text-xs text-slate-400 dark:text-slate-500 mt-3 text-center">
          Assessment reports are included with Pro, or available as a one-time purchase.
        </p>
      )}
    </div>
  );
}

function AssessmentReport({ result, tier }: { result: NonNullable<AssessmentResult["result"]>; tier: string }) {
  return (
    <div className="space-y-6">
      {/* Executive Summary */}
      <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-2xl p-6">
        <h3 className="font-semibold text-slate-900 dark:text-slate-100 mb-3">Executive Summary</h3>
        <p className="text-sm text-slate-700 dark:text-slate-300 leading-relaxed">
          {result.executive_summary || result.health_assessment?.executive_summary}
        </p>
      </div>

      {/* Strengths & Risks */}
      <div className="grid sm:grid-cols-2 gap-4">
        <div className="bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-700 rounded-xl p-4">
          <h4 className="text-sm font-semibold text-green-800 dark:text-green-300 mb-2">Strengths</h4>
          <ul className="space-y-1.5">
            {result.health_assessment?.strengths?.map((s, i) => (
              <li key={i} className="text-xs text-green-700 dark:text-green-400 flex gap-1.5">
                <span className="shrink-0 mt-0.5">+</span>
                <span>{s}</span>
              </li>
            ))}
          </ul>
        </div>
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-700 rounded-xl p-4">
          <h4 className="text-sm font-semibold text-red-800 dark:text-red-300 mb-2">Risks</h4>
          <ul className="space-y-1.5">
            {result.health_assessment?.risks?.map((r, i) => (
              <li key={i} className="text-xs text-red-700 dark:text-red-400 flex gap-1.5">
                <span className="shrink-0 mt-0.5">!</span>
                <span>{r}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      {/* Tech Debt */}
      {result.tech_debt && (
        <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-2xl p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-semibold text-slate-900 dark:text-slate-100">Tech Debt Analysis</h3>
            <span className="text-sm font-bold text-slate-600 dark:text-slate-400">
              {result.tech_debt.debt_score}/100
            </span>
          </div>
          <p className="text-sm text-slate-600 dark:text-slate-400 mb-4">{result.tech_debt.summary}</p>
          <div className="space-y-3">
            {result.tech_debt.debt_items?.map((item, i) => (
              <div key={i} className="border border-slate-100 dark:border-slate-700 rounded-lg p-3">
                <div className="flex items-center gap-2 mb-1">
                  <span className={`text-xs font-medium px-1.5 py-0.5 rounded ${
                    item.severity === "high" ? "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300" :
                    item.severity === "medium" ? "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-300" :
                    "bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-400"
                  }`}>
                    {item.severity}
                  </span>
                  <span className="text-xs text-slate-500 dark:text-slate-400">{item.category}</span>
                </div>
                <p className="text-sm text-slate-700 dark:text-slate-300">{item.description}</p>
                <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                  {item.recommendation} (effort: {item.effort})
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Security Analysis (full tier only) */}
      {result.security_analysis && (
        <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-2xl p-6">
          <h3 className="font-semibold text-slate-900 dark:text-slate-100 mb-3">Security Analysis</h3>
          <p className="text-sm text-slate-600 dark:text-slate-400 mb-4">
            Risk level: <span className="font-semibold">{result.security_analysis.risk_level}</span>
          </p>
          <p className="text-sm text-slate-600 dark:text-slate-400 mb-4">{result.security_analysis.summary}</p>
          <div className="space-y-2">
            {result.security_analysis.attack_surface?.map((area, i) => (
              <div key={i} className="border border-slate-100 dark:border-slate-700 rounded-lg p-3">
                <div className="flex items-center gap-2 mb-1">
                  <span className={`text-xs font-medium px-1.5 py-0.5 rounded ${
                    area.risk === "high" ? "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300" :
                    area.risk === "medium" ? "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-300" :
                    "bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-400"
                  }`}>
                    {area.risk}
                  </span>
                  <span className="text-xs font-medium text-slate-700 dark:text-slate-300">{area.area}</span>
                </div>
                <p className="text-xs text-slate-600 dark:text-slate-400">{area.description}</p>
                <p className="text-xs text-blue-600 dark:text-blue-400 mt-1">{area.mitigation}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Recommendations */}
      {result.recommendations?.length > 0 && (
        <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-2xl p-6">
          <h3 className="font-semibold text-slate-900 dark:text-slate-100 mb-4">Prioritized Recommendations</h3>
          <div className="space-y-2">
            {result.recommendations.map((rec, i) => (
              <div key={i} className="flex gap-2 text-sm">
                <span className={`shrink-0 text-xs font-medium px-1.5 py-0.5 rounded mt-0.5 ${
                  rec.priority === "high" ? "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300" :
                  "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-300"
                }`}>
                  {rec.priority}
                </span>
                <span className="text-slate-700 dark:text-slate-300">{rec.recommendation}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
