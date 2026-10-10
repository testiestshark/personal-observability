import { createFileRoute, Link, notFound } from "@tanstack/react-router";
import { ChevronLeft } from "lucide-react";

import { PageHeader } from "@/components/app-shell";
import { garminActivityHeader } from "@/lib/health/garmin-activity";
import {
  activityIdSchema,
  type FitnessActivityDetail,
  type GarminActivityDetail,
  getFitnessActivity,
  type HevyActivityDetail,
} from "@/lib/health/health.functions";
import {
  activityDetailKind,
  groupSupersets,
  type WorkoutExercise,
  workoutExercises,
  workoutHeader,
} from "@/lib/health/workout";

/**
 * The left rule's colour for each superset colour index: one class per colour
 * (SUPERSET_COLOUR_COUNT), written out in full so Tailwind sees every class.
 * chart-2 to chart-5, not chart-1: in the dark theme chart-1 is a deep blue that
 * barely separates from the card.
 */
const SUPERSET_RULE_CLASSES: readonly string[] = [
  "border-chart-2",
  "border-chart-3",
  "border-chart-4",
  "border-chart-5",
];

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

  // The kind is the same rule the day view links by. The source check only
  // narrows the type: the lookup shapes the row by source.
  const kind = activityDetailKind(activity);
  if (kind === "hevy-strength" && activity.source === "hevy") {
    return <HevyWorkout activity={activity} />;
  }
  if (kind === "garmin-activity" && activity.source === "garmin") {
    return <GarminActivity activity={activity} />;
  }
  return <UnsupportedActivity activity={activity} />;
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

function HevyWorkout({ activity }: { activity: HevyActivityDetail }) {
  const header = workoutHeader(activity);
  const blocks = groupSupersets(workoutExercises(activity.exercises));
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

      <section aria-labelledby="exercises-heading" className="mt-6">
        <h2 id="exercises-heading" className="mb-3 font-display text-lg text-foreground">
          Exercises
        </h2>
        {blocks.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border bg-muted/30 px-4 py-8 text-center text-xs text-muted-foreground">
            No exercises recorded for this workout
          </div>
        ) : (
          <ol className="space-y-3">
            {blocks.map((block) =>
              block.kind === "single" ? (
                <li key={block.exercise.id}>
                  <ExerciseCard exercise={block.exercise} />
                </li>
              ) : (
                <li
                  key={block.label}
                  className={`border-l-4 pl-3 ${SUPERSET_RULE_CLASSES[block.colour]}`}
                >
                  <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    {block.label}
                  </p>
                  <ol aria-label={`${block.label} exercises`} className="space-y-3">
                    {block.exercises.map((exercise) => (
                      <li key={exercise.id}>
                        <ExerciseCard exercise={exercise} />
                      </li>
                    ))}
                  </ol>
                </li>
              ),
            )}
          </ol>
        )}
      </section>
    </>
  );
}

function GarminActivity({ activity }: { activity: GarminActivityDetail }) {
  const header = garminActivityHeader(activity);

  return (
    <>
      <BackToDay day={header.localDay} />
      <PageHeader eyebrow={`${header.dateLabel} · ${header.startTime}`} title={header.title} />

      <section
        aria-label="Activity totals"
        className="grid grid-cols-2 gap-3 rounded-2xl border border-border bg-card p-4 md:grid-cols-4 md:p-5"
      >
        {header.tiles.map((tile) => (
          <div key={tile.label} className="min-w-0">
            <p className="truncate text-[11px] text-muted-foreground">{tile.label}</p>
            <p className="mt-1 truncate font-display text-xl text-foreground md:text-2xl">
              {tile.value}
            </p>
          </div>
        ))}
      </section>
    </>
  );
}

function ExerciseCard({ exercise }: { exercise: WorkoutExercise }) {
  return (
    <div className="rounded-2xl border border-border bg-card p-4 md:p-5">
      <h3 className="text-sm font-medium text-foreground">{exercise.title}</h3>
      {exercise.notes && (
        <p className="mt-1 whitespace-pre-line text-xs text-muted-foreground">{exercise.notes}</p>
      )}
      {exercise.sets.length > 0 && (
        <ol aria-label={`${exercise.title} sets`} className="mt-3 space-y-1.5">
          {exercise.sets.map((set) => (
            <li key={set.id} className="flex items-baseline gap-3 text-sm">
              <span
                className={`w-6 shrink-0 text-center text-xs font-medium tabular-nums ${
                  set.marker ? "text-primary" : "text-muted-foreground"
                }`}
              >
                {set.label}
              </span>
              <span className="min-w-0 text-foreground">
                {set.measurements.length > 0 ? set.measurements.join(" · ") : "—"}
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
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
