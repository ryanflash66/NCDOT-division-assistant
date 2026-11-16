import { describe, expect, it } from "vitest";
import { disputedText, unverifiedReasons, unverifiedText } from "./format";

describe("unverifiedText", () => {
  it("names the numbers the cited pages don't contain", () => {
    expect(unverifiedText(["27.5 ft"])).toBe("Unverified number: 27.5 ft.");
    expect(unverifiedText(["27.5 ft", "12 %"])).toBe("Unverified numbers: 27.5 ft, 12 %.");
  });

  it("is null when every number was found, or for an answer saved before the check", () => {
    expect(unverifiedText([])).toBeNull();
    expect(unverifiedText(undefined)).toBeNull();
  });
});

describe("unverifiedReasons", () => {
  it("separates numbers missing from the pages from numbers a second model contradicted", () => {
    expect(unverifiedReasons(["9.5", "31.07 ft"], ["31.07 ft"])).toEqual({ missing: ["9.5"], disputed: ["31.07 ft"] });
  });

  it("treats every number as missing without a second opinion (the setting off, or an older answer)", () => {
    expect(unverifiedReasons(["27.5 ft"], undefined)).toEqual({ missing: ["27.5 ft"], disputed: [] });
    expect(unverifiedReasons(undefined, undefined)).toEqual({ missing: [], disputed: [] });
  });
});

describe("disputedText", () => {
  it("says what the second model read", () => {
    expect(disputedText(["27.42 ft"])).toBe("A second model reading the same pages gave 27.42 ft instead");
    expect(disputedText([])).toBe("A second model reading the same pages gave a different number");
  });
});
