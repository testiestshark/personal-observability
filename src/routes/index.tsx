import { createFileRoute } from "@tanstack/react-router";

import { PageHeader, Placeholder, PlaceholderRow } from "@/components/app-shell";
import { getDailySteps } from "@/lib/health/health.functions";
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
    return { steps: await getDailySteps({ data: { day } }) };
  },
  component: Today,
});

function Today() {
  const { steps } = Route.useLoaderData();

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
            <PlaceholderRow
              label="Steps"
              value={steps ? steps.steps.toLocaleString("en-GB") : "—"}
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
