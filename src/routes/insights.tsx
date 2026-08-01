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
  component: Insights;
});

function Insights() {
  return null;
}
