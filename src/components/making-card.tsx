import { Lock } from "lucide-react";
import { Bar, BarChart, XAxis } from "recharts";

import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart";
import type { ChartConfig } from "@/components/ui/chart";
import { formatActivityTime, formatSyncStatus } from "@/lib/health/format";
import type { GithubCommit, GithubMaking } from "@/lib/github/github.functions";
import { summariseDay, weekSeries, type AccountDay } from "@/lib/github/making";
import { formatDayLabel } from "@/lib/weight/units";

/** Theme tokens, one per account, so colour is never hard-coded. */
const SERIES_COLOURS = ["var(--chart-1)", "var(--chart-2)"];
const colourFor = (index: number): string =>
  SERIES_COLOURS[index % SERIES_COLOURS.length] ?? "var(--chart-1)";

const plural = (count: number, one: string, many: string) => `${count} ${count === 1 ? one : many}`;

export function MakingCard({ making, day }: { making: GithubMaking; day: string }) {
  const { accounts, contributions, commits } = making;
  const summary = summariseDay(accounts, contributions, day);

  return (
    <section className="rounded-2xl border border-border bg-card p-4 md:p-5">
      <div>
        <p className="text-[11px] tracking-[0.16em] uppercase text-muted-foreground">GitHub</p>
        <h2 className="mt-1 font-display text-xl text-foreground">Making</h2>
      </div>

      {accounts.length === 0 ? (
        <div className="mt-4 rounded-xl border border-dashed border-border bg-muted/30 px-4 py-8 text-center text-xs text-muted-foreground">
          No GitHub account connected yet.
        </div>
      ) : (
        <>
          {summary.allNotSynced ? (
            <p className="mt-4 text-sm text-muted-foreground">Not synced for this day yet.</p>
          ) : (
            <>
              <p className="mt-4 font-display text-3xl text-foreground">
                {plural(summary.total, "contribution", "contributions")}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">{breakdown(summary.tally)}</p>
            </>
          )}

          {summary.total > 0 ? <SplitBar entries={summary.accounts} /> : null}

          <div className="mt-4 grid gap-3">
            {summary.accounts.map((entry, index) => (
              <AccountBlock
                key={entry.account.id}
                entry={entry}
                colour={colourFor(index)}
                commits={commits.filter((commit) => commit.accountId === entry.account.id)}
              />
            ))}
          </div>

          <WeekStrip making={making} day={day} />
        </>
      )}
    </section>
  );
}

function breakdown(tally: ReturnType<typeof summariseDay>["tally"]): string {
  const parts = [
    plural(tally.commit, "commit", "commits"),
    plural(tally.pull_request, "PR", "PRs"),
    plural(tally.issue, "issue", "issues"),
  ];
  if (tally.unsplit > 0) parts.push(`${tally.unsplit} private (unsplit)`);
  return parts.join(" · ");
}

function SplitBar({ entries }: { entries: AccountDay[] }) {
  const total = entries.reduce((sum, entry) => sum + entry.tally.total, 0);
  return (
    <div className="mt-3">
      <div
        role="img"
        aria-label={entries
          .map((entry) => `${entry.account.label}: ${entry.tally.total}`)
          .join(", ")}
        className="flex h-2 overflow-hidden rounded-full bg-muted"
      >
        {entries.map((entry, index) =>
          entry.tally.total > 0 ? (
            <div
              key={entry.account.id}
              style={{
                width: `${(entry.tally.total / total) * 100}%`,
                backgroundColor: colourFor(index),
              }}
            />
          ) : null,
        )}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
        {entries.map((entry, index) => (
          <span key={entry.account.id} className="inline-flex items-center gap-1.5">
            <span
              aria-hidden
              className="h-2 w-2 rounded-full"
              style={{ backgroundColor: colourFor(index) }}
            />
            {entry.account.label} {entry.tally.total}
          </span>
        ))}
      </div>
    </div>
  );
}

function AccountBlock({
  entry,
  colour,
  commits,
}: {
  entry: AccountDay;
  colour: string;
  commits: GithubCommit[];
}) {
  const { account, tally, state } = entry;
  const itemised = account.detail === "full";

  return (
    <article className="rounded-xl border border-border bg-background/40 p-3.5">
      <div className="flex items-center gap-2">
        <span
          aria-hidden
          className="h-2.5 w-2.5 shrink-0 rounded-full"
          style={{ backgroundColor: colour }}
        />
        <h3 className="text-sm font-medium text-foreground">{account.label}</h3>
        <span className="ml-auto text-[11px] text-muted-foreground">
          {account.lastSyncedAt ? formatSyncStatus(account.lastSyncedAt) : "Never synced"}
        </span>
      </div>

      {state === "not-synced" ? (
        <p className="mt-2 text-xs text-muted-foreground">Not synced for this day.</p>
      ) : state === "quiet" ? (
        <p className="mt-2 text-xs text-muted-foreground">Quiet — nothing recorded.</p>
      ) : (
        <p className="mt-2 text-xs text-muted-foreground">
          {plural(tally.commit, "commit", "commits")} · {plural(tally.pull_request, "PR", "PRs")} ·{" "}
          {plural(tally.issue, "issue", "issues")}
        </p>
      )}

      {itemised && commits.length > 0 ? (
        <ul className="mt-3 grid gap-1.5">
          {commits.map((commit) => (
            <li key={commit.oid} className="flex items-start gap-2 text-xs">
              <span className="w-11 shrink-0 text-muted-foreground tabular-nums">
                {formatActivityTime(commit.authoredAt)}
              </span>
              <span className="min-w-0">
                <span className="flex items-center gap-1 text-muted-foreground">
                  {commit.isPrivate ? (
                    <Lock className="h-3 w-3 shrink-0" aria-label="Private repository" />
                  ) : null}
                  <span className="truncate">{commit.repo}</span>
                </span>
                <span className="block break-words text-foreground">{commit.headline}</span>
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </article>
  );
}

function WeekStrip({ making, day }: { making: GithubMaking; day: string }) {
  const data = weekSeries(making.accounts, making.contributions, day);
  const config: ChartConfig = Object.fromEntries(
    making.accounts.map((account, index) => [
      account.id,
      { label: account.label, color: colourFor(index) },
    ]),
  );

  return (
    <div className="mt-5">
      <p className="text-[11px] tracking-[0.16em] uppercase text-muted-foreground">Last 7 days</p>
      <ChartContainer config={config} className="mt-2 aspect-auto h-36 w-full">
        <BarChart data={data} margin={{ top: 4, right: 0, bottom: 0, left: 0 }}>
          <XAxis
            dataKey="day"
            tickLine={false}
            axisLine={false}
            tickFormatter={(value: string) => formatDayLabel(value).split(" ")[0] ?? value}
          />
          <ChartTooltip content={<ChartTooltipContent labelFormatter={formatDayLabel} />} />
          <ChartLegend content={<ChartLegendContent />} />
          {making.accounts.map((account) => (
            <Bar
              key={account.id}
              dataKey={account.id}
              stackId="contributions"
              fill={`var(--color-${account.id})`}
            />
          ))}
        </BarChart>
      </ChartContainer>
    </div>
  );
}
