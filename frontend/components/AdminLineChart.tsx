import { useRef, useEffect } from "react";
import * as d3 from "d3";
import type { DailyAnalysisStat } from "../lib/api";

interface Props {
  data: DailyAnalysisStat[];
}

const MARGIN = { top: 16, right: 24, bottom: 36, left: 40 };
const WIDTH = 600;
const HEIGHT = 220;
const INNER_W = WIDTH - MARGIN.left - MARGIN.right;
const INNER_H = HEIGHT - MARGIN.top - MARGIN.bottom;

export default function AdminLineChart({ data }: Props) {
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    // Build dense 30-day date array
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const dates: Date[] = [];
    for (let i = 29; i >= 0; i--) {
      const d = new Date(today);
      d.setDate(d.getDate() - i);
      dates.push(d);
    }

    const byDate = new Map(data.map((r) => [r.date, r]));
    const dense = dates.map((d) => {
      const key = d.toISOString().slice(0, 10);
      const r = byDate.get(key);
      return { date: d, total: r?.total ?? 0, completed: r?.completed ?? 0, failed: r?.failed ?? 0 };
    });

    const x = d3.scaleTime().domain([dates[0], dates[dates.length - 1]]).range([0, INNER_W]);
    const yMax = d3.max(dense, (d) => d.total) ?? 1;
    const y = d3.scaleLinear().domain([0, Math.max(yMax, 1)]).nice().range([INNER_H, 0]);

    const g = svg
      .append("g")
      .attr("transform", `translate(${MARGIN.left},${MARGIN.top})`);

    // Axes
    g.append("g")
      .attr("transform", `translate(0,${INNER_H})`)
      .call(
        d3.axisBottom(x)
          .ticks(6)
          .tickFormat((d) => d3.timeFormat("%b %d")(d as Date))
      )
      .call((a) => a.select(".domain").remove())
      .call((a) => a.selectAll("line").attr("stroke", "#e2e8f0"))
      .call((a) => a.selectAll("text").attr("fill", "#94a3b8").attr("font-size", "11px"));

    g.append("g")
      .call(d3.axisLeft(y).ticks(4))
      .call((a) => a.select(".domain").remove())
      .call((a) => a.selectAll("line").attr("stroke", "#e2e8f0"))
      .call((a) => a.selectAll("text").attr("fill", "#94a3b8").attr("font-size", "11px"));

    // Grid lines
    g.append("g")
      .attr("class", "grid")
      .call(d3.axisLeft(y).ticks(4).tickSize(-INNER_W).tickFormat(() => ""))
      .call((a) => a.select(".domain").remove())
      .call((a) => a.selectAll("line").attr("stroke", "#f1f5f9").attr("stroke-dasharray", "3,3"));

    // Lines
    const lines: { key: keyof typeof dense[0]; color: string }[] = [
      { key: "total", color: "#64748b" },
      { key: "completed", color: "#10b981" },
      { key: "failed", color: "#ef4444" },
    ];

    for (const { key, color } of lines) {
      const line = d3.line<(typeof dense)[0]>()
        .x((d) => x(d.date))
        .y((d) => y(d[key] as number))
        .curve(d3.curveMonotoneX);

      g.append("path")
        .datum(dense)
        .attr("fill", "none")
        .attr("stroke", color)
        .attr("stroke-width", 2)
        .attr("d", line);
    }
  }, [data]);

  return (
    <div>
      <svg ref={svgRef} viewBox={`0 0 ${WIDTH} ${HEIGHT}`} width="100%" />
      <div className="flex items-center gap-4 mt-1 px-10 text-xs text-slate-500">
        <span className="flex items-center gap-1"><span className="inline-block w-3 h-0.5 bg-slate-500 rounded" />Total</span>
        <span className="flex items-center gap-1"><span className="inline-block w-3 h-0.5 bg-emerald-500 rounded" />Completed</span>
        <span className="flex items-center gap-1"><span className="inline-block w-3 h-0.5 bg-red-500 rounded" />Failed</span>
      </div>
    </div>
  );
}
