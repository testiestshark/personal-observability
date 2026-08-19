import { afterEach, describe, expect, it, vi } from "vitest";

import {
  currentLondonDay,
  currentLondonMonth,
  formatDayLabel,
  formatEntryDay,
  formatMonthLabel,
  formatWeight,
  fromKilograms,
  londonDayKey,
  londonDayToInstant,
  parseMonthKey,
  shiftMonth,
} from "./units";

// Intl output varies between ICU versions, so the human-facing labels are
// asserted by their parts rather than as exact strings — a CI runner on a
// different Node build should not turn this suite red. The day keys are asserted
// exactly, because en-CA's YYYY-MM-DD is stable.

describe("fromKilograms", () => {
  it("returns kilograms unchanged", () => {
    expect(fromKilograms(82.4, "kg")).toBe(82.4);
  });

  it("converts to pounds", () => {
    expect(fromKilograms(100, "lb")).toBeCloseTo(220.462, 3);
  });

  it("converts to stone", () => {
    expect(fromKilograms(100, "st")).toBeCloseTo(15.747, 3);
  });
});

describe("formatWeight", () => {
  it("renders one decimal place with the unit suffix", () => {
    expect(formatWeight(82.44, "kg")).toBe("82.4 kg");
  });

  // The reason the function rounds at all: 12.6 st stored as kilograms comes
  // back as 12.599999…, which must not reach the screen.
  it("does not leak floating-point noise from a round trip", () => {
    const kilograms = (12.6 * 14) / 2.2046226218487757;
    expect(formatWeight(kilograms, "st")).toBe("12.6 st");
  });
});

describe("londonDayKey", () => {
  // The bug fixed in bef8fb0: during BST, 23:30 UTC is already tomorrow in
  // London, and the entry used to be listed under the previous day.
  it("treats a late-evening BST instant as the next London day", () => {
    expect(londonDayKey("2026-08-11T23:30:00Z")).toBe("2026-08-12");
  });

  it("leaves the same instant alone in winter, when London is on GMT", () => {
    expect(londonDayKey("2026-01-11T23:30:00Z")).toBe("2026-01-11");
  });

  it("keeps an early-morning BST instant on its own day", () => {
    expect(londonDayKey("2026-08-12T00:30:00Z")).toBe("2026-08-12");
  });

  it("uses London time rather than UTC across the BST start boundary", () => {
    // BST begins 01:00 UTC on 29 March 2026.
    expect(londonDayKey("2026-03-29T01:30:00Z")).toBe("2026-03-29");
  });
});

describe("londonDayToInstant", () => {
  it("stores a day at noon UTC", () => {
    expect(londonDayToInstant("2026-08-06")).toBe("2026-08-06T12:00:00.000Z");
  });

  // The property that matters: whatever instant is chosen for a day must read
  // back as that same day in London. Noon UTC is what makes this hold in both
  // GMT and BST, and this covers every DST transition in the year at once.
  it("round-trips every day of a year back to itself", () => {
    const failures: string[] = [];

    for (let offset = 0; offset < 365; offset += 1) {
      const date = new Date(Date.UTC(2026, 0, 1 + offset));
      const day = date.toISOString().slice(0, 10);

      const roundTripped = londonDayKey(londonDayToInstant(day));
      if (roundTripped !== day) failures.push(`${day} -> ${roundTripped}`);
    }

    expect(failures).toEqual([]);
  });
});

describe("formatDayLabel", () => {
  it("labels a day with its weekday, date, month and year", () => {
    const label = formatDayLabel("2026-08-06");
    // 6 August 2026 is a Thursday.
    expect(label).toContain("Thu");
    expect(label).toContain("06");
    expect(label).toContain("Aug");
    expect(label).toContain("2026");
  });

  it("does not drift to a neighbouring day at the start of a month", () => {
    expect(formatDayLabel("2026-08-01")).toContain("01");
    expect(formatDayLabel("2026-08-01")).toContain("Aug");
  });
});

describe("formatEntryDay", () => {
  it("shows no time of day", () => {
    // The symptom that prompted the fix: every history row read "13:00".
    expect(formatEntryDay("2026-08-06T12:00:00.000Z")).not.toMatch(/\d{2}:\d{2}/);
  });

  it("agrees with the calendar on which day a late BST entry belongs to", () => {
    const timestamp = "2026-08-11T23:30:00Z";
    expect(formatEntryDay(timestamp)).toBe(formatDayLabel(londonDayKey(timestamp)));
    expect(formatEntryDay(timestamp)).toContain("12");
  });
});

describe("parseMonthKey", () => {
  it("splits a month key into numbers", () => {
    expect(parseMonthKey("2026-08")).toEqual({ year: 2026, monthNumber: 8 });
  });

  it("does not treat a leading zero as octal", () => {
    expect(parseMonthKey("2026-09")).toEqual({ year: 2026, monthNumber: 9 });
  });
});

describe("formatMonthLabel", () => {
  it("names the month and year", () => {
    const label = formatMonthLabel("2026-08");
    expect(label).toContain("August");
    expect(label).toContain("2026");
  });

  // Formatting mid-month exists so an offset at a boundary cannot pull the
  // label into the month either side.
  it("does not slip a month in midwinter or midsummer", () => {
    expect(formatMonthLabel("2026-01")).toContain("January");
    expect(formatMonthLabel("2026-12")).toContain("December");
  });
});

describe("shiftMonth", () => {
  it("steps forward within a year", () => {
    expect(shiftMonth("2026-08", 1)).toBe("2026-09");
  });

  it("steps backward within a year", () => {
    expect(shiftMonth("2026-08", -1)).toBe("2026-07");
  });

  it("rolls over the end of a year", () => {
    expect(shiftMonth("2026-12", 1)).toBe("2027-01");
  });

  it("rolls back over the start of a year", () => {
    expect(shiftMonth("2026-01", -1)).toBe("2025-12");
  });

  it("pads a single-digit month", () => {
    expect(shiftMonth("2026-12", 2)).toBe("2027-02");
  });

  it("returns the same month for a zero step", () => {
    expect(shiftMonth("2026-08", 0)).toBe("2026-08");
  });
});

describe("current London day and month", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("reports the next day when it is already tomorrow in London", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-11T23:30:00Z"));

    expect(currentLondonDay()).toBe("2026-08-12");
    expect(currentLondonMonth()).toBe("2026-08");
  });

  it("rolls the month over when a BST evening ends the month", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-31T23:30:00Z"));

    expect(currentLondonDay()).toBe("2026-09-01");
    expect(currentLondonMonth()).toBe("2026-09");
  });
});
