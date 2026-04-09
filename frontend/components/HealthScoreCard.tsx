import { useState } from "react";
import type { HealthScore } from "../lib/api";

interface HealthScoreCardProps {
  healthScore: HealthScore;
  isPro?: boolean;
}

const GRADE_COLORS: Record<string, string> = {
  A: "text-green-600",
  B: "text-lime-600",
  C: "text-yellow-600",
  D: "text-orange-500",
  F: "text-red-500",
};

const GRADE_BG: Record<string, string> = {
  A: "bg-green-50 border-green-200 dark:bg-green-900/20 dark:border-green-700",
  B: "bg-lime-50 border-lime-200 dark:bg-lime-900/20 dark:border-lime-700",
  C: "bg-yellow-50 border-yellow-200 dark:bg-yellow-900/20 dark:border-yellow-700",
  D: "bg-orange-50 border-orange-200 dark:bg-orange-900/20 dark:border-orange-700",
  F: "bg-red-50 border-red-200 dark:bg-red-900/20 dark:border-red-700",
};

const DIM_ORDER = [
  "modularity",
  "documentation",
  "test_coverage",
  "dependency_health",
  "code_organization",
  "complexity",
];

function RadarChart({ dimensions }: { dimensions: Record<string, { score: number; label: string }> }) {
  const size = 200;
  const cx = size / 2;
  const cy = size / 2;
  const radius = 80;
  const dims = DIM_ORDER.filter((k) => k in dimensions);
  const n = dims.length;
  if (n < 3) return null;

  const angleStep = (2 * Math.PI) / n;

  function point(index: number, value: number): [number, number] {
    const angle = -Math.PI / 2 + index * angleStep;
    const r = (value / 100) * radius;
    return [cx + r * Math.cos(angle), cy + r * Math.sin(angle)];
  }

  // Grid rings
  const rings = [25, 50, 75, 100];
  const gridPaths = rings.map((val) => {
    const pts = dims.map((_, i) => point(i, val));
    return pts.map((p) => `${p[0]},${p[1]}`).join(" ");
  });

  // Data polygon
  const dataPts = dims.map((k, i) => point(i, dimensions[k].score));
  const dataPath = dataPts.map((p) => `${p[0]},${p[1]}`).join(" ");

  // Labels
  const labels = dims.map((k, i) => {
    const angle = -Math.PI / 2 + i * angleStep;
    const lr = radius + 24;
    return {
      x: cx + lr * Math.cos(angle),
      y: cy + lr * Math.sin(angle),
      label: dimensions[k].label,
      score: dimensions[k].score,
    };
  });

  return (
    <svg viewBox={`0 0 ${size} ${size}`} className="w-full max-w-[260px] mx-auto">
      {/* Grid */}
      {gridPaths.map((pts, i) => (
        <polygon
          key={i}
          points={pts}
          fill="none"
          stroke="currentColor"
          className="text-slate-200 dark:text-slate-700"
          strokeWidth="0.5"
        />
      ))}
      {/* Axes */}
      {dims.map((_, i) => {
        const [ex, ey] = point(i, 100);
        return (
          <line
            key={i}
            x1={cx}
            y1={cy}
            x2={ex}
            y2={ey}
            stroke="currentColor"
            className="text-slate-200 dark:text-slate-700"
            strokeWidth="0.5"
          />
        );
      })}
      {/* Data area */}
      <polygon
        points={dataPath}
        fill="rgba(59, 130, 246, 0.15)"
        stroke="#3b82f6"
        strokeWidth="1.5"
      />
      {/* Data points */}
      {dataPts.map((p, i) => (
        <circle key={i} cx={p[0]} cy={p[1]} r="3" fill="#3b82f6" />
      ))}
      {/* Labels */}
      {labels.map((l, i) => (
        <text
          key={i}
          x={l.x}
          y={l.y}
          textAnchor="middle"
          dominantBaseline="middle"
          className="text-slate-500 dark:text-slate-400 fill-current"
          fontSize="7"
        >
          {l.label.split(" ").length > 1
            ? l.label.split(" ").map((w, wi) => (
                <tspan key={wi} x={l.x} dy={wi === 0 ? 0 : 9}>
                  {w}
                </tspan>
              ))
            : l.label}
        </text>
      ))}
    </svg>
  );
}

export default function HealthScoreCard({ healthScore, isPro }: HealthScoreCardProps) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const grade = healthScore.grade;
  const dims = healthScore.dimensions;

  return (
    <div className="space-y-6">
      {/* Overall grade card */}
      <div className={`border rounded-2xl p-6 text-center ${GRADE_BG[grade] || GRADE_BG.C}`}>
        <div className={`text-6xl font-bold mb-2 ${GRADE_COLORS[grade] || "text-slate-600"}`}>
          {grade}
        </div>
        <div className="text-lg font-semibold text-slate-700 dark:text-slate-300">
          Architecture Health Score
        </div>
        <div className="text-sm text-slate-500 dark:text-slate-400 mt-1">
          {healthScore.overall_score}/100
        </div>
      </div>

      {/* Radar chart */}
      <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-2xl p-6">
        <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300 mb-4 text-center">
          Score Breakdown
        </h3>
        <RadarChart dimensions={dims} />
      </div>

      {/* Dimension details */}
      <div className="space-y-2">
        {DIM_ORDER.filter((k) => k in dims).map((key) => {
          const dim = dims[key];
          const isExpanded = expanded === key;
          const barColor =
            dim.score >= 80 ? "bg-green-500" :
            dim.score >= 60 ? "bg-yellow-500" :
            dim.score >= 40 ? "bg-orange-500" : "bg-red-500";

          return (
            <button
              key={key}
              onClick={() => setExpanded(isExpanded ? null : key)}
              className="w-full text-left bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl p-4 hover:border-blue-300 dark:hover:border-blue-600 transition-colors"
            >
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
                  {dim.label}
                </span>
                <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                  {dim.score}/100
                </span>
              </div>
              <div className="h-2 bg-slate-100 dark:bg-slate-700 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all ${barColor}`}
                  style={{ width: `${dim.score}%` }}
                />
              </div>
              {isExpanded && (
                <p className="mt-3 text-xs text-slate-500 dark:text-slate-400 leading-relaxed">
                  {_getDimDescription(key, dim.score)}
                </p>
              )}
            </button>
          );
        })}
      </div>

      {/* CTA for free users */}
      {!isPro && (
        <div className="bg-gradient-to-r from-blue-50 to-indigo-50 dark:from-blue-900/20 dark:to-indigo-900/20 border border-blue-200 dark:border-blue-700 rounded-2xl p-6 text-center">
          <h3 className="font-semibold text-slate-900 dark:text-slate-100 mb-1">
            Get a Detailed Assessment
          </h3>
          <p className="text-sm text-slate-600 dark:text-slate-400 mb-3">
            Professional health narrative, tech debt analysis, and prioritized recommendations.
          </p>
          <a
            href="/settings"
            className="inline-block bg-blue-600 text-white text-sm font-medium px-5 py-2 rounded-lg hover:bg-blue-700 transition-colors"
          >
            Upgrade to Pro
          </a>
        </div>
      )}
    </div>
  );
}

function _getDimDescription(key: string, score: number): string {
  const quality = score >= 80 ? "strong" : score >= 60 ? "moderate" : score >= 40 ? "needs improvement" : "critical";
  const descriptions: Record<string, string> = {
    modularity: `Modularity is ${quality}. This measures how well the codebase is organized into distinct modules with clear boundaries and manageable import relationships.`,
    documentation: `Documentation is ${quality}. This evaluates README quality, inline comments, docstrings, and the presence of contributor guidelines.`,
    test_coverage: `Test coverage is ${quality}. This measures the ratio of test files to source files and the breadth of testing across the codebase.`,
    dependency_health: `Dependency health is ${quality}. This evaluates the number of external dependencies, which affects maintenance burden and security surface area.`,
    code_organization: `Code organization is ${quality}. This assesses naming consistency, entry point clarity, separation of concerns, and adherence to architectural patterns.`,
    complexity: `Complexity is ${quality}. This evaluates average file sizes, maximum file sizes, and directory nesting depth — simpler is better.`,
  };
  return descriptions[key] || `Score: ${score}/100`;
}
