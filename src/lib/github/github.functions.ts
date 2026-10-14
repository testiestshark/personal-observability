import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";

import {
  CONTRIBUTION_KINDS,
  weekWindow,
  type ContributionKind,
  type ContributionRow,
  type GithubAccount,
  type GithubDetail,
} from "./making";

const daySchema = z.string().regex(/^\d{4}-(0[1-9]|1[0-2])-([12]\d|3[01]|0[1-9])$/);

/** One itemised commit. Only ever returned for accounts with detail = 'full'. */
export type GithubCommit = {
  accountId: string;
  oid: string;
  repo: string;
  isPrivate: boolean;
  headline: string;
  authoredAt: string;
};

export type GithubMaking = {
  accounts: GithubAccount[];
  /** The seven days ending on the viewed day. */
  contributions: ContributionRow[];
  /** The viewed day's commits, for full-detail accounts. */
  commits: GithubCommit[];
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

const isKind = (value: string): value is ContributionKind =>
  (CONTRIBUTION_KINDS as readonly string[]).includes(value);

async function loadAccounts(
  supabase: Awaited<ReturnType<typeof requireUser>>["supabase"],
  userId: string,
): Promise<GithubAccount[]> {
  const { data: rows, error } = await supabase
    .from("github_accounts")
    .select("id, label, detail, token_expires_at, last_synced_at")
    .eq("user_id", userId)
    .order("display_order", { ascending: true })
    .order("created_at", { ascending: true });

  if (error) throw new Error(error.message);
  return (rows ?? []).map((row) => ({
    id: row.id,
    label: row.label,
    // `github_accounts_detail_known` limits the column to these two values.
    detail: row.detail as GithubDetail,
    tokenExpiresAt: row.token_expires_at,
    lastSyncedAt: row.last_synced_at,
  }));
}

async function loadContributions(
  supabase: Awaited<ReturnType<typeof requireUser>>["supabase"],
  userId: string,
  from: string,
  to: string,
): Promise<ContributionRow[]> {
  const { data: rows, error } = await supabase
    .from("github_daily_contributions")
    .select("account_id, local_day, kind, count")
    .eq("user_id", userId)
    .gte("local_day", from)
    .lte("local_day", to);

  if (error) throw new Error(error.message);
  return (rows ?? [])
    .filter((row) => isKind(row.kind))
    .map((row) => ({
      accountId: row.account_id,
      day: row.local_day,
      kind: row.kind as ContributionKind,
      count: row.count,
    }));
}

/**
 * Everything the Making card needs for one day. A counts_only account has no
 * itemised commits fetched at all, so a repo name or headline cannot reach the
 * page for it whatever the component does.
 */
export const getGithubMaking = createServerFn({ method: "GET" })
  .validator((data: { day: string }) => ({ day: daySchema.parse(data.day) }))
  .handler(async ({ data }): Promise<GithubMaking> => {
    const { supabase, userId } = await requireUser();
    const window = weekWindow(data.day);
    const [from] = window;
    const accounts = await loadAccounts(supabase, userId);
    const contributions = await loadContributions(supabase, userId, from ?? data.day, data.day);

    const fullIds = accounts.filter((account) => account.detail === "full").map((a) => a.id);
    let commits: GithubCommit[] = [];
    if (fullIds.length > 0) {
      const { data: rows, error } = await supabase
        .from("github_commits")
        .select(
          "account_id, oid, repo_name_with_owner, repo_is_private, message_headline, authored_at",
        )
        .eq("user_id", userId)
        .eq("local_day", data.day)
        .in("account_id", fullIds)
        .order("authored_at", { ascending: true });

      if (error) throw new Error(error.message);
      commits = (rows ?? []).map((row) => ({
        accountId: row.account_id,
        oid: row.oid,
        repo: row.repo_name_with_owner,
        isPrivate: row.repo_is_private,
        headline: row.message_headline,
        authoredAt: row.authored_at,
      }));
    }

    return { accounts, contributions, commits };
  });

/** Per-account status for the Sources page: the accounts and the last 7 days of counts. */
export const getGithubStatus = createServerFn({ method: "GET" }).handler(
  async (): Promise<{ accounts: GithubAccount[]; contributions: ContributionRow[] }> => {
    const { supabase, userId } = await requireUser();
    const accounts = await loadAccounts(supabase, userId);
    const today = new Date().toISOString().slice(0, 10);
    const [from] = weekWindow(today);
    const contributions = await loadContributions(supabase, userId, from ?? today, today);
    return { accounts, contributions };
  },
);
