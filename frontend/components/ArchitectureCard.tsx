import type { Architecture, Pattern } from "../lib/api";

interface Props {
  arch: Architecture;
  quickStart: string;
  keyConcepts: string[];
  patterns?: Pattern[];
  testFileCount?: number;
}

export default function ArchitectureCard({ arch, quickStart, keyConcepts, patterns, testFileCount }: Props) {
  return (
    <div className="space-y-6">
      {/* Description */}
      <div className="bg-white dark:bg-slate-800 rounded-2xl border border-slate-200 dark:border-slate-700 p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100 mb-1">{arch.project_name}</h2>
        <span className="inline-block text-xs font-medium bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 border border-blue-200 dark:border-blue-700 rounded-full px-2.5 py-0.5 mb-3">
          {arch.architecture_type}
        </span>
        <p className="text-slate-700 dark:text-slate-300 leading-relaxed">{arch.description}</p>
      </div>

      {/* Tech Stack + Meta */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="bg-white dark:bg-slate-800 rounded-2xl border border-slate-200 dark:border-slate-700 p-5 shadow-sm">
          <h3 className="text-xs uppercase font-semibold text-slate-500 dark:text-slate-400 tracking-wider mb-3">Tech Stack</h3>
          <div className="flex flex-wrap gap-2">
            {arch.tech_stack.map((tech) => (
              <span key={tech} className="bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-300 text-sm rounded-lg px-2.5 py-1 font-medium">
                {tech}
              </span>
            ))}
          </div>
        </div>

        <div className="bg-white dark:bg-slate-800 rounded-2xl border border-slate-200 dark:border-slate-700 p-5 shadow-sm">
          <h3 className="text-xs uppercase font-semibold text-slate-500 dark:text-slate-400 tracking-wider mb-3">Details</h3>
          <dl className="space-y-2 text-sm">
            {arch.runtime && (
              <div className="flex gap-2">
                <dt className="text-slate-500 dark:text-slate-400 w-20 shrink-0">Runtime</dt>
                <dd className="text-slate-800 dark:text-slate-200 font-mono">{arch.runtime}</dd>
              </div>
            )}
            <div className="flex gap-2">
              <dt className="text-slate-500 dark:text-slate-400 w-20 shrink-0">Languages</dt>
              <dd className="text-slate-800 dark:text-slate-200">{arch.languages.join(", ")}</dd>
            </div>
            <div className="flex gap-2">
              <dt className="text-slate-500 dark:text-slate-400 w-20 shrink-0">License</dt>
              <dd className="text-slate-800 dark:text-slate-200">{arch.license || "Unknown"}</dd>
            </div>
          </dl>
        </div>
      </div>

      {/* Architecture Summary */}
      <div className="bg-white dark:bg-slate-800 rounded-2xl border border-slate-200 dark:border-slate-700 p-6 shadow-sm">
        <h3 className="text-xs uppercase font-semibold text-slate-500 dark:text-slate-400 tracking-wider mb-3">Architecture</h3>
        <p className="text-slate-700 dark:text-slate-300 leading-relaxed">{arch.architecture_summary}</p>

        {arch.key_directories.length > 0 && (
          <div className="mt-4 space-y-1.5">
            {arch.key_directories.map((dir) => (
              <div key={dir.path} className="flex items-baseline gap-3 text-sm">
                <code className="font-mono text-blue-700 dark:text-blue-300 bg-blue-50 dark:bg-blue-900/30 px-1.5 py-0.5 rounded shrink-0">
                  {dir.path}
                </code>
                <span className="text-slate-600 dark:text-slate-400">{dir.purpose}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Entry Points */}
      {arch.entry_points.length > 0 && (
        <div className="bg-white dark:bg-slate-800 rounded-2xl border border-slate-200 dark:border-slate-700 p-6 shadow-sm">
          <h3 className="text-xs uppercase font-semibold text-slate-500 dark:text-slate-400 tracking-wider mb-3">Entry Points</h3>
          <div className="flex flex-wrap gap-2">
            {arch.entry_points.map((ep) => (
              <span key={ep} className="font-mono text-sm bg-amber-50 dark:bg-amber-900/30 text-amber-800 dark:text-amber-300 border border-amber-200 dark:border-amber-700 rounded-lg px-2.5 py-1">
                {ep}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Key Concepts */}
      {keyConcepts.length > 0 && (
        <div className="bg-white dark:bg-slate-800 rounded-2xl border border-slate-200 dark:border-slate-700 p-6 shadow-sm">
          <h3 className="text-xs uppercase font-semibold text-slate-500 dark:text-slate-400 tracking-wider mb-3">Key Concepts</h3>
          <ul className="space-y-1.5">
            {keyConcepts.map((c, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-slate-700 dark:text-slate-300">
                <span className="text-blue-500 mt-0.5 shrink-0">▸</span>
                {c}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* How does X work — architectural patterns */}
      {patterns && patterns.length > 0 && (
        <div className="bg-white dark:bg-slate-800 rounded-2xl border border-slate-200 dark:border-slate-700 p-6 shadow-sm">
          <h3 className="text-xs uppercase font-semibold text-slate-500 dark:text-slate-400 tracking-wider mb-4">How Things Work</h3>
          <div className="space-y-4">
            {patterns.map((p, i) => (
              <div key={i}>
                <p className="text-sm font-semibold text-slate-800 dark:text-slate-200 mb-1">{p.name}</p>
                <p className="text-sm text-slate-600 dark:text-slate-400 leading-relaxed">{p.explanation}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Test coverage callout */}
      {typeof testFileCount === "number" && testFileCount > 0 && (
        <div className="flex items-center gap-3 bg-violet-50 dark:bg-violet-900/30 border border-violet-200 dark:border-violet-700 rounded-2xl p-4 text-sm">
          <span className="text-lg">🧪</span>
          <span className="text-violet-800 dark:text-violet-300">
            <span className="font-semibold">{testFileCount}</span> test/spec file{testFileCount !== 1 ? "s" : ""} detected — see the Onboarding Guide for details on test coverage.
          </span>
        </div>
      )}

      {/* Quick Start */}
      {quickStart && (
        <div className="bg-emerald-50 dark:bg-emerald-900/30 border border-emerald-200 dark:border-emerald-700 rounded-2xl p-6">
          <h3 className="text-xs uppercase font-semibold text-emerald-700 dark:text-emerald-300 tracking-wider mb-3">Quick Start</h3>
          <p className="text-emerald-900 dark:text-emerald-200 leading-relaxed text-sm">{quickStart}</p>
        </div>
      )}
    </div>
  );
}
