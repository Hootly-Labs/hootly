import type { ReadingStep } from "../lib/api";

export default function ReadingOrder({ steps }: { steps: ReadingStep[] }) {
  if (!steps || steps.length === 0) return null;

  return (
    <div className="space-y-3">
      {steps.map((step, i) => (
        <div key={i} className="flex gap-4 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-2xl p-4 shadow-sm items-start">
          {/* Step number */}
          <div className="shrink-0 w-8 h-8 rounded-full bg-blue-600 text-white text-sm font-bold flex items-center justify-center">
            {step.step ?? i + 1}
          </div>

          <div className="min-w-0 flex-1">
            <code className="text-sm font-mono text-blue-700 dark:text-blue-300 font-medium break-all">
              {step.path}
            </code>
            {step.reason && (
              <p className="text-sm text-slate-600 dark:text-slate-400 mt-0.5 leading-relaxed">{step.reason}</p>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
