import { createFileRoute } from "@tanstack/react-router";

import { PageHeader, Placeholder, PlaceholderRow } from "@/components/app-shell";

export const Route = createFileRoute("/settings")({
  head: () => ({
    meta: [
      { title: "Settings — Personal Observability" },
      {
        name: "description",
        content: "Preferences, privacy choices and data handling for your personal workspace.",
      },
      { property: "og:title", content: "Settings — Personal Observability" },
      {
        property: "og:description",
        content: "Preferences, privacy choices and data handling for your workspace.",
      },
    ],
  }),
  component: Settings,
});

function Settings() {
  return (
    <>
      <PageHeader
        eyebrow="Settings"
        title="How this behaves"
        subtitle="Nothing is configurable yet — placeholders only."
      />

      <div className="grid gap-4">
        <section className="rounded-xl border border-border bg-card p-4">
          <h2 className="text-sm font-medium">Preferences</h2>
          <div className="mt-2">
            <PlaceholderRow label="Display name" value="—" />
            <PlaceholderRow label="Time zone" value="—" />
            <PlaceholderRow label="Week starts on" value="—" />
            <PlaceholderRow label="Units" value="—" />
          </div>
        </section>

        <Placeholder label="Privacy" note="This workspace is private by design." height="h-20" />
        <Placeholder label="Data export" note="Download or delete everything." height="h-20" />
      </div>
    </>
  );
}
