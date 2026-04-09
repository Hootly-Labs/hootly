import { useEffect, useRef, useState, useMemo } from "react";
import type { GraphData, GraphEdge, KeyFile } from "../lib/api";

const LANG_COLORS: Record<string, string> = {
  python:     "#3b82f6",
  javascript: "#f59e0b",
  typescript: "#06b6d4",
  go:         "#10b981",
  rust:       "#f97316",
  ruby:       "#ec4899",
  java:       "#8b5cf6",
  csharp:     "#a855f7",
  cpp:        "#64748b",
  c:          "#94a3b8",
  other:      "#94a3b8",
};

const LANG_LABELS: Record<string, string> = {
  python: "Python", javascript: "JavaScript", typescript: "TypeScript",
  go: "Go", rust: "Rust", ruby: "Ruby", java: "Java",
  csharp: "C#", cpp: "C++", c: "C", other: "Other",
};

// Palette for directory-based coloring
const DIR_PALETTE = [
  "#3b82f6", "#f59e0b", "#10b981", "#f97316", "#ec4899",
  "#8b5cf6", "#06b6d4", "#84cc16", "#ef4444", "#14b8a6",
  "#a855f7", "#fb923c", "#22d3ee", "#4ade80", "#f472b6",
];

function topDir(id: string): string {
  const slash = id.indexOf("/");
  return slash === -1 ? "." : id.slice(0, slash);
}

function buildDirColorMap(nodes: { id: string }[]): Map<string, string> {
  const dirs = [...new Set(nodes.map((n) => topDir(n.id)))].sort();
  const map = new Map<string, string>();
  dirs.forEach((d, i) => map.set(d, DIR_PALETTE[i % DIR_PALETTE.length]));
  return map;
}

function nodeRadius(importance: number): number {
  return 6 + Math.max(1, importance) * 1.5;
}

interface SelectedInfo {
  id: string;
  language: string;
  imports: string[];
  importedBy: string[];
}

interface Props {
  graph: GraphData;
  keyFiles: KeyFile[];
}

type ColorBy = "language" | "directory";

export default function DependencyGraph({ graph, keyFiles }: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const highlightRef = useRef<((id: string | null) => void) | null>(null);
  // Preserve node positions across color-mode toggles
  const positionsRef = useRef<Record<string, { x: number; y: number }>>({});

  const [showIsolated, setShowIsolated] = useState(false);
  const [selected, setSelected] = useState<SelectedInfo | null>(null);
  const [colorBy, setColorBy] = useState<ColorBy>(() => {
    if (typeof window === "undefined") return "language";
    return (localStorage.getItem("hl_graph_color") as ColorBy) || "language";
  });

  const importanceMap = useMemo(
    () => new Map(keyFiles.map((f) => [f.path, f.score])),
    [keyFiles]
  );
  const explanationMap = useMemo(
    () => new Map(keyFiles.map((f) => [f.path, f.explanation])),
    [keyFiles]
  );

  // Which nodes have at least one edge
  const connectedIds = useMemo(() => {
    const s = new Set<string>();
    graph.edges.forEach((e) => { s.add(e.source); s.add(e.target); });
    return s;
  }, [graph]);

  const visibleNodes = useMemo(
    () => graph.nodes.filter((n) => showIsolated || connectedIds.has(n.id)),
    [graph, showIsolated, connectedIds]
  );
  const visibleNodeIds = useMemo(
    () => new Set(visibleNodes.map((n) => n.id)),
    [visibleNodes]
  );
  const visibleEdges = useMemo(
    () => graph.edges.filter((e) => visibleNodeIds.has(e.source) && visibleNodeIds.has(e.target)),
    [graph.edges, visibleNodeIds]
  );

  const isolatedCount = graph.nodes.length - connectedIds.size;

  // Directory → color map
  const dirColorMap = useMemo(() => buildDirColorMap(visibleNodes), [visibleNodes]);

  function getNodeColor(node: { id: string; language: string }): string {
    if (colorBy === "directory") {
      return dirColorMap.get(topDir(node.id)) ?? "#94a3b8";
    }
    return LANG_COLORS[node.language] ?? "#94a3b8";
  }

  // Navigate to a node from the info panel
  function navigateTo(nodeId: string) {
    const n = graph.nodes.find((n) => n.id === nodeId);
    const lang = n?.language ?? "other";
    const imports   = visibleEdges.filter((e) => e.source === nodeId).map((e) => e.target);
    const importedBy = visibleEdges.filter((e) => e.target === nodeId).map((e) => e.source);
    setSelected({ id: nodeId, language: lang, imports, importedBy });
    highlightRef.current?.(nodeId);
  }

  // ── D3 effect ──────────────────────────────────────────────────────────────
  useEffect(() => {
    const svgEl = svgRef.current;
    if (!svgEl || visibleNodes.length === 0) return;

    let stopped = false;

    import("d3").then((d3) => {
      if (stopped) return;

      const sel = d3.select(svgEl);
      sel.selectAll("*").remove();

      const W = svgEl.clientWidth || 900;
      const H = svgEl.clientHeight || 560;

      // ── Arrow markers ──
      const defs = sel.append("defs");
      function makeArrow(id: string, color: string) {
        defs.append("marker")
          .attr("id", id)
          .attr("viewBox", "0 -4 8 8")
          .attr("refX", 24)
          .attr("refY", 0)
          .attr("markerWidth", 5)
          .attr("markerHeight", 5)
          .attr("orient", "auto")
          .append("path")
          .attr("d", "M0,-4L8,0L0,4")
          .attr("fill", color);
      }
      makeArrow("arrow-dim",  "#cbd5e1");
      makeArrow("arrow-on",   "#3b82f6");

      // ── Zoom container ──
      const g = sel.append("g");
      sel.call(
        d3.zoom<SVGSVGElement, unknown>()
          .scaleExtent([0.1, 6])
          .on("zoom", (ev) => g.attr("transform", ev.transform.toString()))
      );

      // ── Simulation data — reuse saved positions if available ──
      const spread = Math.max(300, Math.sqrt(visibleNodes.length) * 40);
      const simNodes: any[] = visibleNodes.map((n) => {
        const saved = positionsRef.current[n.id];
        return {
          ...n,
          importance: importanceMap.get(n.id) ?? 3,
          x: saved?.x ?? W / 2 + (Math.random() - 0.5) * spread,
          y: saved?.y ?? H / 2 + (Math.random() - 0.5) * spread,
          // pin if we had a saved position so the layout doesn't reset
          fx: saved ? saved.x : undefined,
          fy: saved ? saved.y : undefined,
        };
      });

      const simEdges: any[] = visibleEdges.map((e) => ({ source: e.source, target: e.target }));

      const simulation = d3.forceSimulation(simNodes)
        .force("link", d3.forceLink(simEdges).id((d: any) => d.id).distance(95).strength(0.45))
        .force("charge", d3.forceManyBody().strength(-280))
        .force("center", d3.forceCenter(W / 2, H / 2).strength(0.06))
        .force("collide", d3.forceCollide().radius((d: any) => nodeRadius(d.importance) + 8));

      // Release pinned positions after one tick so the simulation can refine layout
      setTimeout(() => {
        simNodes.forEach((d: any) => { d.fx = undefined; d.fy = undefined; });
        simulation.alpha(0.1).restart();
      }, 50);

      // ── Links ──
      const link = g.append("g")
        .selectAll<SVGLineElement, any>("line")
        .data(simEdges)
        .join("line")
        .attr("stroke", "#cbd5e1")
        .attr("stroke-width", 1.5)
        .attr("stroke-opacity", 0.7)
        .attr("marker-end", "url(#arrow-dim)");

      // ── Node groups ──
      const nodeG = g.append("g")
        .selectAll<SVGGElement, any>("g")
        .data(simNodes)
        .join("g")
        .attr("cursor", "pointer")
        .call(
          d3.drag<SVGGElement, any>()
            .on("start", (ev, d) => { if (!ev.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
            .on("drag",  (ev, d) => { d.fx = ev.x; d.fy = ev.y; })
            .on("end",   (ev)    => { if (!ev.active) simulation.alphaTarget(0); })
        );

      nodeG.append("circle")
        .attr("r",            (d: any) => nodeRadius(d.importance))
        .attr("fill",         (d: any) => getNodeColor(d))
        .attr("stroke",       "#fff")
        .attr("stroke-width", 2);

      nodeG.append("text")
        .attr("dy",            (d: any) => nodeRadius(d.importance) + 13)
        .attr("text-anchor",   "middle")
        .attr("font-size",     "11")
        .attr("font-family",   "ui-monospace, 'JetBrains Mono', monospace")
        .attr("fill",          "#64748b")
        .attr("pointer-events","none")
        .text((d: any) => d.label.length > 22 ? d.label.slice(0, 21) + "…" : d.label);

      nodeG.append("title").text((d: any) => d.id);

      // ── Highlight helper ──
      function highlight(selectedId: string | null) {
        if (!selectedId) {
          nodeG.select("circle")
            .attr("opacity", 1)
            .attr("stroke", "#fff")
            .attr("stroke-width", 2);
          nodeG.select("text").attr("opacity", 1).attr("fill", "#64748b");
          link
            .attr("stroke", "#cbd5e1")
            .attr("stroke-opacity", 0.7)
            .attr("stroke-width", 1.5)
            .attr("marker-end", "url(#arrow-dim)");
          return;
        }

        const connected = new Set([selectedId]);
        simEdges.forEach((e: any) => {
          const s = e.source?.id ?? e.source;
          const t = e.target?.id ?? e.target;
          if (s === selectedId) connected.add(t);
          if (t === selectedId) connected.add(s);
        });

        nodeG.select("circle")
          .attr("opacity",      (d: any) => connected.has(d.id) ? 1 : 0.12)
          .attr("stroke",       (d: any) => d.id === selectedId ? "#1d4ed8" : "#fff")
          .attr("stroke-width", (d: any) => d.id === selectedId ? 3 : 2);
        nodeG.select("text")
          .attr("opacity", (d: any) => connected.has(d.id) ? 1 : 0.08)
          .attr("fill",    (d: any) => d.id === selectedId ? "#1d4ed8" : "#64748b");

        link
          .attr("stroke", (e: any) => {
            const s = e.source?.id ?? e.source;
            const t = e.target?.id ?? e.target;
            return s === selectedId || t === selectedId ? "#3b82f6" : "#cbd5e1";
          })
          .attr("stroke-opacity", (e: any) => {
            const s = e.source?.id ?? e.source;
            const t = e.target?.id ?? e.target;
            return s === selectedId || t === selectedId ? 1 : 0.06;
          })
          .attr("stroke-width", (e: any) => {
            const s = e.source?.id ?? e.source;
            const t = e.target?.id ?? e.target;
            return s === selectedId || t === selectedId ? 2 : 1.5;
          })
          .attr("marker-end", (e: any) => {
            const s = e.source?.id ?? e.source;
            const t = e.target?.id ?? e.target;
            return s === selectedId || t === selectedId ? "url(#arrow-on)" : "url(#arrow-dim)";
          });
      }

      highlightRef.current = highlight;

      // ── Click handlers ──
      nodeG.on("click", (ev, d: any) => {
        ev.stopPropagation();
        const lang = d.language as string;
        const imports   = simEdges.filter((e: any) => (e.source?.id ?? e.source) === d.id)
                                  .map((e: any) => e.target?.id ?? e.target);
        const importedBy = simEdges.filter((e: any) => (e.target?.id ?? e.target) === d.id)
                                   .map((e: any) => e.source?.id ?? e.source);
        setSelected({ id: d.id, language: lang, imports, importedBy });
        highlight(d.id);
      });

      sel.on("click", () => {
        setSelected(null);
        highlight(null);
      });

      // ── Tick — update positions and save them ──
      simulation.on("tick", () => {
        link
          .attr("x1", (d: any) => d.source.x ?? 0)
          .attr("y1", (d: any) => d.source.y ?? 0)
          .attr("x2", (d: any) => d.target.x ?? 0)
          .attr("y2", (d: any) => d.target.y ?? 0);
        nodeG.attr("transform", (d: any) => `translate(${d.x ?? 0},${d.y ?? 0})`);

        // Persist positions so a color-mode toggle doesn't reset the layout
        simNodes.forEach((d: any) => {
          if (d.x != null && d.y != null) {
            positionsRef.current[d.id] = { x: d.x, y: d.y };
          }
        });
      });
    });

    return () => { stopped = true; };
  // colorBy is intentionally in the dep array — toggling rebuilds the graph
  // but node positions are restored from positionsRef so layout is preserved.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visibleNodes, visibleEdges, importanceMap, colorBy, dirColorMap]);

  // ── Derived UI data ──────────────────────────────────────────────────────
  const presentLanguages = useMemo(
    () => [...new Set(visibleNodes.map((n) => n.language).filter((l) => l !== "other"))],
    [visibleNodes]
  );

  const presentDirs = useMemo(
    () => [...dirColorMap.entries()].sort((a, b) => a[0].localeCompare(b[0])),
    [dirColorMap]
  );

  const selectedExplanation = selected ? explanationMap.get(selected.id) : undefined;

  return (
    <div className="space-y-3">
      {/* Stats + controls */}
      <div className="flex items-center gap-3 flex-wrap text-sm text-slate-500">
        <span>
          <span className="font-semibold text-slate-700">{visibleNodes.length}</span> files ·{" "}
          <span className="font-semibold text-slate-700">{visibleEdges.length}</span> connections
        </span>

        {/* Color-by toggle */}
        <div className="flex items-center gap-1 border border-slate-200 rounded-full p-0.5">
          <button
            onClick={() => setColorBy("language")}
            className={`text-xs rounded-full px-3 py-1 transition-colors ${
              colorBy === "language"
                ? "bg-blue-600 text-white"
                : "text-slate-500 hover:text-slate-700"
            }`}
          >
            By language
          </button>
          <button
            onClick={() => setColorBy("directory")}
            className={`text-xs rounded-full px-3 py-1 transition-colors ${
              colorBy === "directory"
                ? "bg-blue-600 text-white"
                : "text-slate-500 hover:text-slate-700"
            }`}
          >
            By directory
          </button>
        </div>

        {isolatedCount > 0 && (
          <button
            onClick={() => { setSelected(null); setShowIsolated((s) => !s); }}
            className={`text-xs border rounded-full px-3 py-1 transition-colors ${
              showIsolated
                ? "bg-blue-50 border-blue-300 text-blue-700"
                : "border-slate-300 hover:border-slate-400 text-slate-600"
            }`}
          >
            {showIsolated ? "Hide" : "Show"} {isolatedCount} isolated files
          </button>
        )}

        <span className="text-xs text-slate-400 hidden sm:inline">
          Scroll to zoom · Drag nodes to pin · Click to inspect
        </span>
      </div>

      {/* Main panel */}
      <div className="flex gap-4">
        {/* SVG canvas */}
        <div
          className="flex-1 min-w-0 relative bg-slate-50 border border-slate-200 rounded-2xl overflow-hidden"
          style={{ height: 560 }}
        >
          {visibleNodes.length === 0 ? (
            <EmptyState onShowIsolated={() => setShowIsolated(true)} hasIsolated={isolatedCount > 0} />
          ) : (
            <svg ref={svgRef} width="100%" height="100%" className="block" />
          )}

          {/* Legend */}
          {colorBy === "language" && presentLanguages.length > 0 && (
            <div className="absolute top-3 left-3 bg-white/95 border border-slate-200 rounded-xl p-2.5 shadow-sm text-xs space-y-1.5 max-h-52 overflow-y-auto">
              {presentLanguages.map((lang) => (
                <div key={lang} className="flex items-center gap-2">
                  <div
                    className="w-3 h-3 rounded-full shrink-0"
                    style={{ background: LANG_COLORS[lang] ?? "#94a3b8" }}
                  />
                  <span className="text-slate-600">{LANG_LABELS[lang] ?? lang}</span>
                </div>
              ))}
              <div className="flex items-center gap-2 pt-1 border-t border-slate-100 mt-1">
                <div className="flex items-center gap-0.5">
                  <div className="w-1.5 h-1.5 rounded-full bg-slate-300" />
                  <div className="w-3 h-3 rounded-full bg-slate-400" />
                </div>
                <span className="text-slate-400">size = importance</span>
              </div>
            </div>
          )}

          {colorBy === "directory" && presentDirs.length > 0 && (
            <div className="absolute top-3 left-3 bg-white/95 border border-slate-200 rounded-xl p-2.5 shadow-sm text-xs space-y-1.5 max-h-52 overflow-y-auto">
              {presentDirs.map(([dir, color]) => (
                <div key={dir} className="flex items-center gap-2">
                  <div
                    className="w-3 h-3 rounded-full shrink-0"
                    style={{ background: color }}
                  />
                  <span className="text-slate-600 font-mono">{dir === "." ? "(root)" : dir + "/"}</span>
                </div>
              ))}
              <div className="flex items-center gap-2 pt-1 border-t border-slate-100 mt-1">
                <div className="flex items-center gap-0.5">
                  <div className="w-1.5 h-1.5 rounded-full bg-slate-300" />
                  <div className="w-3 h-3 rounded-full bg-slate-400" />
                </div>
                <span className="text-slate-400">size = importance</span>
              </div>
            </div>
          )}

          {/* Hint */}
          <div className="absolute bottom-3 right-3 text-xs text-slate-400 select-none">
            ⌘ scroll to zoom
          </div>
        </div>

        {/* Info panel */}
        {selected && (
          <div
            className="w-64 shrink-0 bg-white border border-slate-200 rounded-2xl p-4 overflow-y-auto space-y-4"
            style={{ maxHeight: 560 }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="flex items-start justify-between gap-2">
              <code className="text-xs font-mono text-blue-700 break-all leading-relaxed flex-1">
                {selected.id}
              </code>
              <button
                onClick={() => { setSelected(null); highlightRef.current?.(null); }}
                className="shrink-0 text-slate-400 hover:text-slate-700 transition-colors mt-0.5"
                aria-label="Close"
              >
                <svg className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                  <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
                </svg>
              </button>
            </div>

            {/* Language + directory + score */}
            <div className="flex items-center gap-2 flex-wrap">
              <span
                className="text-xs font-medium text-white rounded-full px-2.5 py-0.5"
                style={{ background: LANG_COLORS[selected.language] ?? "#94a3b8" }}
              >
                {LANG_LABELS[selected.language] ?? selected.language}
              </span>
              <span
                className="text-xs font-medium rounded-full px-2.5 py-0.5 border"
                style={{
                  color: dirColorMap.get(topDir(selected.id)) ?? "#64748b",
                  borderColor: dirColorMap.get(topDir(selected.id)) ?? "#e2e8f0",
                  background: (dirColorMap.get(topDir(selected.id)) ?? "#94a3b8") + "15",
                }}
              >
                {topDir(selected.id) === "." ? "root" : topDir(selected.id) + "/"}
              </span>
              {importanceMap.has(selected.id) && (
                <span className="text-xs text-slate-500">
                  score {importanceMap.get(selected.id)}/10
                </span>
              )}
            </div>

            {/* Explanation */}
            {selectedExplanation && (
              <p className="text-xs text-slate-600 leading-relaxed">{selectedExplanation}</p>
            )}

            {/* Imports list */}
            {selected.imports.length > 0 && (
              <FileList
                title={`Imports (${selected.imports.length})`}
                paths={selected.imports}
                prefix="→"
                prefixColor="text-blue-500"
                onNavigate={navigateTo}
              />
            )}

            {/* Imported by list */}
            {selected.importedBy.length > 0 && (
              <FileList
                title={`Imported by (${selected.importedBy.length})`}
                paths={selected.importedBy}
                prefix="←"
                prefixColor="text-slate-400"
                onNavigate={navigateTo}
              />
            )}

            {selected.imports.length === 0 && selected.importedBy.length === 0 && (
              <p className="text-xs text-slate-400">No connections visible in current view.</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Sub-components ────────────────────────────────────────────────────────────

function FileList({
  title, paths, prefix, prefixColor, onNavigate,
}: {
  title: string;
  paths: string[];
  prefix: string;
  prefixColor: string;
  onNavigate: (id: string) => void;
}) {
  return (
    <div>
      <p className="text-xs uppercase font-semibold text-slate-400 tracking-wider mb-1.5">{title}</p>
      <div className="space-y-1">
        {paths.map((p) => (
          <button
            key={p}
            onClick={() => onNavigate(p)}
            className="flex items-center gap-1.5 text-xs font-mono text-left w-full hover:text-blue-700 transition-colors group"
          >
            <span className={`shrink-0 ${prefixColor}`}>{prefix}</span>
            <span className="truncate text-slate-600 group-hover:text-blue-700">
              {p.split("/").pop()}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

function EmptyState({ onShowIsolated, hasIsolated }: { onShowIsolated: () => void; hasIsolated: boolean }) {
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center text-slate-400 p-8 text-center">
      <svg className="h-12 w-12 mb-3 text-slate-200" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
          d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
      </svg>
      <p className="text-sm font-medium text-slate-500 mb-1">No import connections detected</p>
      <p className="text-xs text-slate-400 mb-4 max-w-xs">
        This repo may use absolute imports or a language pattern not yet parsed.
      </p>
      {hasIsolated && (
        <button
          onClick={onShowIsolated}
          className="text-xs border border-slate-300 rounded-full px-4 py-1.5 hover:border-blue-400 hover:text-blue-700 transition-colors"
        >
          Show all files as nodes
        </button>
      )}
    </div>
  );
}
