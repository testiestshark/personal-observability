import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";

const daySchema = z.string().regex(/^\d{4}-(0[1-9]|1[0-2])-([12]\d|3[01]|0[1-9])$/);

export type DailySteps = {
  day: string;
  steps: number;
  syncedAt: string;
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

export const getDailySteps = createServerFn({ method: "GET" })
  .validator((data: { day: string }) => ({ day: daySchema.parse(data.day) }))
  .handler(async ({ data }): Promise<DailySteps | null> => {
    const { supabase, userId } = await requireUser();
    const { data: row, error } = await supabase
      .from("daily_health_metrics")
      .select("day, steps, synced_at")
      .eq("user_id", userId)
      .eq("day", data.day)
      .eq("source", "garmin")
      .maybeSingle();

    if (error) throw new Error(error.message);
    if (!row || row.steps === null) return null;

    return { day: row.day, steps: row.steps, syncedAt: row.synced_at };
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
