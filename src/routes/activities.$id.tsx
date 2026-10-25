import { createFileRoute, Link, notFound } from "@tanstack/react-router";
import { ChevronLeft } from "lucide-react";

import { PageHeader } from "@/components/app-shell";
import {
  garminActivityHeader,
  garminActivitySections,
  type GarminSection,
  garminSplits,
  type SplitRow,
} from "@/lib/health/garmin-activity";
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
import { runWeatherTiles } from "@/lib/health/run-weather";

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

function StatGrid({ label, tiles }: { label: string; tiles: { label: string; value: string }[] }) {
  return (
    <section
      aria-label={label}
      className="grid grid-cols-2 gap-3 rounded-2xl border border-border bg-card p-4 md:grid-cols-4 md:p-5"
    >
      {tiles.map((tile) => (
        <div key={tile.label} className="min-w-0">
          <p className="truncate text-[11px] text-muted-foreground">{tile.label}</p>
          <p className="mt-1 truncate font-display text-xl text-foreground md:text-2xl">
            {tile.value}
          </p>
        </div>
      ))}
    </section>
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

      <StatGrid label="Workout totals" tiles={stats} />

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
  const splits = garminSplits(activity);
  const sections = garminActivitySections(activity);
  const weatherTiles = runWeatherTiles(activity.weather);

  return (
    <>
      <BackToDay day={header.localDay} />
      <PageHeader eyebrow={`${header.dateLabel} · ${header.startTime}`} title={header.title} />

      {weatherTiles.length > 0 && <StatGrid label="Weather" tiles={weatherTiles} />}

      <div className={weatherTiles.length > 0 ? "mt-3" : undefined}>
        <StatGrid label="Activity totals" tiles={header.tiles} />
      </div>

      {splits.length > 0 && <SplitsSection rows={splits} />}

      {sections.map((section) => (
        <MetricSection key={section.title} section={section} />
      ))}
    </>
  );
}

/**
 * Splits as a table with a pace bar per row, so a fade or a fast finish shows
 * as the bars shorten or lengthen. The bar is decoration: the pace is also
 * written out, so nothing depends on seeing it.
 */
function SplitsSection({ rows }: { rows: SplitRow[] }) {
  return (
    <section aria-labelledby="section-splits" className="mt-6">
      <h2 id="section-splits" className="mb-3 font-display text-lg text-foreground">
        Splits
      </h2>
      <div className="rounded-2xl border border-border bg-card px-4 py-1 md:px-5">
        <table className="w-full table-fixed text-sm tabular-nums">
          <thead>
            <tr className="text-left text-[11px] font-normal text-muted-foreground">
              <th scope="col" className="w-10 py-2 font-normal">
                Lap
              </th>
              <th scope="col" className="w-14 py-2 font-normal">
                Time
              </th>
              <th scope="col" className="py-2 font-normal">
                Pace /km
              </th>
              <th scope="col" className="w-10 py-2 text-right font-normal">
                HR
              </th>
              <th scope="col" className="w-16 py-2 text-right font-normal">
                Elev
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {rows.map((row) => (
              <tr key={row.lapNumber}>
                <th scope="row" className="py-2.5 text-left align-top font-medium text-foreground">
                  {row.lapNumber}
                  {row.distanceNote && (
                    <span className="block text-[11px] font-normal text-muted-foreground">
                      {row.distanceNote}
                    </span>
                  )}
                </th>
                <td className="py-2.5 align-top text-foreground">{row.time}</td>
                <td className="py-2.5 align-top">
                  <div className="flex items-center gap-2">
                    <span className="w-9 shrink-0 font-medium text-foreground">{row.pace}</span>
                    <div aria-hidden className="h-2 min-w-0 flex-1">
                      {row.barShare !== null && (
                        <div
                          className="h-full rounded-full bg-primary/70"
                          style={{ width: `${Math.round(row.barShare * 100)}%` }}
                        />
                      )}
                    </div>
                  </div>
                </td>
                <td className="py-2.5 text-right align-top text-foreground">{row.heartRate}</td>
                <td className="py-2.5 text-right align-top text-muted-foreground">
                  {row.elevation}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function MetricSection({ section }: { section: GarminSection }) {
  const headingId = `section-${section.title.toLowerCase().replaceAll(" ", "-")}`;
  return (
    <section aria-labelledby={headingId} className="mt-6">
      <h2 id={headingId} className="mb-3 font-display text-lg text-foreground">
        {section.title}
      </h2>
      <dl className="divide-y divide-border rounded-2xl border border-border bg-card px-4 md:px-5">
        {section.rows.map((row) => (
          <div key={row.label} className="flex items-baseline justify-between gap-4 py-3">
            <dt className="text-sm text-muted-foreground">{row.label}</dt>
            <dd className="min-w-0 truncate text-sm font-medium tabular-nums text-foreground">
              {row.value}
            </dd>
          </div>
        ))}
      </dl>
    </section>
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
