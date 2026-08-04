import { createFileRoute } from "@tanstack/react-router";

import { PageHeader, Placeholder, PlaceholderRow } from "@/components/app-shell";


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
  component: Integrations,
});

function Integrations() {
  return (
    <>
      <PageHeader
        eyebrow="Sources"
        title="Where the data comes from"
        subtitle="Connections are not wired up yet — this is the shell only."
      />

      <div className="grid gap-4">
        <section className="rounded-xl border border-border bg-card p-4">
          <h2 className="text-sm font-medium">Planned sources</h2>
          <div className="mt-2">
            <PlaceholderRow label="GitHub — account one" value="Not connected" />
            <PlaceholderRow label="GitHub — account two" value="Not connected" />
            <PlaceholderRow label="Strava" value="Not connected" />
            <PlaceholderRow label="Daily steps" value="Not connected" />
            <PlaceholderRow label="Weight" value="Manual entry" />
            <PlaceholderRow label="Computer activity" value="Not connected" />
            <PlaceholderRow label="iPhone Screen Time" value="Manual entry" />
          </div>
        </section>

        <Placeholder label="Sync status" note="Last sync times and errors." height="h-20" />
        <Placeholder label="Manual entry forms" note="Steps and screen time." height="h-24" />
      </div>
    </>
  );
}
