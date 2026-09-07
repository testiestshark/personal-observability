import { createFileRoute } from "@tanstack/react-router";

import { PageHeader, Placeholder, PlaceholderRow } from "@/components/app-shell";
import {
  getDailyHealth,
  getFitnessActivitiesForDay,
  type FitnessActivity,
} from "@/lib/health/health.functions";
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

  return (
    <>
      <PageHeader
        eyebrow="Today"
        title="A quiet look at your day"
        subtitle="Your signals will appear here once you connect a source."
      />

      <div className="grid gap-4">
        <Placeholder label="Daily state" note="Mood, energy, focus, stress and meaning check-in." />
        <Placeholder label="Movement" note="Garmin activity and weight." />
        <Placeholder label="Making" note="Commits across both GitHub accounts." />
        <Placeholder label="Attention" note="Computer activity and iPhone Screen Time." />

        <section className="rounded-xl border border-border bg-card p-4">
          <h2 className="text-sm font-medium">Snapshot</h2>
          <div className="mt-2">
            <PlaceholderRow label="Steps" value={health?.steps?.toLocaleString("en-GB") ?? "—"} />
            <PlaceholderRow
              label="Active calories"
              value={formatCalories(health?.activeCaloriesKcal)}
            />
            <PlaceholderRow
              label="Total calories"
              value={formatCalories(health?.totalCaloriesKcal)}
            />
            <PlaceholderRow label="Sleep" value={formatSleep(health?.totalSleepSeconds)} />
            <PlaceholderRow
              label="Sleep window"
              value={formatSleepWindow(health?.sleepStartAt, health?.sleepEndAt)}
            />
            <PlaceholderRow
              label="Sleep score"
              value={health?.sleepScore?.toLocaleString("en-GB") ?? "—"}
            />
            <PlaceholderRow
              label="Resting heart rate"
              value={formatHeartRate(health?.restingHeartRateBpm)}
            />
            <PlaceholderRow label="VO₂ max" value={formatVo2Max(health?.vo2Max)} />
            <PlaceholderRow label="Weight" value="—" />
            <PlaceholderRow label="Commits" value="—" />
            <PlaceholderRow label="Screen time" value="—" />
          </div>
        </section>

        <section className="rounded-xl border border-border bg-card p-4">
          <h2 className="text-sm font-medium">Recorded activities</h2>
          <div className="mt-2">
            {activities.length ? (
              activities.map((activity) => (
                <PlaceholderRow
                  key={activity.id}
                  label={activity.name ?? formatActivityType(activity.type)}
                  value={formatActivitySummary(activity)}
                />
              ))
            ) : (
              <PlaceholderRow label="Garmin" value="No activities today" />
            )}
          </div>
        </section>
      </div>
    </>
  );
}

function formatCalories(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${value.toLocaleString("en-GB")} kcal`;
}

function formatSleep(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const totalMinutes = Math.round(value / 60);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return `${hours}h ${minutes}m`;
}

function formatSleepWindow(
  start: string | null | undefined,
  end: string | null | undefined,
): string {
  if (!start || !end) return "—";
  const formatter = new Intl.DateTimeFormat("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Europe/London",
  });
  return `${formatter.format(new Date(start))}–${formatter.format(new Date(end))}`;
}

function formatHeartRate(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${value} bpm`;
}

function formatVo2Max(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : value.toLocaleString("en-GB");
}

function formatActivityType(value: string): string {
  return value.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
}

function formatActivitySummary(activity: FitnessActivity): string {
  const parts: string[] = [];
  if (activity.durationSeconds !== null) {
    parts.push(`${Math.round(activity.durationSeconds / 60)} min`);
  }
  if (activity.distanceMeters !== null && activity.distanceMeters >= 100) {
    parts.push(
      `${(activity.distanceMeters / 1000).toLocaleString("en-GB", {
        maximumFractionDigits: 2,
      })} km`,
    );
  }
  if (activity.caloriesKcal !== null) parts.push(`${activity.caloriesKcal} kcal`);
  if (activity.averageHeartRateBpm !== null) {
    parts.push(`${activity.averageHeartRateBpm} bpm avg`);
  }
  if (activity.totalSets !== null) parts.push(`${activity.totalSets} sets`);
  if (activity.totalReps !== null) parts.push(`${activity.totalReps} reps`);
  return parts.length ? parts.join(" · ") : formatActivityType(activity.type);
}
