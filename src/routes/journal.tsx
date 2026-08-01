import { createFileRoute } from "@tanstack/react-router";

import { PageHeader, Placeholder } from "@/components/app-shell";

export const Route = createFileRoute("/journal")({
  head: () => ({
    meta: [
      { title: "Journal — Personal Observability" },
      {
        name: "description",
        content: "Private journal entries, daily reflections and weekly personal reviews.",
      },
      { property: "og:title", content: "Journal — Personal Observability" },
      {
        property: "og:description",
        content: "Private journal entries, daily reflections and weekly reviews.",
      },
    ],
  }),
  component: Journal,
});

function Journal() {
  return (
    <>
      <PageHeader
        eyebrow="Journal"
        title="Words for yourself"
        subtitle="Entries, reflections and weekly reviews will live here."
      />

      <div className="grid gap-4">
        <Placeholder label="New entry" note="Free-form writing area." height="h-32" />
        <Placeholder label="Daily reflection" note="Short prompted check-in." height="h-24" />
        <Placeholder label="Weekly review" note="Looking back across seven days." height="h-24" />
        <Placeholder label="Past entries" note="Searchable archive." height="h-40" />
      </div>
    </>
  );
}
