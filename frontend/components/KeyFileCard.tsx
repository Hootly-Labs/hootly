import { useState } from "react";
import type { KeyFile } from "../lib/api";

function ScoreBadge({ score }: { score: number }) {
  const color =
    score >= 9 ? "bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300 border-red-200 dark:border-red-700" :
    score >= 7 ? "bg-orange-100 dark:bg-orange-900/40 text-orange-700 dark:text-orange-300 border-orange-200 dark:border-orange-700" :
    score >= 5 ? "bg-yellow-100 dark:bg-yellow-900/40 text-yellow-700 dark:text-yellow-300 border-yellow-200 dark:border-yellow-700" :
                 "bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-400 border-slate-200 dark:border-slate-600";
  const label = score >= 9 ? "Critical" : score >= 7 ? "High" : score >= 5 ? "Medium" : "Low";
  return (
    <span className={`text-xs font-semibold border rounded-full px-2 py-0.5 ${color}`}>
      {label} {score}/10
    </span>
  );
}

export default function KeyFileCard({ file, index }: { file: KeyFile; index: number }) {
  const [open, setOpen] = useState(index < 5);

  return (
    <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-2xl shadow-sm overflow-hidden">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-3 px-5 py-4 text-left hover:bg-slate-50 dark:hover:bg-slate-700/50 transition-colors"
      >
        {/* Rank */}
        <span className="text-sm font-bold text-slate-400 dark:text-slate-500 w-6 shrink-0 text-right">
          #{index + 1}
        </span>

        {/* File path */}
        <span className="font-mono text-sm text-blue-700 dark:text-blue-300 font-medium truncate flex-1">
          {file.path}
        </span>

        <ScoreBadge score={file.score} />

        {/* Toggle */}
        <svg
          className={`h-4 w-4 text-slate-400 dark:text-slate-500 shrink-0 transition-transform ${open ? "rotate-180" : ""}`}
          viewBox="0 0 20 20" fill="currentColor"
        >
          <path fillRule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clipRule="evenodd" />
        </svg>
      </button>

      {open && (
        <div className="px-5 pb-5 border-t border-slate-100 dark:border-slate-700">
          {/* Why important */}
          <div className="mt-4">
            <p className="text-xs uppercase font-semibold text-slate-400 dark:text-slate-500 tracking-wider mb-1.5">Why it matters</p>
            <p className="text-sm text-slate-600 dark:text-slate-400 italic">{file.reason}</p>
          </div>

          {/* Explanation */}
          {file.explanation && (
            <div className="mt-4">
              <p className="text-xs uppercase font-semibold text-slate-400 dark:text-slate-500 tracking-wider mb-1.5">Explanation</p>
              <p className="text-sm text-slate-700 dark:text-slate-300 leading-relaxed">{file.explanation}</p>
            </div>
          )}

          {/* Key exports */}
          {file.key_exports && file.key_exports.length > 0 && (
            <div className="mt-4">
              <p className="text-xs uppercase font-semibold text-slate-400 dark:text-slate-500 tracking-wider mb-1.5">Key exports</p>
              <div className="flex flex-wrap gap-1.5">
                {file.key_exports.map((exp) => (
                  <code
                    key={exp}
                    className="text-xs font-mono bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-300 rounded px-2 py-0.5"
                  >
                    {exp}
                  </code>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
