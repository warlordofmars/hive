// Copyright (c) 2026 John Carter. All rights reserved.
import React, { useCallback, useEffect, useState } from "react";
import PropTypes from "prop-types";
import { api } from "../api.js";
import EmptyState from "./EmptyState.jsx";
import ActivityHeatmap from "./stats/ActivityHeatmap.jsx";
import MemoryGrowth from "./stats/MemoryGrowth.jsx";
import QuotaGauge from "./stats/QuotaGauge.jsx";
import TagDistribution from "./stats/TagDistribution.jsx";
import TopRecalled from "./stats/TopRecalled.jsx";
import { Card } from "./ui/card.jsx";

// #535 — Stats tab scaffolding.
//
// Renders a grid of GraphCards backed by /api/account/stats. Five cards
// are fully implemented (ActivityHeatmap, TopRecalled, TagDistribution,
// MemoryGrowth, QuotaGauge); the remaining three (Freshness,
// ClientContribution, TagCooccurrence) still show a JSON preview via
// RawPreview until their dedicated sub-issues (#538 / #539 / #540) land.

const WINDOWS = [
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last 90 days" },
  { value: "365", label: "Last year" },
];

function hasData(value) {
  if (Array.isArray(value)) return value.length > 0;
  if (value && typeof value === "object") return Object.keys(value).length > 0;
  return false;
}

export function GraphCard({ title, description, data, empty, children }) {
  return (
    <Card className="p-4 flex flex-col min-w-0">
      <div className="mb-1 text-sm font-semibold text-[var(--text)]">{title}</div>
      {description && (
        <div className="mb-3 text-xs text-[var(--text-muted)]">{description}</div>
      )}
      {hasData(data) ? (
        children
      ) : (
        <div className="text-xs text-[var(--text-muted)] italic py-2">
          {empty ?? "No data yet."}
        </div>
      )}
    </Card>
  );
}

GraphCard.propTypes = {
  title: PropTypes.string.isRequired,
  description: PropTypes.string,
  data: PropTypes.oneOfType([PropTypes.array, PropTypes.object]),
  empty: PropTypes.string,
  children: PropTypes.node,
};

// Stub body shared by every graph until a sub-issue ships the real chart.
// Shows a compact JSON preview so we can eyeball the aggregate shape on
// the deployed page without waiting for all the chart work.
function RawPreview({ value, take = 5 }) {
  // Called with arrays only — the <GraphCard> parent suppresses us when
  // its `data` prop is empty/missing, so non-array cases can't reach
  // here.
  const overflow = value.length > take ? `\n…(+${value.length - take} more)` : "";
  return (
    <pre className="text-[11px] leading-snug text-[var(--text-muted)] overflow-x-auto m-0">
      {JSON.stringify(value.slice(0, take), null, 2)}
      {overflow}
    </pre>
  );
}

RawPreview.propTypes = {
  value: PropTypes.array,
  take: PropTypes.number,
};

export default function Stats() {
  const [windowDays, setWindowDays] = useState("90");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setData(await api.getAccountStats(windowDays));
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [windowDays]);

  useEffect(() => {
    load();
  }, [load]);

  if (error) {
    return (
      <div>
        <h2 className="text-lg font-semibold mb-4">My Stats</h2>
        <p className="text-[var(--danger)]">{error}</p>
      </div>
    );
  }

  if (loading && !data) {
    return (
      <div>
        <h2 className="text-lg font-semibold mb-4">My Stats</h2>
        <p className="text-[var(--text-muted)]">Loading…</p>
      </div>
    );
  }

  if (!data) return null;

  // Top-level empty state: no memories means there's nothing to graph at all.
  if (data.quota?.memory_count === 0) {
    return (
      <div>
        <h2 className="text-lg font-semibold mb-4">My Stats</h2>
        <EmptyState
          variant="activity"
          title="No data yet"
          description="Stats will populate as you remember, recall, and tag memories."
        />
      </div>
    );
  }

  return (
    <div>
      <div className="flex flex-wrap gap-2 items-center mb-5">
        <h2 className="text-lg font-semibold mr-2">My Stats</h2>
        {WINDOWS.map((w) => (
          <button
            key={w.value}
            type="button"
            onClick={() => setWindowDays(w.value)}
            className={`px-3 py-1 rounded-md border text-xs ${
              windowDays === w.value
                ? "bg-[var(--accent)] text-[#1a1a2e] border-[var(--accent)] font-semibold"
                : "border-[var(--border)] text-[var(--text)]"
            }`}
          >
            {w.label}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <GraphCard
          title="Activity heatmap"
          description="Events per day across the past year."
          data={data.activity_heatmap?.filter((d) => d.count > 0)}
          empty="No activity in this window yet."
        >
          <ActivityHeatmap data={data.activity_heatmap} />
        </GraphCard>

        <GraphCard
          title="Top recalled"
          description="Your most-hit memories — click to open."
          data={data.top_recalled}
          empty="No memory has been recalled yet."
        >
          <TopRecalled data={data.top_recalled} />
        </GraphCard>

        <GraphCard
          title="Tag distribution"
          description="Memories per tag — click a slice to filter."
          data={data.tag_distribution}
          empty="No tags assigned yet."
        >
          <TagDistribution data={data.tag_distribution} />
        </GraphCard>

        <GraphCard
          title="Memory growth"
          description="Cumulative memory count over the window."
          data={data.memory_growth}
        >
          <MemoryGrowth data={data.memory_growth} />
        </GraphCard>

        <GraphCard
          title="Quota"
          description="Current memory count against your plan limit."
          data={data.quota}
        >
          <QuotaGauge quota={data.quota} />
        </GraphCard>

        <GraphCard
          title="Freshness"
          description="Days since creation and last access per memory."
          data={data.freshness}
        >
          <RawPreview value={data.freshness} />
        </GraphCard>

        <GraphCard
          title="Client contribution"
          description="Events per day, split by OAuth client."
          data={data.client_contribution}
          empty="No client activity in this window."
        >
          <RawPreview value={data.client_contribution} />
        </GraphCard>

        <GraphCard
          title="Tag co-occurrence"
          description="Tags that appear together on the same memory."
          data={data.tag_cooccurrence}
          empty="No co-tagged memories yet."
        >
          <RawPreview value={data.tag_cooccurrence} />
        </GraphCard>
      </div>
    </div>
  );
}
