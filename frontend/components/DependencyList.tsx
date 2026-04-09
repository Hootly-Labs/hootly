import type { Dependencies } from "../lib/api";

function DepChip({ name }: { name: string }) {
  return (
    <span className="bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-300 text-sm rounded-lg px-2.5 py-1 font-mono">
      {name}
    </span>
  );
}

export default function DependencyList({ deps }: { deps: Dependencies }) {
  const runtime = deps?.runtime ?? [];
  const dev = deps?.dev ?? [];

  if (runtime.length === 0 && dev.length === 0) {
    return <p className="text-slate-500 dark:text-slate-400 text-sm">No dependency information available.</p>;
  }

  return (
    <div className="space-y-6">
      {runtime.length > 0 && (
        <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-2xl p-6 shadow-sm">
          <h3 className="text-xs uppercase font-semibold text-slate-500 dark:text-slate-400 tracking-wider mb-3">
            Runtime Dependencies ({runtime.length})
          </h3>
          <div className="flex flex-wrap gap-2">
            {runtime.map((dep) => <DepChip key={dep} name={dep} />)}
          </div>
        </div>
      )}

      {dev.length > 0 && (
        <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-2xl p-6 shadow-sm">
          <h3 className="text-xs uppercase font-semibold text-slate-500 dark:text-slate-400 tracking-wider mb-3">
            Dev / Build Dependencies ({dev.length})
          </h3>
          <div className="flex flex-wrap gap-2">
            {dev.map((dep) => <DepChip key={dep} name={dep} />)}
          </div>
        </div>
      )}
    </div>
  );
}
