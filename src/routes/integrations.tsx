import { createFileRoute } from "@tanstack/react-router";

import { PageHeader, Placeholder, PlaceholderRow } from "@/components/app-shell";
import { getGarminSyncStatus } from "@/lib/health/health.functions";

export const Route = createFileRoute("/integrations")({
  head: () => ({
    meta: [
      { title: "Sources — Personal Observability" },
      {
        name: "description",
        content: "Manage the data sources that will feed your private observability workspace.",
      },
      { property: "og:title", content: "Sources — Personal Observability" },
      {
        property: "og:description",
        content: "Manage the data sources that will feed your private workspace.",
      },
    ],
  }),
  loader: async () => ({ garmin: await getGarminSyncStatus() }),
  component: Integrations,
});

function Integrations() {
  const { garmin } = Route.useLoaderData();

  return (
    <>
      <PageHeader
        eyebrow="Sources"
        title="Where the data comes from"
        subtitle="Local integrations feed your private observability database."
      />

      <div className="grid gap-4">
        <section className="rounded-xl border border-border bg-card p-4">
          <h2 className="text-sm font-medium">Planned sources</h2>
          <div className="mt-2">
            <PlaceholderRow label="GitHub — account one" value="Not connected" />
            <PlaceholderRow label="GitHub — account two" value="Not connected" />
            <PlaceholderRow label="Strava" value="Not connected" />
            <PlaceholderRow
              label="Garmin daily steps"
              value={
                garmin ? `Last synced ${formatSyncTime(garmin.lastSyncedAt)}` : "Setup required"
              }
            />
            <PlaceholderRow label="Weight" value="Manual entry" />
            <PlaceholderRow label="Computer activity" value="Not connected" />
            <PlaceholderRow label="iPhone Screen Time" value="Manual entry" />
          </div>
        </section>

        <Placeholder
          label="Garmin sync"
          note={
            garmin
              ? `Automatic local sync is active; latest Garmin day is ${garmin.latestDay}.`
              : "Run the one-time Garmin setup, then install the hourly scheduled task."
          }
          height="h-20"
        />
        <Placeholder label="Manual entry forms" note="Screen time." height="h-24" />
      </div>
    </>
  );
}

function formatSyncTime(value: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Europe/London",
  }).format(new Date(value));
}
