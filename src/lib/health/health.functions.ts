import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";

const daySchema = z.string().regex(/^\d{4}-(0[1-9]|1[0-2])-([12]\d|3[01]|0[1-9])$/);

export type DailyHealth = {
  day: string;
  steps: number | null;
  activeCaloriesKcal: number | null;
  totalCaloriesKcal: number | null;
  sleepStartAt: string | null;
  sleepEndAt: string | null;
  totalSleepSeconds: number | null;
  sleepScore: number | null;
  restingHeartRateBpm: number | null;
  vo2Max: number | null;
  sourceSyncedAt: string | null;
  syncedAt: string;
};

export type FitnessActivity = {
  id: string;
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

async function requireUser() {
  // Server functions ship browser RPC stubs, so the server-only client must be
  // imported inside the handler path rather than at module scope.
  const { createSupabaseRequestClient } = await import("@/lib/auth/supabase-request.server");
  const supabase = createSupabaseRequestClient();
  const { data, error } = await supabase.auth.getUser();
  if (error || !data.user) throw new Error("Not signed in.");
  return { supabase, userId: data.user.id };
}

export const getDailyHealth = createServerFn({ method: "GET" })
  .validator((data: { day: string }) => ({ day: daySchema.parse(data.day) }))
  .handler(async ({ data }): Promise<DailyHealth | null> => {
    const { supabase, userId } = await requireUser();
    const { data: row, error } = await supabase
      .from("daily_health_metrics")
      .select(
        "day, steps, active_calories_kcal, total_calories_kcal, sleep_start_at, sleep_end_at, total_sleep_seconds, sleep_score, resting_heart_rate_bpm, vo2_max, source_synced_at, synced_at",
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
      sleepStartAt: row.sleep_start_at,
      sleepEndAt: row.sleep_end_at,
      totalSleepSeconds: row.total_sleep_seconds,
      sleepScore: row.sleep_score,
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
        "id, activity_name, activity_type, started_at, duration_seconds, distance_meters, calories_kcal, average_heart_rate_bpm, total_sets, total_reps",
      )
      .eq("user_id", userId)
      .eq("local_day", data.day)
      .order("started_at", { ascending: false });

    if (error) throw new Error(error.message);
    return (rows ?? []).map((row) => ({
      id: row.id,
      name: row.activity_name,
      type: row.activity_type,
      startedAt: row.started_at,
      durationSeconds: row.duration_seconds,
      distanceMeters: row.distance_meters,
      caloriesKcal: row.calories_kcal,
      averageHeartRateBpm: row.average_heart_rate_bpm,
      totalSets: row.total_sets,
      totalReps: row.total_reps,
    }));
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
