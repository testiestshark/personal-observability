import { createFileRoute } from "@tanstack/react-router";

import { PageHeader, Placeholder } from "@/components/app-shell";

export const Route = createFileRoute("/insights")({
  head: () => ({
    meta: [
      { title: "Insights — Personal Observability" },
      {
        name: "description",
        content: "Patterns and correlations between your habits, health and state of mind.",
      },
      { property: "og:title", content: "Insights — Personal Observability" },
      {
        property: "og:description",
        content: "Patterns and correlations between your habits, health and state of mind.",
      },
    ],
  }),
  component: Insights,
});

function Insights() {
  return (
    <>
      <PageHeader
        eyebrow="Insights"
        title="What the patterns suggest"
        subtitle="Summaries will appear once enough history exists."
      />

      <div className="grid gap-4">
        <Placeholder label="Correlations" note="Sleep, movement, focus and mood." height="h-40" />
        <Placeholder label="Streaks & rhythms" note="Recurring weekly patterns." height="h-24" />
        <Placeholder
          label="Notable shifts"
          note="Changes worth paying attention to."
          height="h-24"
        />
      </div>
    </>
  );
}
