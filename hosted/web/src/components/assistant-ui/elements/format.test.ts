import { describe, expect, it } from "vitest";
import { unverifiedText } from "./format";

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
