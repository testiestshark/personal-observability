import { createFileRoute, useRouter } from "@tanstack/react-router";
import { useState, type FormEvent } from "react";

import { PageHeader } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { WeightWheel } from "@/components/weight-picker";
import { formatUkDateTime, formatWeight } from "@/lib/weight/units";
import {
  addWeightEntry,
  deleteWeightEntry,
  listWeightEntries,
} from "@/lib/weight/weight.functions";

export const Route = createFileRoute("/weight")({
  head: () => ({
    meta: [
      { title: "Weight — Personal Observability" },
      { name: "description", content: "Record and review your weight over time." },
    ],
  }),
  // Loaded server-side, so the list is present on first paint.
  loader: () => listWeightEntries(),
  component: Weight,
});

/**
 * `datetime-local` needs "YYYY-MM-DDTHH:mm" in the device's own time zone —
 * toISOString() would return UTC and silently shift the prefilled time during
 * British Summer Time.
 */
function nowForDateTimeInput(): string {
  const now = new Date();
  const offsetMs = now.getTimezoneOffset() * 60_000;
  return new Date(now.getTime() - offsetMs).toISOString().slice(0, 16);
}

/**
 * Where the wheel starts when there is nothing to go on. Only used for a first
 * ever entry — after that the most recent weigh-in is the far better guess.
 */
const DEFAULT_KG = 80;

function Weight() {
  const router = useRouter();
  const entries = Route.useLoaderData();

  // Entries come back newest first, so the head is the last recorded weight.
  const lastWeightKg = entries[0]?.weightKg ?? DEFAULT_KG;

  const [weightKg, setWeightKg] = useState(() => Number(lastWeightKg.toFixed(1)));
  const [recordedAt, setRecordedAt] = useState(nowForDateTimeInput);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError(null);

    try {
      const result = await addWeightEntry({
        data: {
          weight: weightKg,
          unit: "kg",
          // The picker gives wall-clock time with no zone; the Date constructor
          // reads it in the device's zone, giving the correct instant to store.
          recordedAt: new Date(recordedAt).toISOString(),
        },
      });

      if (result.error) {
        setError(result.error);
        return;
      }

      // The wheel stays where it was left — the next weigh-in is nearly always
      // near the last one — but the timestamp rolls forward to now.
      setRecordedAt(nowForDateTimeInput());
      await router.invalidate();
    } catch {
      setError("Could not save that entry. Please try again.");
    } finally {
      setPending(false);
    }
  }

  async function handleDelete(id: string) {
    const result = await deleteWeightEntry({ data: { id } });
    if (result.error) {
      setError(result.error);
      return;
    }
    await router.invalidate();
  }

  return (
    <>
      <PageHeader
        eyebrow="Weight"
        title="What you weighed"
        subtitle="Recorded in UK time, in kilograms."
      />

      <div className="grid gap-4">
        <section className="rounded-xl border border-border bg-card p-4">
          <h2 className="text-sm font-medium">Add an entry</h2>

          <form onSubmit={handleSubmit} className="mt-3 grid gap-4">
            <div className="grid gap-2">
              <Label>Weight</Label>
              <WeightWheel
                value={weightKg}
                onChange={setWeightKg}
                disabled={pending}
                ariaLabel="Weight in kilograms"
              />
            </div>

            <div className="grid gap-2">
              <Label htmlFor="recorded-at">Date and time</Label>
              <Input
                id="recorded-at"
                type="datetime-local"
                required
                value={recordedAt}
                onChange={(event) => setRecordedAt(event.target.value)}
                disabled={pending}
                // A native datetime-local lays its shadow-DOM field out on the
                // baseline, so inside the Input's flex box it sits high and reads
                // as a different height from every other control. Centring the
                // flex child lines it up with the rest of the form.
                className="items-center [&::-webkit-calendar-picker-indicator]:cursor-pointer [&::-webkit-calendar-picker-indicator]:opacity-60"
              />
            </div>

            {error ? (
              <p role="alert" className="text-sm text-destructive">
                {error}
              </p>
            ) : null}

            <Button
              type="submit"
              disabled={pending}
              className="w-full sm:w-auto sm:justify-self-start"
            >
              {pending ? "Saving…" : `Save ${weightKg.toFixed(1)} kg`}
            </Button>
          </form>
        </section>

        <section className="rounded-xl border border-border bg-card p-4">
          <h2 className="text-sm font-medium">History</h2>

          {entries.length === 0 ? (
            <p className="mt-3 text-sm text-muted-foreground">
              Nothing recorded yet. Your first entry will appear here.
            </p>
          ) : (
            <ul className="mt-2">
              {entries.map((entry) => (
                <li
                  key={entry.id}
                  className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-3 border-b border-border py-3 last:border-0"
                >
                  <span className="truncate text-sm text-muted-foreground">
                    {formatUkDateTime(entry.recordedAt)}
                  </span>
                  <span className="shrink-0 text-sm tabular-nums text-foreground">
                    {formatWeight(entry.weightKg, entry.unit)}
                  </span>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="shrink-0 text-muted-foreground hover:text-destructive"
                    onClick={() => handleDelete(entry.id)}
                    aria-label={`Delete entry from ${formatUkDateTime(entry.recordedAt)}`}
                  >
                    Delete
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </>
  );
}
