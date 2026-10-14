import { describe, expect, it } from "vitest";

import {
  accountStatus,
  summariseDay,
  tallyDay,
  tokenWarning,
  weekSeries,
  weekTotal,
  weekWindow,
  type ContributionKind,
  type ContributionRow,
  type GithubAccount,
} from "./making";

const A: GithubAccount = {
  id: "a",
  label: "Account A",
  detail: "full",
  tokenExpiresAt: null,
  lastSyncedAt: "2026-10-13T08:00:00Z",
};
const B: GithubAccount = { ...A, id: "b", label: "Account B", detail: "counts_only" };

function day(accountId: string, date: string, counts: Partial<Record<ContributionKind, number>>) {
  const kinds: ContributionKind[] = ["commit", "pull_request", "review", "issue", "unsplit"];
  return kinds.map((kind): ContributionRow => ({
    accountId,
    day: date,
    kind,
    count: counts[kind] ?? 0,
  }));
}

describe("weekTotal", () => {
  it("sums every kind across accounts inside the 7-day window only", () => {
    const rows = [
      ...day("a", "2026-10-13", { commit: 4, pull_request: 1 }),
      ...day("b", "2026-10-07", { commit: 3, unsplit: 2 }),
      ...day("b", "2026-10-06", { commit: 99 }),
      ...day("a", "2026-10-14", { commit: 50 }),
    ];
    expect(weekTotal([A, B], rows, "2026-10-13")).toBe(10);
  });
});

describe("tallyDay", () => {
  it("sums the kinds for one account and one day only", () => {
    const rows = [
      ...day("a", "2026-10-13", { commit: 4, pull_request: 1, unsplit: 2 }),
      ...day("a", "2026-10-12", { commit: 9 }),
      ...day("b", "2026-10-13", { commit: 7 }),
    ];
    expect(tallyDay(rows, "a", "2026-10-13")).toEqual({
      commit: 4,
      pull_request: 1,
      review: 0,
      issue: 0,
      unsplit: 2,
      total: 7,
    });
  });
});

describe("summariseDay", () => {
  it("adds the accounts together", () => {
    const rows = [
      ...day("a", "2026-10-13", { commit: 3, review: 1 }),
      ...day("b", "2026-10-13", { commit: 2, unsplit: 5 }),
    ];
    const summary = summariseDay([A, B], rows, "2026-10-13");
    expect(summary.total).toBe(11);
    expect(summary.tally.commit).toBe(5);
    expect(summary.tally.unsplit).toBe(5);
  });

  it("tells a quiet day from a day that was never synced", () => {
    const rows = day("a", "2026-10-13", {});
    const summary = summariseDay([A, B], rows, "2026-10-13");
    expect(summary.accounts.map((entry) => entry.state)).toEqual(["quiet", "not-synced"]);
    expect(summary.allNotSynced).toBe(false);
    expect(summariseDay([A, B], [], "2026-10-13").allNotSynced).toBe(true);
  });
});

describe("weekWindow and weekSeries", () => {
  it("returns seven days ending on the viewed day, oldest first", () => {
    expect(weekWindow("2026-10-13")).toEqual([
      "2026-10-07",
      "2026-10-08",
      "2026-10-09",
      "2026-10-10",
      "2026-10-11",
      "2026-10-12",
      "2026-10-13",
    ]);
  });

  it("crosses a month boundary", () => {
    expect(weekWindow("2026-11-02")[0]).toBe("2026-10-27");
  });

  it("keys each account's total by id and fills quiet days with zero", () => {
    const rows = [
      ...day("a", "2026-10-13", { commit: 3 }),
      ...day("b", "2026-10-11", { issue: 2 }),
    ];
    const series = weekSeries([A, B], rows, "2026-10-13");
    expect(series).toHaveLength(7);
    expect(series.at(-1)).toEqual({ day: "2026-10-13", a: 3, b: 0 });
    expect(series.find((point) => point.day === "2026-10-11")).toEqual({
      day: "2026-10-11",
      a: 0,
      b: 2,
    });
  });
});

describe("tokenWarning", () => {
  const now = new Date("2026-10-14T12:00:00Z");

  it("is silent without an expiry", () => {
    expect(tokenWarning(null, now)).toBeNull();
  });

  it("is silent when expiry is beyond 14 days", () => {
    expect(tokenWarning("2026-10-29T12:00:00Z", now)).toBeNull();
  });

  it("warns at exactly 14 days and counts whole days remaining", () => {
    expect(tokenWarning("2026-10-28T12:00:00Z", now)).toEqual({ kind: "expiring", days: 14 });
    expect(tokenWarning("2026-10-14T18:00:00Z", now)).toEqual({ kind: "expiring", days: 1 });
  });

  it("is silent just past the 14-day threshold", () => {
    expect(tokenWarning("2026-10-28T12:00:00.001Z", now)).toBeNull();
  });

  it("reports an expired token", () => {
    expect(tokenWarning("2026-10-14T11:59:59Z", now)).toEqual({ kind: "expired", days: 0 });
  });
});

describe("accountStatus", () => {
  const now = new Date("2026-10-14T12:00:00Z");

  it("warns when a full account has unsplit contributions", () => {
    const rows = day("a", "2026-10-13", { unsplit: 3 });
    expect(accountStatus(A, rows, now).warnings).toEqual(["Token can't see some repos"]);
  });

  it("does not apply the unsplit warning to a counts_only account", () => {
    const rows = day("b", "2026-10-13", { unsplit: 3 });
    expect(accountStatus(B, rows, now).warnings).toEqual([]);
  });

  it("combines the expiry and unsplit warnings", () => {
    const account = { ...A, tokenExpiresAt: "2026-10-20T12:00:00Z" };
    const rows = day("a", "2026-10-13", { unsplit: 1 });
    expect(accountStatus(account, rows, now).warnings).toEqual([
      "Token expires in 6 days",
      "Token can't see some repos",
    ]);
  });
});
