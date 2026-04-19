// Copyright (c) 2026 John Carter. All rights reserved.
import React from "react";
import PropTypes from "prop-types";

// #537 — big visual of used / remaining memory count. Uses a semicircle
// SVG arc so it reads as a gauge rather than a bar-chart spinoff. Renders
// a flat count when `memory_limit` is null (admin / exempt users).

const RADIUS = 70;
const STROKE = 14;
const CENTER_X = 90;
const CENTER_Y = 90;

export function arcPath(fraction) {
  // Semicircle from 180° → 0° (left to right), clamped to [0, 1].
  const safe = Math.max(0, Math.min(1, fraction));
  const angle = Math.PI * (1 - safe); // 180° → 0°
  const startX = CENTER_X - RADIUS;
  const startY = CENTER_Y;
  const endX = CENTER_X + RADIUS * Math.cos(angle);
  const endY = CENTER_Y - RADIUS * Math.sin(angle);
  const largeArc = safe > 0.5 ? 1 : 0;
  return `M ${startX} ${startY} A ${RADIUS} ${RADIUS} 0 ${largeArc} 1 ${endX.toFixed(2)} ${endY.toFixed(2)}`;
}

export function fillColor(fraction) {
  if (fraction >= 0.9) return "var(--danger)";
  if (fraction >= 0.75) return "#f5a623";
  return "var(--accent)";
}

export default function QuotaGauge({ quota }) {
  if (!quota || typeof quota.memory_count !== "number") return null;

  const { memory_count: count, memory_limit: limit } = quota;

  // Unbounded (admin / exempt): render just the count.
  if (limit === null || limit === undefined) {
    return (
      <div className="flex flex-col items-center py-4" data-testid="quota-gauge-unbounded">
        <div className="text-4xl font-bold text-[var(--text)]">{count}</div>
        <div className="mt-1 text-xs text-[var(--text-muted)]">
          memories — no quota
        </div>
      </div>
    );
  }

  const fraction = limit > 0 ? count / limit : 0;
  const remaining = Math.max(0, limit - count);
  const color = fillColor(fraction);

  return (
    <div className="flex flex-col items-center py-2">
      <svg
        width="180"
        height="110"
        viewBox="0 0 180 110"
        role="img"
        aria-label={`Quota: ${count} of ${limit} memories used`}
      >
        {/* Track */}
        <path
          d={arcPath(1)}
          fill="none"
          stroke="var(--border)"
          strokeWidth={STROKE}
          strokeLinecap="round"
        />
        {/* Fill */}
        {fraction > 0 && (
          <path
            d={arcPath(fraction)}
            fill="none"
            stroke={color}
            strokeWidth={STROKE}
            strokeLinecap="round"
          />
        )}
      </svg>
      <div className="flex items-baseline gap-1 -mt-8">
        <span className="text-3xl font-bold text-[var(--text)]">{count}</span>
        <span className="text-sm text-[var(--text-muted)]">/ {limit}</span>
      </div>
      <div className="mt-1 text-xs text-[var(--text-muted)]">
        {remaining} remaining
      </div>
    </div>
  );
}

QuotaGauge.propTypes = {
  quota: PropTypes.shape({
    memory_count: PropTypes.number.isRequired,
    memory_limit: PropTypes.number,
  }),
};
