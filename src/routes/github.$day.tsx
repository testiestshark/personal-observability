import { createFileRoute, Link } from "@tanstack/react-router";
import { ChevronLeft, Lock } from "lucide-react";
import { z } from "zod";

import { PageHeader } from "@/components/app-shell";
import { getGithubMaking } from "@/lib/github/github.functions";
import { formatActivityTime } from "@/lib/health/format";
import { formatDayLabel } from "@/lib/weight/units";

const daySchema = z.string().regex(/^\d{4}-(0[1-9]|1[0-2])-([12]\d|3[01]|0[1-9])$/);

export const Route = createFileRoute("/github/$day")({
  head: () => ({
    meta: [{ title: "GitHub — Personal Observability" }],
  }),
  params: {
    parse: (params) => ({ day: daySchema.parse(params.day) }),
  },
  loader: async ({ params }) => ({
    day: params.day,
    making: await getGithubMaking({ data: { day: params.day } }),
  }),
  component: GithubDay,
});

function GithubDay() {
  const { day, making } = Route.useLoaderData();
  const itemised = making.accounts.filter((account) =>
    making.commits.some((commit) => commit.accountId === account.id),
  );

  return (
    <>
      <Link
        to="/"
        search={{ day }}
        className="mb-5 inline-flex items-center gap-1 text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        <ChevronLeft className="h-4 w-4" />
        Back to day
      </Link>
      <PageHeader eyebrow={formatDayLabel(day)} title="GitHub commits" />

      {itemised.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border bg-muted/30 px-4 py-8 text-center text-xs text-muted-foreground">
          No itemised commits for this day.
        </div>
      ) : (
        itemised.map((account) => {
          const commits = making.commits.filter((commit) => commit.accountId === account.id);
          return (
            <section key={account.id} aria-label={account.label} className="mt-6 first:mt-0">
              <h2 className="mb-3 font-display text-lg text-foreground">{account.label}</h2>
              <ul className="divide-y divide-border rounded-2xl border border-border bg-card px-4 md:px-5">
                {commits.map((commit) => (
                  <li key={commit.oid} className="flex items-start gap-3 py-3 text-sm">
                    <span className="w-11 shrink-0 text-xs text-muted-foreground tabular-nums">
                      {formatActivityTime(commit.authoredAt)}
                    </span>
                    <span className="min-w-0">
                      <span className="flex items-center gap-1 text-xs text-muted-foreground">
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
            </section>
          );
        })
      )}
    </>
  );
}
