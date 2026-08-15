import { describe, expect, it } from "vitest";

import { parseWeightCsv } from "./csv";

/** Build a CSV body from rows, with the header the exports carry. */
function csv(...lines: string[]): string {
  return ["Date,Weight", ...lines].join("\n");
}

describe("parseWeightCsv", () => {
  it("parses a plain dd/mm/yyyy export", () => {
    const result = parseWeightCsv(csv("06/08/2026,82.4", "07/08/2026,82.1"));

    expect(result.days).toHaveLength(2);
    expect(result.days[0]).toMatchObject({ day: "2026-08-06", weightKg: 82.4 });
    expect(result.days[1]).toMatchObject({ day: "2026-08-07", weightKg: 82.1 });
    expect(result.skipped).toEqual([]);
  });

  it("returns days oldest first even when the file is newest first", () => {
    const result = parseWeightCsv(csv("07/08/2026,82.1", "06/08/2026,82.4"));

    expect(result.days.map((row) => row.day)).toEqual(["2026-08-06", "2026-08-07"]);
  });

  it("skips the header row without reporting it", () => {
    const result = parseWeightCsv(csv("06/08/2026,82.4"));

    expect(result.skipped).toEqual([]);
    expect(result.days).toHaveLength(1);
  });

  it("ignores blank lines, including a trailing newline", () => {
    const result = parseWeightCsv(csv("06/08/2026,82.4", "", "07/08/2026,82.1", ""));

    expect(result.days).toHaveLength(2);
    expect(result.skipped).toEqual([]);
  });

  it("handles CRLF line endings", () => {
    const result = parseWeightCsv("Date,Weight\r\n06/08/2026,82.4\r\n07/08/2026,82.1\r\n");

    expect(result.days).toHaveLength(2);
    expect(result.days[0]?.weightKg).toBe(82.4);
  });

  it("strips a UTF-8 BOM so the first data row still parses", () => {
    // Excel writes a BOM; without stripping it the first cell fails to match.
    const result = parseWeightCsv("﻿06/08/2026,82.4");

    expect(result.days).toHaveLength(1);
    expect(result.days[0]?.day).toBe("2026-08-06");
  });

  it("accepts hyphen-separated dates and a trailing unit on the weight", () => {
    const result = parseWeightCsv(csv("06-08-2026,82.4 kg"));

    expect(result.days[0]).toMatchObject({ day: "2026-08-06", weightKg: 82.4 });
  });

  it("reads a time when the date cell carries one", () => {
    const result = parseWeightCsv(csv("06/08/2026 07:30,82.4", "07/08/2026T08:05,82.1"));

    expect(result.days[0]?.time).toBe("07:30");
    expect(result.days[1]?.time).toBe("08:05");
  });

  it("pads a single-digit hour so times compare lexicographically", () => {
    const result = parseWeightCsv(csv("06/08/2026 7:30,82.4"));

    expect(result.days[0]?.time).toBe("07:30");
  });

  it("records no time when the date cell has none", () => {
    const result = parseWeightCsv(csv("06/08/2026,82.4"));

    expect(result.days[0]?.time).toBeNull();
  });

  describe("quoted fields", () => {
    it("splits on commas outside quotes only", () => {
      const result = parseWeightCsv(csv('"06/08/2026","82.4"'));

      expect(result.days[0]).toMatchObject({ day: "2026-08-06", weightKg: 82.4 });
    });

    it("honours a doubled quote inside a quoted field", () => {
      const result = parseWeightCsv(csv('"06/08/2026","82.4","a ""note"" here"'));

      expect(result.days[0]?.weightKg).toBe(82.4);
      expect(result.skipped).toEqual([]);
    });
  });

  describe("one row per day", () => {
    it("keeps the earliest weigh-in of a day and reports the rest", () => {
      const result = parseWeightCsv(
        csv("06/08/2026 07:30,82.4", "06/08/2026 19:00,83.1", "07/08/2026 08:00,82.1"),
      );

      expect(result.days).toHaveLength(2);
      expect(result.days[0]).toMatchObject({ day: "2026-08-06", weightKg: 82.4 });
      expect(result.duplicates).toHaveLength(1);
      expect(result.duplicates[0]?.weightKg).toBe(83.1);
    });

    it("prefers a row that has a time over one that does not", () => {
      const result = parseWeightCsv(csv("06/08/2026,83.1", "06/08/2026 07:30,82.4"));

      expect(result.days).toHaveLength(1);
      expect(result.days[0]?.weightKg).toBe(82.4);
      expect(result.duplicates[0]?.weightKg).toBe(83.1);
    });

    it("keeps the first of two rows that both lack a time", () => {
      const result = parseWeightCsv(csv("06/08/2026,82.4", "06/08/2026,83.1"));

      expect(result.days).toHaveLength(1);
      expect(result.days[0]?.weightKg).toBe(82.4);
      expect(result.duplicates).toHaveLength(1);
    });
  });

  describe("rejected rows", () => {
    it("skips a row whose date cannot be read", () => {
      const result = parseWeightCsv(csv("not a date,82.4"));

      expect(result.days).toEqual([]);
      expect(result.skipped).toHaveLength(1);
      expect(result.skipped[0]?.reason).toBe("could not read the date");
      expect(result.skipped[0]?.lineNumber).toBe(2);
    });

    it("skips a row whose weight cannot be read", () => {
      const result = parseWeightCsv(csv("06/08/2026,"));

      expect(result.skipped[0]?.reason).toBe("could not read the weight");
    });

    it("rejects an impossible calendar date rather than rolling it over", () => {
      // The Date constructor would turn 31 April into 1 May.
      const result = parseWeightCsv(csv("31/04/2026,82.4"));

      expect(result.days).toEqual([]);
      expect(result.skipped[0]?.reason).toBe("could not read the date");
    });

    it("rejects an mm/dd date, whose day part is not a real month", () => {
      const result = parseWeightCsv(csv("03/25/2026,82.4"));

      expect(result.days).toEqual([]);
      expect(result.skipped).toHaveLength(1);
    });

    it("skips weights outside the allowed range", () => {
      const result = parseWeightCsv(csv("06/08/2026,0.2", "07/08/2026,1200"));

      expect(result.days).toEqual([]);
      expect(result.skipped).toHaveLength(2);
      expect(result.skipped[0]?.reason).toContain("outside the allowed range");
    });

    it("keeps good rows alongside bad ones", () => {
      const result = parseWeightCsv(csv("06/08/2026,82.4", "rubbish", "08/08/2026,82.0"));

      expect(result.days).toHaveLength(2);
      expect(result.skipped).toHaveLength(1);
    });
  });

  describe("rounding", () => {
    it("rounds to the three decimal places the column stores and flags it", () => {
      const result = parseWeightCsv(csv("06/08/2026,82.44449"));

      expect(result.days[0]?.weightKg).toBe(82.444);
      expect(result.days[0]?.rounded).toBe(true);
      expect(result.roundedCount).toBe(1);
    });

    it("does not flag a value that already fits", () => {
      const result = parseWeightCsv(csv("06/08/2026,82.4"));

      expect(result.days[0]?.rounded).toBe(false);
      expect(result.roundedCount).toBe(0);
    });
  });

  describe("provesDayFirst", () => {
    // Without a day above 12 the file reads identically as mm/dd/yyyy, so the
    // caller has to warn rather than silently swapping day and month.
    it("is true when some row has a day above 12", () => {
      const result = parseWeightCsv(csv("06/08/2026,82.4", "13/08/2026,82.1"));

      expect(result.provesDayFirst).toBe(true);
    });

    it("is false when every row is ambiguous", () => {
      const result = parseWeightCsv(csv("06/08/2026,82.4", "07/08/2026,82.1"));

      expect(result.provesDayFirst).toBe(false);
    });
  });

  it("returns empty results for an empty file", () => {
    const result = parseWeightCsv("");

    expect(result.days).toEqual([]);
    expect(result.skipped).toEqual([]);
    expect(result.duplicates).toEqual([]);
    expect(result.provesDayFirst).toBe(false);
  });
});
