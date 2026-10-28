import { describe, expect, it } from "vitest";
import { formatPaise, parseRupeesToPaise } from "./money";

describe("formatPaise", () => {
  it.each([
    [0, "₹0.00"],
    [5, "₹0.05"],
    [29, "₹0.29"],
    [100, "₹1.00"],
    [123450, "₹1,234.50"],
    [12345678, "₹1,23,456.78"],
    [10000000000, "₹10,00,00,000.00"],
    [-18050, "-₹180.50"],
  ])("%i paise → %s", (paise, expected) => {
    expect(formatPaise(paise)).toBe(expected);
  });

  it("shows a dash when there is no amount", () => {
    expect(formatPaise(null)).toBe("n/a");
    expect(formatPaise(undefined)).toBe("n/a");
  });
});

describe("parseRupeesToPaise", () => {
  it.each([
    ["120", 12000],
    ["120.5", 12050],
    ["120.50", 12050],
    ["0.29", 29],
    [" 10 ", 1000],
  ])("%s → %i", (text, paise) => {
    expect(parseRupeesToPaise(text)).toBe(paise);
  });

  it.each(["", "abc", "-5", "1.234", "1e3", "1,000", ".5", "12."])("rejects %j", (text) => {
    expect(parseRupeesToPaise(text)).toBeNull();
  });
});
