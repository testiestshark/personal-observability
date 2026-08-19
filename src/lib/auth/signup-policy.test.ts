import { describe, expect, it } from "vitest";

import { parseSignupFlag } from "./signup-policy";

describe("parseSignupFlag", () => {
  it("enables signup only for the exact string true", () => {
    expect(parseSignupFlag("true")).toBe(true);
  });

  it("accepts the casing and padding a .env file tends to produce", () => {
    expect(parseSignupFlag("TRUE")).toBe(true);
    expect(parseSignupFlag("True")).toBe(true);
    expect(parseSignupFlag("  true  ")).toBe(true);
  });

  // The important half. A build that never saw the flag must not ship open
  // registration, so every unrecognised value has to land on false rather than
  // being treated as "set, therefore on".
  it("fails closed when the flag is missing or empty", () => {
    expect(parseSignupFlag(undefined)).toBe(false);
    expect(parseSignupFlag("")).toBe(false);
    expect(parseSignupFlag("   ")).toBe(false);
  });

  it("fails closed for truthy-looking values that are not true", () => {
    expect(parseSignupFlag("1")).toBe(false);
    expect(parseSignupFlag("yes")).toBe(false);
    expect(parseSignupFlag("on")).toBe(false);
    expect(parseSignupFlag("enabled")).toBe(false);
    expect(parseSignupFlag("ture")).toBe(false);
  });

  it("fails closed for explicit false", () => {
    expect(parseSignupFlag("false")).toBe(false);
    expect(parseSignupFlag("FALSE")).toBe(false);
  });
});
