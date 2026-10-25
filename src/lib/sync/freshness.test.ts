import { describe, expect, it } from "vitest";

import {
  DEVICE_SYNC_THRESHOLD_MS,
  WORKER_STALE_THRESHOLD_MS,
  formatStale,
  isDeviceSyncOld,
  isWorkerStale,
  staleWorkers,
} from "./freshness";

const HOUR = 60 * 60 * 1000;
const now = new Date("2026-10-25T12:00:00Z");
const hoursAgo = (hours: number) => new Date(now.getTime() - hours * HOUR).toISOString();

describe("thresholds", () => {
  it("are 3 hours for a Worker run and 12 hours for a Device sync", () => {
    expect(WORKER_STALE_THRESHOLD_MS).toBe(3 * HOUR);
    expect(DEVICE_SYNC_THRESHOLD_MS).toBe(12 * HOUR);
  });
});

describe("isWorkerStale", () => {
  it("is not stale for a recent run", () => {
    expect(isWorkerStale(hoursAgo(1), now)).toBe(false);
  });

  it("is not stale exactly at the threshold, and stale just past it", () => {
    expect(isWorkerStale(hoursAgo(3), now)).toBe(false);
    expect(isWorkerStale(new Date(now.getTime() - 3 * HOUR - 1).toISOString(), now)).toBe(true);
  });

  it("is stale when there has never been a run", () => {
    expect(isWorkerStale(null, now)).toBe(true);
    expect(isWorkerStale(undefined, now)).toBe(true);
  });

  it("is stale for an unparseable timestamp", () => {
    expect(isWorkerStale("not a date", now)).toBe(true);
  });

  it("is not stale for a run slightly in the future (clock skew)", () => {
    expect(isWorkerStale(hoursAgo(-0.1), now)).toBe(false);
  });
});

describe("isDeviceSyncOld", () => {
  it("is old past 12 hours only", () => {
    expect(isDeviceSyncOld(hoursAgo(12), now)).toBe(false);
    expect(isDeviceSyncOld(hoursAgo(13), now)).toBe(true);
  });

  it("is not old when the time is unknown", () => {
    expect(isDeviceSyncOld(null, now)).toBe(false);
  });
});

describe("formatStale", () => {
  it("says how long ago the last run was", () => {
    expect(formatStale(hoursAgo(6), now)).toBe("Stale · last ran 6h ago");
    expect(formatStale(hoursAgo(49), now)).toBe("Stale · last ran 2d ago");
  });

  it("says never ran without a heartbeat", () => {
    expect(formatStale(null, now)).toBe("Stale · never ran");
  });
});

describe("staleWorkers", () => {
  const recent = hoursAgo(1);
  const old = hoursAgo(5);

  it("is empty when every worker ran recently", () => {
    expect(staleWorkers({ garmin: recent, hevy: recent, github: recent }, now)).toEqual([]);
  });

  it("names each stale worker, in a fixed order", () => {
    expect(staleWorkers({ garmin: old, hevy: recent, github: null }, now)).toEqual([
      "Garmin",
      "GitHub",
    ]);
  });

  it("lists all three when all are stale", () => {
    expect(staleWorkers({ garmin: old, hevy: old, github: old }, now)).toEqual([
      "Garmin",
      "Hevy",
      "GitHub",
    ]);
  });
});
