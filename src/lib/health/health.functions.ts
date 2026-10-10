import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";

export const activityIdSchema = z.string().uuid();

const daySchema = z.string().regex(/^\d{4}-(0[1-9]|1[0-2])-([12]\d|3[01]|0[1-9])$/);

export type DailyHealth = {
  day: string;
  steps: number | null;
  activeCaloriesKcal: number | null;
  totalCaloriesKcal: number | null;
  consumedCaloriesKcal: number | null;
  calorieGoalKcal: number | null;
  sleepStartAt: string | null;
  sleepEndAt: string | null;
  totalSleepSeconds: number | null;
  restingHeartRateBpm: number | null;
  vo2Max: number | null;
  sourceSyncedAt: string | null;
  syncedAt: string;
};

export type FitnessActivity = {
  id: string;
  source: "garmin" | "hevy";
  name: string | null;
  type: string;
  startedAt: string;
  durationSeconds: number | null;
  distanceMeters: number | null;
  caloriesKcal: number | null;
  averageHeartRateBpm: number | null;
  totalSets: number | null;
  totalReps: number | null;
};

/** One set of an exercise. Hevy stores weights in kilograms and distances in metres. */
export type FitnessSet = {
  id: string;
  position: number;
  type: string;
  weightKg: number | null;
  reps: number | null;
  rpe: number | null;
  distanceMeters: number | null;
  durationSeconds: number | null;
  customMetric: number | null;
};

/** One exercise within a workout, with its sets nested. */
export type FitnessExercise = {
  id: string;
  position: number;
  title: string | null;
  notes: string | null;
  supersetId: number | null;
  sets: FitnessSet[];
};

/**
 * One activity for its detail page: the day-view fields plus what the header
 * needs, and its exercises (ordered by position) with their sets nested.
 */
export type FitnessActivityDetail = FitnessActivity & {
  localDay: string;
  activeSets: number | null;
  totalVolumeKg: number | null;
  exercises: FitnessExercise[];
};

async function requireUser() {
  // Server functions ship browser RPC stubs, so the server-only client must be
  // imported inside the handler path rather than at module scope.
  const { createSupabaseRequestClient } = await import("@/lib/auth/supabase-request.server");
  const supabase = createSupabaseRequestClient();
  const { data, error } = await supabase.auth.getUser();
  if (error || !data.user) throw new Error("Not signed in.");
  return { supabase, userId: data.user.id };
}

type FitnessActivityRow = {
  id: string;
  source: string;
  activity_name: string | null;
  activity_type: string;
  started_at: string;
  duration_seconds: number | null;
  distance_meters: number | null;
  calories_kcal: number | null;
  average_heart_rate_bpm: number | null;
  total_sets: number | null;
  total_reps: number | null;
};

/** The day-view fields of a `fitness_activities` row; the detail query adds its own on top. */
function toFitnessActivity(row: FitnessActivityRow): FitnessActivity {
  return {
    id: row.id,
    // `fitness_activities_source_known` limits the column to these two values.
    source: row.source as FitnessActivity["source"],
    name: row.activity_name,
    type: row.activity_type,
    startedAt: row.started_at,
    durationSeconds: row.duration_seconds,
    distanceMeters: row.distance_meters,
    caloriesKcal: row.calories_kcal,
    averageHeartRateBpm: row.average_heart_rate_bpm,
    totalSets: row.total_sets,
    totalReps: row.total_reps,
  };
}

export const getDailyHealth = createServerFn({ method: "GET" })
  .validator((data: { day: string }) => ({ day: daySchema.parse(data.day) }))
  .handler(async ({ data }): Promise<DailyHealth | null> => {
    const { supabase, userId } = await requireUser();
    const { data: row, error } = await supabase
      .from("daily_health_metrics")
      .select(
        "day, steps, active_calories_kcal, total_calories_kcal, consumed_calories_kcal, calorie_goal_kcal, sleep_start_at, sleep_end_at, total_sleep_seconds, resting_heart_rate_bpm, vo2_max, source_synced_at, synced_at",
      )
      .eq("user_id", userId)
      .eq("day", data.day)
      .eq("source", "garmin")
      .maybeSingle();

    if (error) throw new Error(error.message);
    if (!row) return null;

    return {
      day: row.day,
      steps: row.steps,
      activeCaloriesKcal: row.active_calories_kcal,
      totalCaloriesKcal: row.total_calories_kcal,
      consumedCaloriesKcal: row.consumed_calories_kcal,
      calorieGoalKcal: row.calorie_goal_kcal,
      sleepStartAt: row.sleep_start_at,
      sleepEndAt: row.sleep_end_at,
      totalSleepSeconds: row.total_sleep_seconds,
      restingHeartRateBpm: row.resting_heart_rate_bpm,
      vo2Max: row.vo2_max,
      sourceSyncedAt: row.source_synced_at,
      syncedAt: row.synced_at,
    };
  });

export const getFitnessActivitiesForDay = createServerFn({ method: "GET" })
  .validator((data: { day: string }) => ({ day: daySchema.parse(data.day) }))
  .handler(async ({ data }): Promise<FitnessActivity[]> => {
    const { supabase, userId } = await requireUser();
    const { data: rows, error } = await supabase
      .from("fitness_activities")
      .select(
        "id, source, activity_name, activity_type, started_at, duration_seconds, distance_meters, calories_kcal, average_heart_rate_bpm, total_sets, total_reps",
      )
      .eq("user_id", userId)
      .eq("local_day", data.day)
      .order("started_at", { ascending: false });

    if (error) throw new Error(error.message);
    return (rows ?? []).map(toFitnessActivity);
  });

export const getFitnessActivity = createServerFn({ method: "GET" })
  .validator((data: { id: string }) => ({ id: activityIdSchema.parse(data.id) }))
  .handler(async ({ data }): Promise<FitnessActivityDetail | null> => {
    const { supabase, userId } = await requireUser();
    const { data: row, error } = await supabase
      .from("fitness_activities")
      .select(
        `id, source, activity_name, activity_type, local_day, started_at, duration_seconds, distance_meters, calories_kcal, average_heart_rate_bpm, total_sets, active_sets, total_reps, total_volume_kg,
        fitness_exercises (
          id, position, title, notes, superset_id,
          fitness_sets (id, position, type, weight_kg, reps, rpe, distance_meters, duration_seconds, custom_metric)
        )`,
      )
      .eq("user_id", userId)
      .eq("id", data.id)
      .order("position", { referencedTable: "fitness_exercises", ascending: true })
      .order("position", { referencedTable: "fitness_exercises.fitness_sets", ascending: true })
      .maybeSingle();

    if (error) throw new Error(error.message);
    if (!row) return null;

    return {
      ...toFitnessActivity(row),
      localDay: row.local_day,
      activeSets: row.active_sets,
      totalVolumeKg: row.total_volume_kg,
      exercises: row.fitness_exercises.map((exercise) => ({
        id: exercise.id,
        position: exercise.position,
        title: exercise.title,
        notes: exercise.notes,
        supersetId: exercise.superset_id,
        sets: exercise.fitness_sets.map((set) => ({
          id: set.id,
          position: set.position,
          type: set.type,
          weightKg: set.weight_kg,
          reps: set.reps,
          rpe: set.rpe,
          distanceMeters: set.distance_meters,
          durationSeconds: set.duration_seconds,
          customMetric: set.custom_metric,
        })),
      })),
    };
  });

export const getGarminSyncStatus = createServerFn({ method: "GET" }).handler(
  async (): Promise<{ lastSyncedAt: string; latestDay: string } | null> => {
    const { supabase, userId } = await requireUser();
    const { data: row, error } = await supabase
      .from("daily_health_metrics")
      .select("day, synced_at")
      .eq("user_id", userId)
      .eq("source", "garmin")
      .order("synced_at", { ascending: false })
      .limit(1)
      .maybeSingle();

    if (error) throw new Error(error.message);
    return row ? { latestDay: row.day, lastSyncedAt: row.synced_at } : null;
  },
);

export const getHevySyncStatus = createServerFn({ method: "GET" }).handler(
  async (): Promise<{ lastSyncedAt: string } | null> => {
    const { supabase, userId } = await requireUser();
    const { data: row, error } = await supabase
      .from("sync_runs")
      .select("last_succeeded_at")
      .eq("user_id", userId)
      .eq("source", "hevy")
      .maybeSingle();

    if (error) throw new Error(error.message);
    return row ? { lastSyncedAt: row.last_succeeded_at } : null;
  },
);
