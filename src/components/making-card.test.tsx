// The pill's stale rule is tested in lib/sync/freshness.test.ts; this covers that the
// card takes it from the Worker run and not from an account's last-synced time.
// Smoke-level: jsdom draws no chart, so only the pill text is asserted (docs/TESTING.md).
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MakingCard } from "./making-card";
import type { GithubMaking } from "@/lib/github/github.functions";

const NOW = new Date("2026-10-25T12:00:00Z");
const hoursAgo = (hours: number) => new Date(NOW.getTime() - hours * 3_600_000).toISOString();

const making = (lastSyncedAt: string | null): GithubMaking => ({
  accounts: [],
  contributions: [],
  commits: [],
  ...(lastSyncedAt
    ? {
        accounts: [
          { id: "a", label: "Personal", detail: "full", tokenExpiresAt: null, lastSyncedAt },
        ],
      }
    : {}),
});

describe("MakingCard sync pill", () => {
  it("is stale when the latest Worker run is older than 3 hours", () => {
    render(<MakingCard making={making(null)} day="2026-10-25" workerRun={hoursAgo(6)} now={NOW} />);

    expect(screen.getByText("Stale · last ran 6h ago")).toBeInTheDocument();
  });

  it("is stale when the worker has never run", () => {
    render(<MakingCard making={making(null)} day="2026-10-25" workerRun={null} now={NOW} />);

    expect(screen.getByText("Stale · never ran")).toBeInTheDocument();
  });

  it("stays stale even though an account synced recently", () => {
    render(
      <MakingCard
        making={making(hoursAgo(1))}
        day="2026-10-25"
        workerRun={hoursAgo(5)}
        now={NOW}
      />,
    );

    expect(screen.getByText("Stale · last ran 5h ago")).toBeInTheDocument();
  });

  it("is not stale after a recent Worker run, even if an account synced long ago", () => {
    render(
      <MakingCard
        making={making(hoursAgo(30))}
        day="2026-10-25"
        workerRun={hoursAgo(1)}
        now={NOW}
      />,
    );

    expect(screen.queryByText(/Stale/)).not.toBeInTheDocument();
    expect(screen.getByText(/^Updated /)).toBeInTheDocument();
  });
});
