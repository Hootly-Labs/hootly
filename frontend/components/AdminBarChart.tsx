import { useRef, useEffect } from "react";
import * as d3 from "d3";
import type { DailySignupStat } from "../lib/api";

interface Props {
  data: DailySignupStat[];
}

const MARGIN = { top: 16, right: 24, bottom: 36, left: 40 };
const WIDTH = 600;
const HEIGHT = 200;
const INNER_W = WIDTH - MARGIN.left - MARGIN.right;
const INNER_H = HEIGHT - MARGIN.top - MARGIN.bottom;

export default function AdminBarChart({ data }: Props) {
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

    const byDate = new Map(data.map((r) => [r.date, r.signups]));
    const dense = dates.map((d) => ({
      date: d,
      label: d.toISOString().slice(0, 10),
      signups: byDate.get(d.toISOString().slice(0, 10)) ?? 0,
    }));

    const x = d3.scaleBand()
      .domain(dense.map((d) => d.label))
      .range([0, INNER_W])
      .padding(0.25);

    const yMax = d3.max(dense, (d) => d.signups) ?? 1;
    const y = d3.scaleLinear().domain([0, Math.max(yMax, 1)]).nice().range([INNER_H, 0]);

    const g = svg
      .append("g")
      .attr("transform", `translate(${MARGIN.left},${MARGIN.top})`);

    // Grid lines
    g.append("g")
      .call(d3.axisLeft(y).ticks(4).tickSize(-INNER_W).tickFormat(() => ""))
      .call((a) => a.select(".domain").remove())
      .call((a) => a.selectAll("line").attr("stroke", "#f1f5f9").attr("stroke-dasharray", "3,3"));

    // X axis — show every 5th label
    const xAxis = d3.axisBottom(x)
      .tickValues(dense.filter((_, i) => i % 5 === 0).map((d) => d.label))
      .tickFormat((d) => {
        const dt = new Date(d + "T00:00:00");
        return d3.timeFormat("%b %d")(dt);
      });

    g.append("g")
      .attr("transform", `translate(0,${INNER_H})`)
      .call(xAxis)
      .call((a) => a.select(".domain").remove())
      .call((a) => a.selectAll("line").remove())
      .call((a) => a.selectAll("text").attr("fill", "#94a3b8").attr("font-size", "11px"));

    // Y axis
    g.append("g")
      .call(d3.axisLeft(y).ticks(4))
      .call((a) => a.select(".domain").remove())
      .call((a) => a.selectAll("line").remove())
      .call((a) => a.selectAll("text").attr("fill", "#94a3b8").attr("font-size", "11px"));

    // Bars
    g.selectAll("rect")
      .data(dense)
      .join("rect")
      .attr("x", (d) => x(d.label) ?? 0)
      .attr("y", (d) => y(d.signups))
      .attr("width", x.bandwidth())
      .attr("height", (d) => INNER_H - y(d.signups))
      .attr("fill", "#3b82f6")
      .attr("rx", 3);
  }, [data]);

  return (
    <svg ref={svgRef} viewBox={`0 0 ${WIDTH} ${HEIGHT}`} width="100%" />
  );
}
