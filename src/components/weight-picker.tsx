import { useCallback, useEffect, useRef, useState } from "react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";


const ITEM_HEIGHT = 40;
const VISIBLE = 5;

function ScrollColumn({
  values,
  value,
  onChange,
  ariaLabel,
  suffix,
}: {
  values: number[];
  value: number;
  onChange: (next: number) => void;
  ariaLabel: string;
  suffix?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const settle = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isUserScrolling = useRef(false);

  // Keep the scroll position in sync when the value changes from outside.
  useEffect(() => {
    const el = ref.current;
    if (!el || isUserScrolling.current) return;
    const index = values.indexOf(value);
    if (index < 0) return;
    const target = index * ITEM_HEIGHT;
    if (Math.abs(el.scrollTop - target) > 1) {
      el.scrollTo({ top: target, behavior: "auto" });
    }
  }, [value, values]);

  const handleScroll = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    isUserScrolling.current = true;
    if (settle.current) clearTimeout(settle.current);
    settle.current = setTimeout(() => {
      isUserScrolling.current = false;
      const index = Math.max(
        0,
        Math.min(values.length - 1, Math.round(el.scrollTop / ITEM_HEIGHT)),
      );
      const next = values[index];
      if (next !== undefined && next !== value) onChange(next);
    }, 90);
  }, [onChange, value, values]);

  const step = (delta: number) => {
    const index = values.indexOf(value);
    const next = values[Math.max(0, Math.min(values.length - 1, index + delta))];
    if (next !== undefined) onChange(next);
  };

  return (
    <div
      ref={ref}
      role="listbox"
      aria-label={ariaLabel}
      tabIndex={0}
      onScroll={handleScroll}
      onKeyDown={(event) => {
        if (event.key === "ArrowUp") {
          event.preventDefault();
          step(-1);
        } else if (event.key === "ArrowDown") {
          event.preventDefault();
          step(1);
        }
      }}
      className="hide-scrollbar snap-y snap-mandatory overflow-y-scroll overscroll-contain rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-ring"
      style={{
        height: ITEM_HEIGHT * VISIBLE,
        paddingBlock: ITEM_HEIGHT * ((VISIBLE - 1) / 2),
        scrollBehavior: "smooth",
        WebkitOverflowScrolling: "touch",
      }}
    >
      {values.map((item) => {
        const active = item === value;
        return (
          <div
            key={item}
            role="option"
            aria-selected={active}
            onClick={() => onChange(item)}
            className={`flex snap-center cursor-pointer items-center justify-center tabular-nums transition-all ${
              active
                ? "font-display text-3xl text-foreground"
                : "text-lg text-muted-foreground/60"
            }`}
            style={{ height: ITEM_HEIGHT }}
          >
            {item}
            {suffix && active ? <span className="ml-1 text-sm">{suffix}</span> : null}
          </div>
        );
      })}
    </div>
  );
}

const WHOLE = Array.from({ length: 251 }, (_, i) => i + 20); // 20 – 270
const DECIMAL = Array.from({ length: 10 }, (_, i) => i); // .0 – .9

export function WeightPicker({
  initial = 80,
  onConfirm,
}: {
  initial?: number;
  onConfirm?: (kg: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const [whole, setWhole] = useState(Math.floor(initial));
  const [decimal, setDecimal] = useState(Math.round((initial % 1) * 10));
  const [saved, setSaved] = useState<number | null>(null);

  const kg = whole + decimal / 10;

  return (
    <section className="rounded-xl border border-border bg-card p-4">
      <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3">
        <h2 className="truncate text-sm font-medium text-foreground">Weight</h2>
        <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
          {saved === null ? "No entry today" : `${saved.toFixed(1)} kg`}
        </span>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogTrigger className="mt-3 w-full rounded-lg border border-border bg-muted/40 px-4 py-2.5 text-sm text-foreground transition-colors hover:bg-accent hover:text-accent-foreground">
          Add weight
        </DialogTrigger>
        <DialogContent className="max-w-xs">
          <DialogHeader>
            <DialogTitle className="font-display text-lg">Add weight</DialogTitle>
            <DialogDescription>Scroll to set today’s weight.</DialogDescription>
          </DialogHeader>

          <div className="relative mt-1">
            {/* selection band */}
            <div
              className="pointer-events-none absolute inset-x-0 top-1/2 -translate-y-1/2 rounded-lg border-y border-border bg-muted/40"
              style={{ height: ITEM_HEIGHT }}
            />
            <div className="relative grid grid-cols-[1fr_auto_1fr] items-center gap-1">
              <ScrollColumn values={WHOLE} value={whole} onChange={setWhole} ariaLabel="Kilograms" />
              <span className="font-display text-2xl text-muted-foreground">.</span>
              <ScrollColumn
                values={DECIMAL}
                value={decimal}
                onChange={setDecimal}
                ariaLabel="Decimal of a kilogram"
                suffix="kg"
              />
            </div>
          </div>

          <button
            type="button"
            onClick={() => {
              setSaved(kg);
              onConfirm?.(kg);
              setOpen(false);
            }}
            className="mt-2 w-full rounded-lg bg-primary px-4 py-2.5 text-sm text-primary-foreground transition-opacity hover:opacity-90"
          >
            Save {kg.toFixed(1)} kg
          </button>
        </DialogContent>
      </Dialog>
    </section>
  );
}

