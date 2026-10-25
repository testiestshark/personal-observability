const HOUR_MS = 60 * 60 * 1000;

/** How long since a Worker run before a source counts as Stale. See CONTEXT.md. */
export const WORKER_STALE_THRESHOLD_MS = 3 * HOUR_MS;

/** How long since a Device sync before the owner is nudged to open the Garmin app. */
export const DEVICE_SYNC_THRESHOLD_MS = 12 * HOUR_MS;

function ageMs(timestamp: string | null | undefined, now: Date): number | null {
  if (!timestamp) return null;
  const time = new Date(timestamp).getTime();
  return Number.isNaN(time) ? null : now.getTime() - time;
}

/**
 * The Worker run that sets a card fed by several sources: the oldest of them.
 * If any source has no readable heartbeat the result is null, which reads as
 * Stale ("never ran") because that source is unproven.
 */
export function oldestWorkerRun(runs: Array<string | null | undefined>): string | null {
  let oldest: { iso: string; time: number } | null = null;
  for (const run of runs) {
    const time = run ? new Date(run).getTime() : Number.NaN;
    if (Number.isNaN(time)) return null;
    if (!oldest || time < oldest.time) oldest = { iso: run as string, time };
  }
  return oldest?.iso ?? null;
}

/**
 * Whether a source's latest Worker run is too old. Only the heartbeat counts,
 * never the data: a quiet day with a recent run is not Stale. A missing or
 * unreadable heartbeat is Stale, because nothing proves the worker is alive.
 */
export function isWorkerStale(lastRunAt: string | null | undefined, now: Date): boolean {
  const age = ageMs(lastRunAt, now);
  return age === null || age > WORKER_STALE_THRESHOLD_MS;
}

/** Whether the watch last synced long enough ago to nudge the owner. Unknown is not old. */
export function isDeviceSyncOld(deviceSyncAt: string | null | undefined, now: Date): boolean {
  const age = ageMs(deviceSyncAt, now);
  return age !== null && age > DEVICE_SYNC_THRESHOLD_MS;
}

/** The pill text for a Stale source: "Stale · last ran 6h ago", or that it has never run. */
export function formatStale(lastRunAt: string | null | undefined, now: Date): string {
  const age = ageMs(lastRunAt, now);
  if (age === null) return "Stale · never ran";
  const hours = Math.floor(age / HOUR_MS);
  return hours < 24
    ? `Stale · last ran ${hours}h ago`
    : `Stale · last ran ${Math.floor(hours / 24)}d ago`;
}

const WORKER_LABELS = { garmin: "Garmin", hevy: "Hevy", github: "GitHub" } as const;

/** Display names of the sources whose Worker is Stale, for the strip on Today. Device sync never counts. */
export function staleWorkers(
  runs: Record<keyof typeof WORKER_LABELS, string | null | undefined>,
  now: Date,
): string[] {
  return (Object.keys(WORKER_LABELS) as (keyof typeof WORKER_LABELS)[])
    .filter((source) => isWorkerStale(runs[source], now))
    .map((source) => WORKER_LABELS[source]);
}
