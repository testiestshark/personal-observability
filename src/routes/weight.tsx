import { createFileRoute, useRouter } from "@tanstack/react-router";
import { useState, type FormEvent } from "react";

import { PageHeader } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  formatUkDateTime,
  formatWeight,
  isWeightUnit,
  UNIT_LABELS,
  WEIGHT_UNITS,
  type WeightUnit,
} from "@/lib/weight/units";
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

function Weight() {
  const router = useRouter();
  const entries = Route.useLoaderData();

  const [weight, setWeight] = useState("");
  const [unit, setUnit] = useState<WeightUnit>("kg");
  const [recordedAt, setRecordedAt] = useState(nowForDateTimeInput);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError(null);

    try {
      const parsed = Number(weight);
      if (!Number.isFinite(parsed) || parsed <= 0) {
        setError("Enter a weight greater than zero.");
        return;
      }

      const result = await addWeightEntry({
        data: {
          weight: parsed,
          unit,
          // The picker gives wall-clock time with no zone; the Date constructor
          // reads it in the device's zone, giving the correct instant to store.
          recordedAt: new Date(recordedAt).toISOString(),
        },
      });

      if (result.error) {
        setError(result.error);
        return;
      }

      setWeight("");
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
        subtitle="Recorded in UK time. Enter in whichever unit you prefer."
      />

      <div className="grid gap-4">
        <section className="rounded-xl border border-border bg-card p-4">
          <h2 className="text-sm font-medium">Add an entry</h2>

          <form onSubmit={handleSubmit} className="mt-3 grid gap-4">
            <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_9rem]">
              <div className="grid gap-2">
                <Label htmlFor="weight">Weight</Label>
                <Input
                  id="weight"
                  type="number"
                  inputMode="decimal"
                  step="0.1"
                  min="0"
                  required
                  placeholder="0.0"
                  value={weight}
                  onChange={(event) => setWeight(event.target.value)}
                  disabled={pending}
                />
              </div>

              <div className="grid gap-2">
                <Label htmlFor="unit">Unit</Label>
                <Select
                  value={unit}
                  onValueChange={(value) => {
                    if (isWeightUnit(value)) setUnit(value);
                  }}
                  disabled={pending}
                >
                  <SelectTrigger id="unit">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {WEIGHT_UNITS.map((value) => (
                      <SelectItem key={value} value={value}>
                        {UNIT_LABELS[value]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
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
              {pending ? "Saving…" : "Save entry"}
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
