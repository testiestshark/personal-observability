// A month grid of weigh-ins: Monday to Sunday across the top, one cell per day,
// showing the weight recorded on that day where there is one. Tapping a recorded
// day opens its details, with the option to delete it.
//
// The grid is pure calendar arithmetic and deliberately knows nothing about time
// zones. Days arrive already keyed as London dates (see londonDayKey) — deciding
// which day a UTC timestamp belongs to is the server's job, not the layout's.
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { formatDayLabel, formatMonthLabel, parseMonthKey, shiftMonth } from "@/lib/weight/units";
import type { DayWeight } from "@/lib/weight/weight.functions";

/** Monday-first, matching how a UK week is read. */
const WEEKDAYS = ["M", "T", "W", "T", "F", "S", "S"] as const;

function monthGrid(month: string) {
  const { year, monthNumber } = parseMonthKey(month);

  // UTC here is an arithmetic convenience, not a time zone claim: these Dates are
  // only ever asked for their day-of-month and day-of-week.
  const firstOfMonth = new Date(Date.UTC(year, monthNumber - 1, 1));
  // Day 0 of the next month is the last day of this one.
  const dayCount = new Date(Date.UTC(year, monthNumber, 0)).getUTCDate();
  // getUTCDay is Sunday-first (0–6); shift it so Monday is 0.
  const blanksBefore = (firstOfMonth.getUTCDay() + 6) % 7;

  return { dayCount, blanksBefore };
}

export function WeightCalendar({
  month,
  days,
  today,
  onMonthChange,
  onDelete,
  canGoForward = true,
}: {
  month: string;
  days: DayWeight[];
  today: string;
  onMonthChange: (month: string) => void;
  onDelete: (id: string) => Promise<string | null>;
  canGoForward?: boolean;
}) {
  const { dayCount, blanksBefore } = monthGrid(month);
  const weightByDay = new Map(days.map((entry) => [entry.day, entry]));

  // Which day's details are showing, and which one is awaiting confirmation.
  // Confirmation is held separately so the popover can close beneath it.
  const [openDay, setOpenDay] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<DayWeight | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleConfirmDelete() {
    if (!confirming) return;
    setDeleting(true);
    setError(null);

    const message = await onDelete(confirming.id);

    setDeleting(false);
    if (message) {
      setError(message);
      return;
    }
    setConfirming(null);
  }

  return (
    <section className="rounded-xl border border-border bg-card p-4">
      <div className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => onMonthChange(shiftMonth(month, -1))}
          aria-label="Previous month"
        >
          <ChevronLeft className="size-4" />
        </Button>
        <h2 className="text-center text-sm font-medium">{formatMonthLabel(month)}</h2>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => onMonthChange(shiftMonth(month, 1))}
          disabled={!canGoForward}
          aria-label="Next month"
        >
          <ChevronRight className="size-4" />
        </Button>
      </div>

      <div className="mt-3 grid grid-cols-7 gap-1">
        {WEEKDAYS.map((label, index) => (
          <div
            // Two Ts and two Ss, so the index is what makes these unique.
            key={index}
            aria-hidden
            className="pb-1 text-center text-[11px] tracking-wide uppercase text-muted-foreground"
          >
            {label}
          </div>
        ))}

        {Array.from({ length: blanksBefore }, (_, index) => (
          <div key={`blank-${index}`} />
        ))}

        {Array.from({ length: dayCount }, (_, index) => {
          const dayOfMonth = index + 1;
          const day = `${month}-${String(dayOfMonth).padStart(2, "0")}`;
          const entry = weightByDay.get(day);
          const isToday = day === today;

          const cell = (
            <>
              <span className="text-[10px] leading-none text-muted-foreground tabular-nums">
                {dayOfMonth}
              </span>
              {entry ? (
                <span className="text-xs leading-none font-medium text-foreground tabular-nums">
                  {entry.weightKg.toFixed(1)}
                </span>
              ) : null}
            </>
          );

          const cellClasses = `grid aspect-square content-center justify-items-center gap-0.5 rounded-lg border p-1 ${
            isToday ? "ring-1 ring-ring" : ""
          }`;

          // Only recorded days are interactive — there is nothing to show or
          // delete on an empty one.
          if (!entry) {
            return (
              <div key={day} className={`${cellClasses} border-transparent bg-muted/30`}>
                {cell}
              </div>
            );
          }

          return (
            <Popover
              key={day}
              open={openDay === day}
              onOpenChange={(next) => setOpenDay(next ? day : null)}
            >
              <PopoverTrigger
                className={`${cellClasses} border-border bg-background transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring`}
                aria-label={`${formatDayLabel(day)}, ${entry.weightKg.toFixed(1)} kilograms`}
              >
                {cell}
              </PopoverTrigger>

              <PopoverContent className="w-auto min-w-40 p-3">
                <p className="text-xs text-muted-foreground">{formatDayLabel(day)}</p>
                <p className="mt-0.5 font-display text-xl tabular-nums">
                  {entry.weightKg.toFixed(1)} kg
                </p>
                <Button
                  variant="ghost"
                  size="sm"
                  className="mt-2 w-full text-muted-foreground hover:text-destructive"
                  onClick={() => {
                    setOpenDay(null);
                    setError(null);
                    setConfirming(entry);
                  }}
                >
                  Delete
                </Button>
              </PopoverContent>
            </Popover>
          );
        })}
      </div>

      <AlertDialog
        open={confirming !== null}
        onOpenChange={(next) => {
          if (!next) setConfirming(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this weigh-in?</AlertDialogTitle>
            <AlertDialogDescription>
              {confirming
                ? `${confirming.weightKg.toFixed(1)} kg on ${formatDayLabel(confirming.day)} will be permanently deleted. This cannot be undone.`
                : null}
            </AlertDialogDescription>
          </AlertDialogHeader>

          {error ? (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          ) : null}

          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={(event) => {
                // Hold the dialog open while the delete is in flight, and keep it
                // open on failure so the error is not lost behind a closing
                // dialog. handleConfirmDelete closes it on success.
                event.preventDefault();
                void handleConfirmDelete();
              }}
              disabled={deleting}
            >
              {deleting ? "Deleting…" : "Delete"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  );
}
