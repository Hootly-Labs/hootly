import { useState } from "react";
import { ArrowRight, ArrowLeft, Target, Loader2 } from "lucide-react";
import { Button } from "./ui/button";
import { Badge } from "./ui/badge";
import { ImpactResult, getImpact } from "../lib/api";

interface Props {
  analysisId: string;
  filePath: string;
  onHighlight?: (filePath: string) => void;
}

export default function ImpactView({ analysisId, filePath, onHighlight }: Props) {
  const [impact, setImpact] = useState<ImpactResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const result = await getImpact(analysisId, filePath);
      setImpact(result);
    } catch {
      setError("Failed to load impact analysis");
    }
    setLoading(false);
  };

  if (!impact && !loading) {
    return (
      <Button variant="outline" size="sm" onClick={load} className="gap-1.5">
        <Target className="h-3.5 w-3.5" />
        Show impact
      </Button>
    );
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-zinc-500">
        <Loader2 className="h-4 w-4 animate-spin" />
        Analyzing impact...
      </div>
    );
  }

  if (error) {
    return <p className="text-sm text-red-500">{error}</p>;
  }

  if (!impact) return null;

  return (
    <div className="border border-zinc-200 dark:border-zinc-700 rounded-lg p-3 mt-2 space-y-3">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-semibold">Impact Analysis</h4>
        <Badge variant="outline">
          {impact.total_impact_radius} file{impact.total_impact_radius !== 1 ? "s" : ""} affected
        </Badge>
      </div>

      {impact.imported_by.length > 0 && (
        <div>
          <p className="text-xs font-medium text-zinc-500 mb-1 flex items-center gap-1">
            <ArrowLeft className="h-3 w-3" /> Imported by ({impact.imported_by.length})
          </p>
          <div className="flex flex-wrap gap-1">
            {impact.imported_by.map((f) => (
              <button
                key={f}
                className="text-xs bg-blue-50 dark:bg-blue-950 text-blue-700 dark:text-blue-300 px-1.5 py-0.5 rounded hover:bg-blue-100 dark:hover:bg-blue-900"
                onClick={() => onHighlight?.(f)}
              >
                {f.split("/").pop()}
              </button>
            ))}
          </div>
        </div>
      )}

      {impact.imports.length > 0 && (
        <div>
          <p className="text-xs font-medium text-zinc-500 mb-1 flex items-center gap-1">
            <ArrowRight className="h-3 w-3" /> Imports ({impact.imports.length})
          </p>
          <div className="flex flex-wrap gap-1">
            {impact.imports.map((f) => (
              <button
                key={f}
                className="text-xs bg-green-50 dark:bg-green-950 text-green-700 dark:text-green-300 px-1.5 py-0.5 rounded hover:bg-green-100 dark:hover:bg-green-900"
                onClick={() => onHighlight?.(f)}
              >
                {f.split("/").pop()}
              </button>
            ))}
          </div>
        </div>
      )}

      {impact.transitive_dependents.length > 0 && (
        <div>
          <p className="text-xs font-medium text-zinc-500 mb-1">
            Transitive dependents ({impact.transitive_dependents.length})
          </p>
          <div className="flex flex-wrap gap-1">
            {impact.transitive_dependents.map((f) => (
              <button
                key={f}
                className="text-xs bg-amber-50 dark:bg-amber-950 text-amber-700 dark:text-amber-300 px-1.5 py-0.5 rounded hover:bg-amber-100 dark:hover:bg-amber-900"
                onClick={() => onHighlight?.(f)}
              >
                {f.split("/").pop()}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
