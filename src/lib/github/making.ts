// Pure logic for the "Making" card on Today and the GitHub rows on Sources (#78).
//
// No I/O, so it is safe on server and client and cheap to test. The days here are
// GitHub's UTC dates (see the github_daily_contributions migration), not
// Europe/London days; the card shows the contribution date that matches the
// calendar date being viewed.

import { shiftDay } from "@/lib/weight/units";

export const CONTRIBUTION_KINDS = ["commit", "pull_request", "review", "issue", "unsplit"] as const;
export type ContributionKind = (typeof CONTRIBUTION_KINDS)[number];

export type GithubDetail = "full" | "counts_only";

export type GithubAccount = {
  id: string;
  label: string;
  detail: GithubDetail;
  tokenExpiresAt: string | null;
  lastSyncedAt: string | null;
};

export type ContributionRow = {
  accountId: string;
  day: string;
  kind: ContributionKind;
  count: number;
};

export type DayTally = {
  commit: number;
  pull_request: number;
  review: number;
  issue: number;
  /** Contributions GitHub counted but would not itemise (private repositories). */
  unsplit: number;
  /** Every kind summed: the number the card calls "contributions". */
  total: number;
};

/** How many days before expiry the Sources page starts warning. */
export const TOKEN_WARNING_DAYS = 14;

export const WEEK_LENGTH = 7;

const emptyTally = (): DayTally => ({
  commit: 0,
  pull_request: 0,
  review: 0,
  issue: 0,
  unsplit: 0,
  total: 0,
});

/** One account's counts for one day. */
export function tallyDay(rows: ContributionRow[], accountId: string, day: string): DayTally {
  const tally = emptyTally();
  for (const row of rows) {
    if (row.accountId !== accountId || row.day !== day) continue;
    tally[row.kind] += row.count;
    tally.total += row.count;
  }
  return tally;
}

/**
 * Whether the worker has written anything for this account and day. The worker
 * writes all five kinds even when they are zero, so rows mean "synced, and
 * quiet if the counts are zero"; no rows means the day was never fetched.
 */
export function hasDayData(rows: ContributionRow[], accountId: string, day: string): boolean {
  return rows.some((row) => row.accountId === accountId && row.day === day);
}

export type AccountDay = {
  account: GithubAccount;
  tally: DayTally;
  /** "quiet" is a synced day with nothing in it; "not-synced" is no data at all. */
  state: "active" | "quiet" | "not-synced";
};

export type DaySummary = {
  accounts: AccountDay[];
  /** Sum across accounts. Accounts that were not synced add nothing. */
  total: number;
  /** Per-type sums across accounts, for the breakdown line. */
  tally: DayTally;
  /** True when no account has any data for the day. */
  allNotSynced: boolean;
};

export function summariseDay(
  accounts: GithubAccount[],
  rows: ContributionRow[],
  day: string,
): DaySummary {
  const perAccount = accounts.map((account): AccountDay => {
    const tally = tallyDay(rows, account.id, day);
    const state = !hasDayData(rows, account.id, day)
      ? "not-synced"
      : tally.total > 0
        ? "active"
        : "quiet";
    return { account, tally, state };
  });

  const tally = emptyTally();
  for (const entry of perAccount) {
    for (const kind of CONTRIBUTION_KINDS) tally[kind] += entry.tally[kind];
    tally.total += entry.tally.total;
  }

  return {
    accounts: perAccount,
    total: tally.total,
    tally,
    allNotSynced: perAccount.every((entry) => entry.state === "not-synced"),
  };
}

/** The `length` days ending on `day`, oldest first. */
export function weekWindow(day: string, length: number = WEEK_LENGTH): string[] {
  return Array.from({ length }, (_, index) => shiftDay(day, index - (length - 1)));
}

export type WeekPoint = { day: string; [accountId: string]: number | string };

/** One point per day, with each account's total keyed by its id, for a stacked bar. */
export function weekSeries(
  accounts: GithubAccount[],
  rows: ContributionRow[],
  day: string,
): WeekPoint[] {
  return weekWindow(day).map((windowDay) => {
    const point: WeekPoint = { day: windowDay };
    for (const account of accounts) {
      point[account.id] = tallyDay(rows, account.id, windowDay).total;
    }
    return point;
  });
}

export type TokenWarning = { kind: "expired" | "expiring"; days: number };

const MS_PER_DAY = 24 * 60 * 60 * 1000;

/** Null when the token is fine or has no recorded expiry. */
export function tokenWarning(
  tokenExpiresAt: string | null,
  now: Date,
  thresholdDays: number = TOKEN_WARNING_DAYS,
): TokenWarning | null {
  if (!tokenExpiresAt) return null;
  const expiry = new Date(tokenExpiresAt).getTime();
  if (Number.isNaN(expiry)) return null;

  const msLeft = expiry - now.getTime();
  if (msLeft <= 0) return { kind: "expired", days: 0 };

  const days = Math.ceil(msLeft / MS_PER_DAY);
  return days <= thresholdDays ? { kind: "expiring", days } : null;
}

export type AccountStatus = {
  account: GithubAccount;
  lastSyncedAt: string | null;
  warnings: string[];
};

/**
 * Per-account status for the Sources page. `recentRows` is the recent window the
 * server loaded; an `unsplit` count above zero on a `full` account means the
 * token could not see some repositories.
 */
export function accountStatus(
  account: GithubAccount,
  recentRows: ContributionRow[],
  now: Date,
): AccountStatus {
  const warnings: string[] = [];

  const expiry = tokenWarning(account.tokenExpiresAt, now);
  if (expiry?.kind === "expired") warnings.push("Token has expired");
  else if (expiry) {
    warnings.push(`Token expires in ${expiry.days} ${expiry.days === 1 ? "day" : "days"}`);
  }

  if (account.detail === "full") {
    const unsplit = recentRows
      .filter((row) => row.accountId === account.id && row.kind === "unsplit")
      .reduce((sum, row) => sum + row.count, 0);
    if (unsplit > 0) warnings.push("Token can't see some repos");
  }

  return { account, lastSyncedAt: account.lastSyncedAt, warnings };
}
