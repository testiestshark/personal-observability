import { createFileRoute } from "@tanstack/react-router";

import { PageHeader, Placeholder, PlaceholderRow } from "@/components/app-shell";
import { getDailyHealth } from "@/lib/health/health.functions";
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
    return { health: await getDailyHealth({ data: { day } }) };
  },
  component: Today,
});

function Today() {
  const { health } = Route.useLoaderData();

  return (
    <>
      <PageHeader
        eyebrow="Today"
        title="A quiet look at your day"
        subtitle="Your signals will appear here once you connect a source."
      />

      <div className="grid gap-4">
        <Placeholder label="Daily state" note="Mood, energy, focus, stress and meaning check-in." />
        <Placeholder label="Movement" note="Steps, Strava activity and weight." />
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
            <PlaceholderRow label="Weight" value="—" />
            <PlaceholderRow label="Commits" value="—" />
            <PlaceholderRow label="Screen time" value="—" />
          </div>
        </section>
      </div>
    </>
  );
}

function formatCalories(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${value.toLocaleString("en-GB")} kcal`;
}
