import { createFileRoute } from "@tanstack/react-router";

import { PageHeader, Placeholder } from "@/components/app-shell";

export const Route = createFileRoute("/timeline")({
  head: () => ({
    meta: [
      { title: "Timeline — Personal Observability" },
      {
        name: "description",
        content: "A chronological record of activity, health and reflection over time.",
      },
      { property: "og:title", content: "Timeline — Personal Observability" },
      {
        property: "og:description",
        content: "A chronological record of activity, health and reflection over time.",
      },
    ],
  }),
  component: Timeline,
});

function Timeline() {
  return (
    <>
      <PageHeader
        eyebrow="Timeline"
        title="Your days, in order"
        subtitle="Day-by-day history will build up here."
      />

      <div className="grid gap-4">
        <Placeholder label="Range selector" note="Week, month and year views." height="h-14" />
        <Placeholder label="Daily entries" note="One row per day with key signals." height="h-48" />
        <Placeholder label="Trend strip" note="Steps, weight and focus over time." height="h-32" />
      </div>
    </>
  );
}
