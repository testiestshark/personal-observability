import { createFileRoute } from "@tanstack/react-router";
import { Activity, Clock3, Flame, Footprints, HeartPulse, Moon, Sparkles } from "lucide-react";
import type { ComponentType } from "react";

import { PageHeader, Placeholder } from "@/components/app-shell";
import {
  formatActivitySummary,
  formatActivityTime,
  formatActivityType,
  formatCalories,
  formatHeartRate,
  formatSleep,
  formatSleepWindow,
  formatSyncTime,
  formatVo2Max,
} from "@/lib/health/format";
import { getDailyHealth, getFitnessActivitiesForDay } from "@/lib/health/health.functions";
import { currentLondonDay } from "@/lib/weight/units";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Today — Personal Observability" },
      {
        name: "description",
        content:
          "A private daily view of your activity, health, focus and reflections in one calm place.",
      },
      { property: "og:title", content: "Today — Personal Observability" },
      {
        property: "og:description",
        content: "A private daily view of your activity, health, focus and reflections.",
      },
    ],
  }),
  loader: async () => {
    const day = currentLondonDay();
    const [health, activities] = await Promise.all([
      getDailyHealth({ data: { day } }),
      getFitnessActivitiesForDay({ data: { day } }),
    ]);
    return { health, activities };
  },
  component: Today,
});

function Today() {
  const { health, activities } = Route.useLoaderData();
  const syncLabel = formatSyncTime(health?.sourceSyncedAt ?? health?.syncedAt);
  const metrics = [
    {
      label: "Steps",
      value: health?.steps?.toLocaleString("en-GB") ?? "—",
      note: "Today",
      icon: Footprints,
    },
    {
      label: "Active calories",
      value: formatCalories(health?.activeCaloriesKcal),
      note: "Movement energy",
      icon: Flame,
    },
    {
      label: "Total calories",
      value: formatCalories(health?.totalCaloriesKcal),
      note: "Including resting energy",
      icon: Sparkles,
    },
    {
      label: "Total sleep",
      value: formatSleep(health?.totalSleepSeconds),
      note: formatSleepWindow(health?.sleepStartAt, health?.sleepEndAt),
      icon: Moon,
    },
    {
      label: "Sleep score",
      value: health?.sleepScore?.toLocaleString("en-GB") ?? "—",
      note: "Out of 100",
      icon: Moon,
    },
    {
      label: "Resting heart rate",
      value: formatHeartRate(health?.restingHeartRateBpm),
      note: "Daily resting value",
      icon: HeartPulse,
    },
    {
      label: "VO₂ max",
      value: formatVo2Max(health?.vo2Max),
      note: "Cardio fitness estimate",
      icon: Activity,
    },
  ];

  return (
    <>
      <PageHeader
        eyebrow="Today"
        title="Your day at a glance"
        subtitle="Health and activity from Garmin Connect, refreshed automatically."
      />

      <div className="grid gap-5">
        <section className="rounded-2xl border border-border bg-card p-4 md:p-5">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <p className="text-[11px] tracking-[0.16em] uppercase text-muted-foreground">
                Garmin health
              </p>
              <h2 className="mt-1 font-display text-xl text-foreground">Daily signals</h2>
            </div>
            {syncLabel ? (
              <span className="rounded-full bg-muted px-2.5 py-1 text-[11px] text-muted-foreground">
                {syncLabel}
              </span>
            ) : null}
          </div>

          {health ? (
            <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-3">
              {metrics.map((metric) => (
                <MetricCard key={metric.label} {...metric} />
              ))}
            </div>
          ) : (
            <EmptyState>No Garmin health data has arrived for today yet.</EmptyState>
          )}
        </section>

        <section className="rounded-2xl border border-border bg-card p-4 md:p-5">
          <div>
            <p className="text-[11px] tracking-[0.16em] uppercase text-muted-foreground">
              Garmin activities
            </p>
            <h2 className="mt-1 font-display text-xl text-foreground">Recorded today</h2>
          </div>

          {activities.length ? (
            <div className="mt-4 grid gap-3">
              {activities.map((activity) => (
                <article
                  key={activity.id}
                  className="rounded-xl border border-border bg-background/40 p-4"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0">
                      <h3 className="truncate text-sm font-medium text-foreground">
                        {activity.name ?? formatActivityType(activity.type)}
                      </h3>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {formatActivitySummary(activity)}
                      </p>
                    </div>
                    <span className="flex shrink-0 items-center gap-1.5 rounded-full bg-muted px-2.5 py-1 text-[11px] text-muted-foreground">
                      <Clock3 className="h-3 w-3" />
                      {formatActivityTime(activity.startedAt)}
                    </span>
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <EmptyState>No recorded Garmin activities today.</EmptyState>
          )}
        </section>

        <Placeholder label="Daily state" note="Mood, energy, focus, stress and meaning check-in." />
        <Placeholder label="Making" note="Commits across both GitHub accounts." />
        <Placeholder label="Attention" note="Computer activity and iPhone Screen Time." />
      </div>
    </>
  );
}

function MetricCard({
  label,
  value,
  note,
  icon: Icon,
}: {
  label: string;
  value: string;
  note: string;
  icon: ComponentType<{ className?: string; strokeWidth?: number }>;
}) {
  return (
    <article className="min-w-0 rounded-xl border border-border bg-background/40 p-3.5">
      <div className="flex items-center gap-2 text-muted-foreground">
        <Icon className="h-4 w-4 shrink-0" strokeWidth={1.75} />
        <span className="truncate text-[11px]">{label}</span>
      </div>
      <p className="mt-3 truncate font-display text-xl text-foreground md:text-2xl">{value}</p>
      <p className="mt-1 truncate text-[10px] text-muted-foreground">{note}</p>
    </article>
  );
}

function EmptyState({ children }: { children: string }) {
  return (
    <div className="mt-4 rounded-xl border border-dashed border-border bg-muted/30 px-4 py-8 text-center text-xs text-muted-foreground">
      {children}
    </div>
  );
}
