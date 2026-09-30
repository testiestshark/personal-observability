import { createFileRoute, useRouter } from "@tanstack/react-router";
import { useState, type FormEvent } from "react";

import { PageHeader } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { WeightCalendar } from "@/components/weight-calendar";
import { WeightTrend } from "@/components/weight-trend";
import { WeightWheel } from "@/components/weight-picker";
import { currentLondonDay, currentLondonMonth } from "@/lib/weight/units";
import {
  addWeightEntry,
  deleteWeightEntry,
  listMonthWeights,
  listWeightEntries,
} from "@/lib/weight/weight.functions";

const MONTH_PATTERN = /^\d{4}-(0[1-9]|1[0-2])$/;

export const Route = createFileRoute("/weight")({
  head: () => ({
    meta: [
      { title: "Weight — Personal Observability" },
      { name: "description", content: "Record and review your weight over time." },
    ],
  }),
  // The displayed month lives in the URL, so browser back/forward steps through
  // months and a refresh keeps you where you were.
  validateSearch: (search: Record<string, unknown>): { month: string } => {
    const month = search["month"];
    return {
      month: typeof month === "string" && MONTH_PATTERN.test(month) ? month : currentLondonMonth(),
    };
  },
  loaderDeps: ({ search: { month } }) => ({ month }),
  // Loaded server-side, so the list and grid are present on first paint.
  loader: async ({ deps: { month } }) => ({
    entries: await listWeightEntries(),
    days: await listMonthWeights({ data: { month } }),
  }),
  component: Weight,
});

/**
 * Where the wheel starts when there is nothing to go on. Only used for a first
 * ever entry — after that the most recent weigh-in is the far better guess.
 */
const DEFAULT_KG = 80;

function Weight() {
  const router = useRouter();
  const navigate = Route.useNavigate();
  const { month } = Route.useSearch();
  const { entries, days } = Route.useLoaderData();

  // Entries come back newest first, so the head is the last recorded weight.
  const lastWeightKg = entries[0]?.weightKg ?? DEFAULT_KG;

  const [open, setOpen] = useState(false);
  const [weightKg, setWeightKg] = useState(() => Number(lastWeightKg.toFixed(1)));
  // A weigh-in is a day, not an instant — at most one per day.
  const [day, setDay] = useState(currentLondonDay);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError(null);

    try {
      const result = await addWeightEntry({ data: { weight: weightKg, day } });

      if (result.error) {
        setError(result.error);
        return;
      }

      setOpen(false);
      await router.invalidate();
    } catch {
      setError("Could not save that entry. Please try again.");
    } finally {
      setPending(false);
    }
  }

  function handleOpenChange(next: boolean) {
    if (next) {
      // Reopening is a fresh attempt: default to today rather than whenever the
      // page was loaded, and clear any error left over from a previous try. The
      // wheel deliberately keeps its position — consecutive weigh-ins are close.
      setDay(currentLondonDay());
      setError(null);
    }
    setOpen(next);
  }

  /** Returns an error message, or null once the entry is gone and data refreshed. */
  async function handleDelete(id: string): Promise<string | null> {
    const result = await deleteWeightEntry({ data: { id } });
    if (result.error) return result.error;
    await router.invalidate();
    return null;
  }

  return (
    <>
      <PageHeader eyebrow="Weight" />

      <div className="grid gap-4">
        <Dialog open={open} onOpenChange={handleOpenChange}>
          <DialogTrigger asChild>
            <Button className="w-full sm:w-auto sm:justify-self-start">Add an entry</Button>
          </DialogTrigger>

          <DialogContent className="max-w-xs">
            <DialogHeader>
              <DialogTitle className="font-display text-lg">Add an entry</DialogTitle>
            </DialogHeader>

            <form onSubmit={handleSubmit} className="grid gap-4">
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
                <Label htmlFor="recorded-on">Date</Label>
                <Input
                  id="recorded-on"
                  type="date"
                  required
                  value={day}
                  // Nothing can be weighed in the future.
                  max={currentLondonDay()}
                  onChange={(event) => setDay(event.target.value)}
                  disabled={pending}
                  // A native date field lays its shadow-DOM contents out on the
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

              <Button type="submit" disabled={pending} className="w-full">
                {pending ? "Saving…" : `Save ${weightKg.toFixed(1)} kg`}
              </Button>
            </form>
          </DialogContent>
        </Dialog>

        <WeightCalendar
          month={month}
          days={days}
          today={currentLondonDay()}
          onMonthChange={(next) => navigate({ search: { month: next } })}
          onDelete={handleDelete}
          // Nothing is ever recorded in the future, so there is nowhere to go.
          canGoForward={month < currentLondonMonth()}
        />

        <WeightTrend entries={entries} />
      </div>
    </>
  );
}
