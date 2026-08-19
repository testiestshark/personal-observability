// The weigh-in trend: raw readings as faint dots, with a smoothed 7-day average
// drawn over them. The average is the line to read — daily bodyweight swings by
// more than most people's monthly progress, so the raw series alone shows noise
// rather than direction.
//
// All of the arithmetic lives in lib/weight/trend.ts and is tested there. This file
// is layout: it picks a range, hands the numbers to recharts and formats labels.
import { useMemo, useState } from "react";
import {
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Button } from "@/components/ui/button";
import { buildTrend, WINDOW_DAYS, type TrendPoint } from "@/lib/weight/trend";
import { formatDayLabel } from "@/lib/weight/units";
import type { WeightEntry } from "@/lib/weight/weight.functions";

/** Null means every reading there is. */
const RANGES = [
  { label: "30d", days: 30 },
  { label: "90d", days: 90 },
  { label: "1y", days: 365 },
  { label: "All", days: null },
] as const;

const DEFAULT_RANGE = 90;

/** "2026-08-06" → "6 Aug", for an axis that has to fit many of them. */
function shortDay(day: string): string {
  const label = formatDayLabel(day); // "Thu 06 Aug 2026"
  const parts = label.split(" ");
  return `${Number(parts[1])} ${parts[2]}`;
}

function ChangeLabel({ changeKg }: { changeKg: number | null }) {
  if (changeKg === null) {
    return <span className="text-muted-foreground">Not enough readings yet</span>;
  }

  // Below 50g the direction is scale resolution, not a change worth naming.
  if (Math.abs(changeKg) < 0.05) {
    return <span className="text-muted-foreground">Holding steady</span>;
  }

  const down = changeKg < 0;
  return (
    <span className={down ? "text-emerald-600 dark:text-emerald-500" : "text-foreground"}>
      {down ? "↓" : "↑"} {Math.abs(changeKg).toFixed(1)} kg
    </span>
  );
}

function TrendTooltip({
  active,
  payload,
}: {
  active?: boolean | undefined;
  payload?: { payload: TrendPoint }[] | undefined;
}) {
  const point = active ? payload?.[0]?.payload : undefined;
  if (!point) return null;

  return (
    <div className="rounded-lg border border-border bg-popover px-3 py-2 text-xs shadow-md">
      <p className="font-medium text-popover-foreground">{formatDayLabel(point.day)}</p>
      <p className="mt-1 text-muted-foreground">
        Weighed <span className="text-popover-foreground">{point.weightKg.toFixed(1)} kg</span>
      </p>
      {point.averageKg !== null ? (
        <p className="text-muted-foreground">
          {WINDOW_DAYS}-day average{" "}
          <span className="text-popover-foreground">{point.averageKg.toFixed(1)} kg</span>
        </p>
      ) : null}
    </div>
  );
}

export function WeightTrend({ entries }: { entries: readonly WeightEntry[] }) {
  const [rangeDays, setRangeDays] = useState<number | null>(DEFAULT_RANGE);

  const { points, summary } = useMemo(
    () => buildTrend(entries, { rangeDays }),
    [entries, rangeDays],
  );

  // Two points is the minimum that can show a direction rather than a dot.
  const hasChart = points.length >= 2;

  return (
    <section className="rounded-xl border border-border bg-card p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-medium">Trend</h2>

        <div className="flex gap-1" role="group" aria-label="Range">
          {RANGES.map((range) => (
            <Button
              key={range.label}
              type="button"
              variant={range.days === rangeDays ? "secondary" : "ghost"}
              size="sm"
              aria-pressed={range.days === rangeDays}
              className="h-7 px-2 text-xs"
              onClick={() => setRangeDays(range.days)}
            >
              {range.label}
            </Button>
          ))}
        </div>
      </div>

      {summary ? (
        <div className="mt-3 flex flex-wrap items-baseline gap-x-4 gap-y-1 text-sm">
          <p className="font-display text-2xl text-foreground">
            {(summary.latestAverageKg ?? summary.latestKg).toFixed(1)} kg
          </p>
          <ChangeLabel changeKg={summary.changeKg} />
          <p className="text-xs text-muted-foreground">
            {summary.count} {summary.count === 1 ? "reading" : "readings"} over {summary.spanDays}{" "}
            {summary.spanDays === 1 ? "day" : "days"}
          </p>
        </div>
      ) : null}

      {hasChart ? (
        // Fixed height: ResponsiveContainer needs a bounded parent, and the card
        // has no intrinsic height of its own.
        <div className="mt-4 h-56 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={points as TrendPoint[]} margin={{ top: 4, right: 8, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" className="stroke-border" vertical={false} />
              <XAxis
                dataKey="day"
                tickFormatter={shortDay}
                tickLine={false}
                axisLine={false}
                minTickGap={28}
                className="text-xs"
                stroke="currentColor"
              />
              <YAxis
                // Weight never approaches zero, so a zero-based axis would flatten
                // every real movement into a straight line.
                domain={["dataMin - 0.5", "dataMax + 0.5"]}
                tickFormatter={(value: number) => value.toFixed(1)}
                tickLine={false}
                axisLine={false}
                width={40}
                className="text-xs"
                stroke="currentColor"
              />
              <Tooltip content={<TrendTooltip />} />

              {/* Raw readings, deliberately understated. */}
              <Scatter
                dataKey="weightKg"
                fill="currentColor"
                className="text-muted-foreground/40"
              />

              {/* The line that answers "which way am I going". connectNulls joins
                  across days whose window was too sparse to average. */}
              <Line
                type="monotone"
                dataKey="averageKg"
                dot={false}
                strokeWidth={2}
                stroke="currentColor"
                className="text-foreground"
                connectNulls
                isAnimationActive={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <p className="mt-3 text-sm text-muted-foreground">
          {points.length === 0
            ? "Nothing recorded in this range yet."
            : "One reading so far — a second gives this something to draw."}
        </p>
      )}
    </section>
  );
}
