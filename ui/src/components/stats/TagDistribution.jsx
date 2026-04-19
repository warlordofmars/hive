// Copyright (c) 2026 John Carter. All rights reserved.
import React, { useMemo } from "react";
import PropTypes from "prop-types";
import { Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import EmptyState from "../EmptyState.jsx";

// #537 — donut chart of memory counts per tag. Clicking a slice jumps to
// the Memories tab pre-filtered by that tag.

const TOP_N = 8;
// Brand-orange + five complementary colours from Dashboard's TOOL_COLORS.
const SLICE_COLORS = [
  "#e8a020", // brand orange
  "#1a73e8", // blue
  "#00897b", // teal
  "#9334e8", // purple
  "#34a853", // green
  "#fb923c", // orange-500
  "#d93025", // red
  "#64748b", // slate
];
const OTHER_COLOR = "var(--text-muted)";

export function buildSlices(data) {
  const sorted = [...(data ?? [])].sort((a, b) => b.count - a.count);
  const head = sorted.slice(0, TOP_N);
  const tail = sorted.slice(TOP_N);
  const slices = head.map((d) => ({ tag: d.tag, count: d.count }));
  if (tail.length > 0) {
    const otherCount = tail.reduce((sum, d) => sum + d.count, 0);
    slices.push({ tag: "Other", count: otherCount, isOther: true });
  }
  return slices;
}

export function filterByTag(tag) {
  if (typeof globalThis.dispatchEvent !== "function") return;
  globalThis.dispatchEvent(
    new CustomEvent("hive:memory-browser", { detail: { tag } }),
  );
  globalThis.dispatchEvent(new CustomEvent("hive:switch-tab", { detail: "memories" }));
}

export default function TagDistribution({ data }) {
  const slices = useMemo(() => buildSlices(data), [data]);

  if (slices.length === 0) {
    return (
      <EmptyState
        variant="memories"
        title="No tags yet"
        description="Tag some memories to see how they cluster."
      />
    );
  }

  return (
    <ResponsiveContainer width="100%" height={260}>
      <PieChart>
        <Pie
          data={slices}
          dataKey="count"
          nameKey="tag"
          innerRadius={50}
          outerRadius={90}
          paddingAngle={2}
          onClick={(p) => {
            if (!p.isOther) filterByTag(p.tag);
          }}
          cursor="pointer"
        >
          {slices.map((s, i) => (
            <Cell
              key={s.tag}
              fill={s.isOther ? OTHER_COLOR : SLICE_COLORS[i % SLICE_COLORS.length]}
            />
          ))}
        </Pie>
        <Tooltip
          contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", fontSize: 12 }}
          formatter={(value, name) => [`${value} memories`, name]}
        />
        <Legend wrapperStyle={{ fontSize: 11, color: "var(--text-muted)" }} />
      </PieChart>
    </ResponsiveContainer>
  );
}

TagDistribution.propTypes = {
  data: PropTypes.arrayOf(
    PropTypes.shape({
      tag: PropTypes.string.isRequired,
      count: PropTypes.number.isRequired,
    }),
  ),
};
