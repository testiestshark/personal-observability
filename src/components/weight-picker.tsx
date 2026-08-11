// A scroll-wheel weight control: a whole-kilogram column and a decimal column.
//
// Deliberately controlled and stateless — it owns no notion of a "saved" value.
// An earlier version kept its own local `saved` state and displayed it as though
// it were persisted, which is how the app briefly ended up with a weight UI that
// looked like it worked but wrote nothing (see commit d1ba4ae). The value lives
// with whoever renders this; the wheel only reports changes.
//
// Kilograms only. Stone would need a different shape entirely (a 0–13 pounds
// column rather than a decimal), so it is not pretended at here.
import { useCallback, useEffect, useRef } from "react";

const ITEM_HEIGHT = 40;
const VISIBLE = 5;

/** Sane human range. Inside the CHECK bounds on weight_entries.weight_kg. */
const WHOLE_VALUES = Array.from({ length: 251 }, (_, i) => i + 20); // 20 – 270
const DECIMAL_VALUES = Array.from({ length: 10 }, (_, i) => i); // .0 – .9

function ScrollColumn({
  values,
  value,
  onChange,
  ariaLabel,
  disabled,
}: {
  values: number[];
  value: number;
  onChange: (next: number) => void;
  ariaLabel: string;
  // Explicitly `| undefined`: exactOptionalPropertyTypes is on, so an optional
  // prop otherwise refuses a value that is merely possibly undefined.
  disabled?: boolean | undefined;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const settle = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isUserScrolling = useRef(false);

  // Keep the scroll position in sync when the value changes from outside — on
  // first paint, and after a save resets the form.
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

  // Snap points land the wheel mid-gesture, so the value is read once scrolling
  // has stopped rather than on every frame.
  const handleScroll = useCallback(() => {
    const el = ref.current;
    if (!el || disabled) return;
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
  }, [disabled, onChange, value, values]);

  // Clear a pending settle on unmount so it cannot fire onChange afterwards.
  useEffect(() => {
    return () => {
      if (settle.current) clearTimeout(settle.current);
    };
  }, []);

  const step = (delta: number) => {
    if (disabled) return;
    const index = values.indexOf(value);
    const next = values[Math.max(0, Math.min(values.length - 1, index + delta))];
    if (next !== undefined) onChange(next);
  };

  return (
    <div
      ref={ref}
      role="listbox"
      aria-label={ariaLabel}
      aria-disabled={disabled}
      tabIndex={disabled ? -1 : 0}
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
      className={`hide-scrollbar snap-y snap-mandatory overflow-y-scroll overscroll-contain rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-ring ${
        disabled ? "pointer-events-none opacity-50" : ""
      }`}
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
            onClick={() => !disabled && onChange(item)}
            className={`flex snap-center cursor-pointer items-center justify-center tabular-nums transition-all ${
              active ? "font-display text-3xl text-foreground" : "text-lg text-muted-foreground/60"
            }`}
            style={{ height: ITEM_HEIGHT }}
          >
            {item}
          </div>
        );
      })}
    </div>
  );
}

/**
 * Pick a weight in kilograms to one decimal place.
 *
 * `value` is the weight in kg; `onChange` fires with the new weight whenever
 * either column settles.
 */
export function WeightWheel({
  value,
  onChange,
  disabled,
  ariaLabel = "Weight in kilograms",
}: {
  value: number;
  onChange: (kilograms: number) => void;
  disabled?: boolean | undefined;
  ariaLabel?: string;
}) {
  const whole = Math.floor(value);
  // Rounding the fractional part avoids 82.3 arriving as .2999 and snapping the
  // decimal column to the wrong row.
  const decimal = Math.round((value - whole) * 10);

  return (
    <div className="relative" role="group" aria-label={ariaLabel}>
      {/* Selection band, marking the row the columns snap to. */}
      <div
        className="pointer-events-none absolute inset-x-0 top-1/2 -translate-y-1/2 rounded-lg border-y border-border bg-muted/40"
        style={{ height: ITEM_HEIGHT }}
      />

      <div className="relative grid grid-cols-[1fr_auto_1fr_auto] items-center gap-1">
        <ScrollColumn
          values={WHOLE_VALUES}
          value={whole}
          onChange={(next) => onChange(next + decimal / 10)}
          ariaLabel="Kilograms"
          disabled={disabled}
        />
        <span aria-hidden className="font-display text-2xl text-muted-foreground">
          .
        </span>
        <ScrollColumn
          values={DECIMAL_VALUES}
          value={decimal}
          onChange={(next) => onChange(whole + next / 10)}
          ariaLabel="Decimal fraction of a kilogram"
          disabled={disabled}
        />
        <span aria-hidden className="pr-1 text-sm text-muted-foreground">
          kg
        </span>
      </div>

      <p className="sr-only" aria-live="polite">
        {value.toFixed(1)} kilograms
      </p>
    </div>
  );
}
