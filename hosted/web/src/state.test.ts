import { describe, expect, it } from "vitest";
import { DIVISIONS } from "@/panels/fixtures";
import { ALL_DIVISIONS, allDivisions, askable, askableById, selectedDocuments } from "@/state";

// "All divisions" (DAR-666): offered after the divisions, never as "I work in".
describe("All divisions", () => {
  it("is every division's documents and passages, offered last", () => {
    const all = allDivisions(DIVISIONS);
    expect(all.id).toBe(ALL_DIVISIONS);
    expect(all.documents.map((d) => d.file)).toEqual(["tmp.pdf", "flagger.pdf", "uam.pdf"]);
    expect(all.passages).toBe(210);
    expect(askable(DIVISIONS).map((d) => d.id)).toEqual(["wztc", "utilities", "all"]);
    expect(askable([])).toEqual([]);
    expect(askableById(DIVISIONS, "all")?.name).toBe("All divisions");
    expect(askableById(DIVISIONS, "utilities")?.name).toBe("Utilities");
    expect(askableById(DIVISIONS, "nope")).toBeUndefined();
  });

  it("searches every document when all are ticked, else every division's ticked ones", () => {
    expect(selectedDocuments({ divisions: DIVISIONS, unticked: {} }, "all")).toBeNull();
    expect(selectedDocuments({ divisions: DIVISIONS, unticked: { wztc: { "tmp.pdf": true } } }, "all")).toEqual([
      "flagger.pdf",
      "uam.pdf",
    ]);
    // One division's selection is unchanged.
    expect(selectedDocuments({ divisions: DIVISIONS, unticked: { wztc: { "tmp.pdf": true } } }, "utilities")).toBeNull();
  });
});
