import { describe, expect, it } from "vitest";
import { findMention, matchDivisions, removeMention, typedMention } from "@/mention";
import { DIVISIONS } from "@/panels/fixtures";

const names = (q: string) => matchDivisions(DIVISIONS, q).map((d) => d.id);

describe("matchDivisions", () => {
  it("lists every division for a bare @", () => {
    expect(names("")).toEqual(["wztc", "utilities"]);
  });
  it("matches the start of the name, of any word in it, or of the id", () => {
    expect(names("util")).toEqual(["utilities"]);
    expect(names("zone")).toEqual(["wztc"]);
    expect(names("WZ")).toEqual(["wztc"]);
    expect(names("work zone t")).toEqual(["wztc"]);
    expect(names("xyz")).toEqual([]);
  });
});

describe("findMention", () => {
  it("finds the @ the caret is in, at the start or after a space", () => {
    expect(findMention("@Ut", 3, DIVISIONS)).toEqual({ start: 0, query: "Ut" });
    expect(findMention("hi @", 4, DIVISIONS)).toEqual({ start: 3, query: "" });
  });
  it("ignores an @ inside a word, such as an email address", () => {
    expect(findMention("me@ncdot.gov", 12, DIVISIONS)).toBeNull();
  });
  it("lets a query run past a space while a name still matches it", () => {
    expect(findMention("@Work Zone", 10, DIVISIONS)).toEqual({ start: 0, query: "Work Zone" });
    expect(findMention("@Utilities who pays", 19, DIVISIONS)).toBeNull();
  });
  it("only looks before the caret", () => {
    expect(findMention("who pays @", 3, DIVISIONS)).toBeNull();
  });
});

describe("typedMention", () => {
  it("picks a division written out in full and followed by a space", () => {
    expect(typedMention("@utilities ", 11, DIVISIONS)).toEqual({
      mention: { start: 0, query: "utilities" },
      end: 10,
      division: DIVISIONS[1],
    });
    expect(typedMention("hi @WZTC ", 9, DIVISIONS)?.division.id).toBe("wztc");
  });
  it("picks one pasted with the question after it", () => {
    const text = "@Work Zone Traffic Control when is a flagger needed?";
    const typed = typedMention(text, text.length, DIVISIONS)!;
    expect(typed.division.id).toBe("wztc");
    expect(removeMention(text, typed.mention, typed.end).text).toBe("when is a flagger needed?");
  });
  it("waits while the name is still being typed", () => {
    expect(typedMention("@utilities", 10, DIVISIONS)).toBeNull();
    expect(typedMention("@work ", 6, DIVISIONS)).toBeNull();
    expect(typedMention("me@utilities ", 13, DIVISIONS)).toBeNull();
  });
});

describe("removeMention", () => {
  it("takes the @query out and leaves one space between the words", () => {
    expect(removeMention("@Ut who pays?", { start: 0, query: "Ut" }, 3)).toEqual({ text: "who pays?", caret: 0 });
    expect(removeMention("who pays @Ut", { start: 9, query: "Ut" }, 12)).toEqual({ text: "who pays ", caret: 9 });
    expect(removeMention("who @Ut pays", { start: 4, query: "Ut" }, 7)).toEqual({ text: "who pays", caret: 4 });
  });
});
