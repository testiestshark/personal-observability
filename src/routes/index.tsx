import { createFileRoute, Link } from "@tanstack/react-router";
import {
  Activity,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Flame,
  Footprints,
  HeartPulse,
  Moon,
  Scale,
  Sparkles,
  Utensils,
} from "lucide-react";
import type { ComponentType, ReactNode } from "react";
import { z } from "zod";

import { PageHeader } from "@/components/app-shell";
import {
  caloriesEatenNote,
  energyBalance,
  energyBalanceNote,
  formatActivitySummary,
  formatActivityTime,
  formatActivityType,
  formatCalories,
  formatHeartRate,
  formatSleep,
  formatSleepWindow,
  formatSyncTime,
  formatVo2Max,
  goalProgress,
  isCompleteDay,
} from "@/lib/health/format";
import {
  type DailyHealth,
  getDailyHealth,
  getFitnessActivitiesForDay,
} from "@/lib/health/health.functions";
import { currentLondonDay, formatDayLabel, shiftDay } from "@/lib/weight/units";

const daySchema = z.string().regex(/^\d{4}-(0[1-9]|1[0-2])-([12]\d|3[01]|0[1-9])$/);

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
  validateSearch: z.object({
    day: daySchema.optional(),
  }).parse,
  loaderDeps: ({ search: { day } }) => ({ day: day ?? currentLondonDay() }),
  loader: async ({ deps: { day } }) => {
    const [health, activities] = await Promise.all([
      getDailyHealth({ data: { day } }),
      getFitnessActivitiesForDay({ data: { day } }),
    ]);
    return { day, health, activities };
  },
  component: Today,
});

function Today() {
  const { health, activities, day: viewedDay } = Route.useLoaderData();
  const today = currentLondonDay();
  const isToday = viewedDay === today;
  const syncLabel = formatSyncTime(health?.sourceSyncedAt ?? health?.syncedAt);
  const metrics = [
    {
      label: "Steps",
      value: health?.steps?.toLocaleString("en-GB") ?? "—",
      note: isToday ? "Today" : formatDayLabel(viewedDay),
      icon: Footprints,
    },
    {
      label: "Total sleep",
      value: formatSleep(health?.totalSleepSeconds),
      note: formatSleepWindow(health?.sleepStartAt, health?.sleepEndAt),
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
        eyebrow={isToday ? "Today" : formatDayLabel(viewedDay)}
        title="Your day at a glance"
        subtitle="Health and activity from Garmin Connect, refreshed automatically."
      />

      <DayNavigator day={viewedDay} isToday={isToday} />

      <div className="grid gap-5">
        <section className="rounded-2xl border border-border bg-card p-4 md:p-5">
          <div>
            <p className="text-[11px] tracking-[0.16em] uppercase text-muted-foreground">
              Garmin + MyFitnessPal
            </p>
            <h2 className="mt-1 font-display text-xl text-foreground">Energy</h2>
          </div>

          {health ? (
            <EnergyTiles health={health} day={viewedDay} today={today} />
          ) : (
            <EmptyState>No Garmin health data has arrived for this day yet.</EmptyState>
          )}
        </section>

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
            <EmptyState>No Garmin health data has arrived for this day yet.</EmptyState>
          )}
        </section>

        <section className="rounded-2xl border border-border bg-card p-4 md:p-5">
          <div>
            <p className="text-[11px] tracking-[0.16em] uppercase text-muted-foreground">
              Garmin activities
            </p>
            <h2 className="mt-1 font-display text-xl text-foreground">Recorded on this day</h2>
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
            <EmptyState>No recorded Garmin activities on this day.</EmptyState>
          )}
        </section>
      </div>
    </>
  );
}

function EnergyTiles({ health, day, today }: { health: DailyHealth; day: string; today: string }) {
  const eaten = health.consumedCaloriesKcal;
  const total = health.totalCaloriesKcal;
  const complete = isCompleteDay(day, today, health.sourceSyncedAt);
  const progress = goalProgress(eaten, health.calorieGoalKcal);

  return (
    <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
      <MetricCard
        label="Calories eaten"
        value={formatCalories(eaten)}
        note={caloriesEatenNote(eaten, health.calorieGoalKcal, day, today)}
        icon={Utensils}
      >
        {progress !== null ? (
          <div
            role="progressbar"
            aria-label="Calories eaten against goal"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(progress * 100)}
            className="mt-2 h-1 overflow-hidden rounded-full bg-muted"
          >
            <div
              className="h-full rounded-full bg-primary"
              style={{ width: `${progress * 100}%` }}
            />
          </div>
        ) : null}
      </MetricCard>
      <MetricCard
        label="Total calories"
        value={formatCalories(total)}
        note="Garmin estimate"
        icon={Sparkles}
      />
      <MetricCard
        label="Active calories"
        value={formatCalories(health.activeCaloriesKcal)}
        note="Movement energy"
        icon={Flame}
      />
      <MetricCard
        label="Energy balance"
        value={formatCalories(energyBalance(eaten, total, complete))}
        note={energyBalanceNote(complete, eaten, total)}
        icon={Scale}
      />
    </div>
  );
}

function DayNavigator({ day, isToday }: { day: string; isToday: boolean }) {
  const previousDay = shiftDay(day, -1);
  const nextDay = shiftDay(day, 1);

  return (
    <div className="mb-5 flex items-center justify-between rounded-xl border border-border bg-card p-2">
      <Link
        to="/"
        search={{ day: previousDay }}
        aria-label="Previous day"
        className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
      >
        <ChevronLeft className="h-5 w-5" />
      </Link>
      <span className="text-sm font-medium text-foreground">
        {isToday ? "Today" : formatDayLabel(day)}
      </span>
      {isToday ? (
        <span
          aria-label="Next day"
          className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-muted-foreground opacity-40"
        >
          <ChevronRight className="h-5 w-5" />
        </span>
      ) : (
        <Link
          to="/"
          search={{ day: nextDay }}
          aria-label="Next day"
          className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
        >
          <ChevronRight className="h-5 w-5" />
        </Link>
      )}
    </div>
  );
}

function MetricCard({
  label,
  value,
  note,
  icon: Icon,
  children,
}: {
  label: string;
  value: string;
  note?: string | undefined;
  icon: ComponentType<{ className?: string; strokeWidth?: number }>;
  children?: ReactNode;
}) {
  return (
    <article className="min-w-0 rounded-xl border border-border bg-background/40 p-3.5">
      <div className="flex items-center gap-2 text-muted-foreground">
        <Icon className="h-4 w-4 shrink-0" strokeWidth={1.75} />
        <span className="truncate text-[11px]">{label}</span>
      </div>
      <p className="mt-3 truncate font-display text-xl text-foreground md:text-2xl">{value}</p>
      {children}
      {note ? <p className="mt-1 truncate text-[10px] text-muted-foreground">{note}</p> : null}
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
