import { createFileRoute, Link, notFound } from "@tanstack/react-router";
import { ChevronLeft } from "lucide-react";

import { PageHeader } from "@/components/app-shell";
import {
  activityIdSchema,
  type FitnessActivityDetail,
  getFitnessActivity,
} from "@/lib/health/health.functions";
import { activityDetailKind, workoutHeader } from "@/lib/health/workout";

export const Route = createFileRoute("/activities/$id")({
  head: () => ({
    meta: [{ title: "Workout — Personal Observability" }],
  }),
  loader: async ({ params }) => {
    // A malformed id can never match a row; answer it as not found rather than
    // letting the server function's validation surface as an error page.
    if (!activityIdSchema.safeParse(params.id).success) throw notFound();
    const activity = await getFitnessActivity({ data: { id: params.id } });
    // RLS hides another account's rows, so "not yours" and "not there" are the
    // same answer, by design.
    if (!activity) throw notFound();
    return { activity };
  },
  component: ActivityDetail,
});

function ActivityDetail() {
  const { activity } = Route.useLoaderData();

  return activityDetailKind(activity) === "hevy-strength" ? (
    <HevyWorkout activity={activity} />
  ) : (
    <UnsupportedActivity activity={activity} />
  );
}

function BackToDay({ day }: { day: string }) {
  return (
    <Link
      to="/"
      search={{ day }}
      className="mb-5 inline-flex items-center gap-1 text-sm text-muted-foreground transition-colors hover:text-foreground"
    >
      <ChevronLeft className="h-4 w-4" />
      Back to day
    </Link>
  );
}

function HevyWorkout({ activity }: { activity: FitnessActivityDetail }) {
  const header = workoutHeader(activity);
  const stats = [
    { label: "Duration", value: header.duration },
    { label: "Active sets", value: header.activeSets },
    { label: "Total reps", value: header.totalReps },
    { label: "Volume", value: header.volume },
  ];

  return (
    <>
      <BackToDay day={header.localDay} />
      <PageHeader eyebrow={`${header.dateLabel} · ${header.startTime}`} title={header.title} />

      <section
        aria-label="Workout totals"
        className="grid grid-cols-2 gap-3 rounded-2xl border border-border bg-card p-4 md:grid-cols-4 md:p-5"
      >
        {stats.map((stat) => (
          <div key={stat.label} className="min-w-0">
            <p className="truncate text-[11px] text-muted-foreground">{stat.label}</p>
            <p className="mt-1 truncate font-display text-xl text-foreground md:text-2xl">
              {stat.value}
            </p>
          </div>
        ))}
      </section>
    </>
  );
}

function UnsupportedActivity({ activity }: { activity: FitnessActivityDetail }) {
  return (
    <>
      <BackToDay day={activity.localDay} />
      <div className="rounded-xl border border-dashed border-border bg-muted/30 px-4 py-8 text-center text-xs text-muted-foreground">
        No detail view for this kind of activity yet
      </div>
    </>
  );
}
