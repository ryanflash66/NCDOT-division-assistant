import { describe, expect, it } from "vitest";
import { PRINTED_PAGE_TITLE, pagesText, pagesTitle } from "@/panels/answers";
import { source } from "@/panels/fixtures";

// The page label of a source (DAR-654): the PDF index alone, or the printed page number first
// when the page prints another one (the TMP manual's p.13 is PDF page 37).

describe("pagesText", () => {
  it("names the PDF page, or pages, when the index has no printed number", () => {
    expect(pagesText(source(1, { page: 37, page_end: null }))).toBe("PDF page 37");
    expect(pagesText(source(1, { page: 37, page_end: 38 }))).toBe("PDF pages 37–38");
    expect(pagesText(source(1, { page: 37, page_end: 37 }))).toBe("PDF page 37");
    expect(pagesTitle(source(1, { page: 37 }))).toBeUndefined();
  });

  it("puts the printed page before the PDF page when they differ", () => {
    const s = source(1, { page: 37, page_end: null, printed_page: "13", printed_page_end: null });
    expect(pagesText(s)).toBe("p.13 (PDF p.37)");
    expect(pagesTitle(s)).toBe(PRINTED_PAGE_TITLE);
  });

  it("gives both ranges for a passage that spans pages", () => {
    const s = source(1, { page: 37, page_end: 38, printed_page: "13", printed_page_end: "14" });
    expect(pagesText(s)).toBe("pp.13–14 (PDF pp.37–38)");
    expect(pagesTitle(s)).toBe(PRINTED_PAGE_TITLE);
    // The same printed number on both PDF pages (a plate spread over two sheets).
    expect(pagesText(source(1, { page: 37, page_end: 38, printed_page: "13", printed_page_end: null }))).toBe(
      "p.13 (PDF pp.37–38)",
    );
  });

  it("keeps the plain label when the printed number is the PDF index", () => {
    expect(pagesText(source(1, { page: 5, page_end: null, printed_page: "5", printed_page_end: null }))).toBe("PDF page 5");
    expect(pagesText(source(1, { page: 5, page_end: 6, printed_page: "5", printed_page_end: "6" }))).toBe("PDF pages 5–6");
    expect(pagesTitle(source(1, { page: 5, printed_page: "5" }))).toBeUndefined();
  });

  it("is null without a page, whatever else the source says", () => {
    expect(pagesText(source(1, { page: null, printed_page: "13" }))).toBeNull();
    expect(pagesTitle(source(1, { page: null, printed_page: "13" }))).toBeUndefined();
  });
});
