// Text for the answer's steps and footer, as the old page wrote it (public/js/render.js,
// steps.js, docs.js).

export function seconds(ms: number): string {
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

/** "nvidia/nemotron-3-ultra-550b-a55b:free" -> "nemotron-3-ultra-550b-a55b"; the full id is the tooltip. */
export function modelName(id: string): string {
  return String(id).replace(/^[^/]*\//, "").replace(/:free$/, "");
}

export function count(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

/** "Searched 412 passages in 1 document." / "… in 1 of 2 documents." */
export function searchedText(searched: { documents: number; passages: number }, total: number): string {
  const documents = searched.documents < total ? `${searched.documents} of ${total} documents` : count(searched.documents, "document");
  return `Searched ${count(searched.passages, "passage")} in ${documents}.`;
}

/**
 * The answer's [n] markers as Markdown links to #cite-n, which the answer's link
 * component draws as citation buttons. A marker without a source (n out of 1..sources)
 * is dropped, as the old page did.
 */
export function linkCitations(text: string, sources: number): string {
  return text.replace(/\[(\d+)\]/g, (_, digits: string) => {
    const n = Number(digits);
    return n >= 1 && n <= sources ? `[${n}](#cite-${n})` : "";
  });
}

/** "Unverified number: 27.5 ft." / "Unverified numbers: 27.5 ft, 12 %."; null when every number was found. */
export function unverifiedText(numbers: string[] | null | undefined): string | null {
  if (!numbers?.length) return null;
  return `Unverified number${numbers.length === 1 ? "" : "s"}: ${numbers.join(", ")}.`;
}

/**
 * The unverified numbers split by why they are flagged: `missing` ones aren't in the cited pages
 * (DAR-659), `disputed` ones a second model reading the same pages contradicted (DAR-663). The
 * payload doesn't say whether a contradicted number was also missing, so it is listed as disputed.
 */
export function unverifiedReasons(
  numbers: string[] | null | undefined,
  disagreed: string[] | null | undefined,
): { missing: string[]; disputed: string[] } {
  const all = numbers ?? [];
  const contradicted = new Set(disagreed ?? []);
  return { missing: all.filter((n) => !contradicted.has(n)), disputed: all.filter((n) => contradicted.has(n)) };
}

/** "A second model reading the same pages gave 27.42 ft instead"; the footer adds the rest of the sentence. */
export function disputedText(numbers: string[] | null | undefined): string {
  return numbers?.length
    ? `A second model reading the same pages gave ${numbers.join(", ")} instead`
    : "A second model reading the same pages gave a different number";
}

/**
 * The notice under a reply a free backup model wrote because OpenAI couldn't answer (DAR-735),
 * or null. The flag comes from the server (`backup_model`), never from the model's name: without
 * LLM_PROVIDER=openai every model is a free one and the server leaves it false.
 */
export function backupNotice(payload: {
  backup_model?: boolean;
  refused: boolean;
  uncited: boolean;
}): { title: string; text: string } | null {
  if (!payload.backup_model) return null;
  if (payload.refused) {
    return {
      title: "Checked by the backup model.",
      text: "The main model couldn't answer just now, so it may have missed this; ask again later to have the main model look.",
    };
  }
  return {
    title: "Answered by the backup model.",
    text: payload.uncited
      ? "The main model couldn't answer just now; check the answer in the documents before relying on it."
      : "The main model couldn't answer just now; double-check the cited page before relying on it.",
  };
}

/** "Checked answer, Nov 20, 2026." from the YYYY-MM-DD a person checked it (DAR-673); the date as sent if it isn't one. */
export function checkedText(checkedOn: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(checkedOn);
  if (!match) return `Checked answer, ${checkedOn}.`;
  const [, year, month, day] = match;
  const when = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day)));
  const shown = when.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
  return `Checked answer, ${shown}.`;
}

export const CITE_PREFIX = "#cite-";
