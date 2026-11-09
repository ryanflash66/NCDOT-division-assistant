import type { Division } from "@/types";

// "@Utilities who pays for the detour?" (DAR-628): typing @ in the composer opens a list
// of divisions, and picking one makes it the division the question goes to. The pure
// part lives here, so it is tested without a browser.

/** An @ being typed: where it starts in the text and what follows it up to the caret. */
export type Mention = { start: number; query: string };

const norm = (s: string) => s.toLowerCase().replace(/\s+/g, " ");

/** The divisions an @query names: by the start of the name, of any of its words, or of the id. */
export function matchDivisions(divisions: Division[], query: string): Division[] {
  const q = norm(query).trim();
  if (!q) return divisions;
  return divisions.filter((d) => {
    const name = norm(d.name);
    return name.startsWith(q) || d.id.toLowerCase().startsWith(q) || name.split(" ").some((w) => w.startsWith(q));
  });
}

/**
 * The @ the caret is in, if any. The @ starts the text or follows a space, so an email
 * address doesn't open the list. Names have spaces ("Work Zone"), so the query may too,
 * but only while some division still matches it; past that the @ is plain text.
 */
export function findMention(text: string, caret: number, divisions: Division[]): Mention | null {
  const before = text.slice(0, caret);
  const start = before.lastIndexOf("@");
  if (start < 0) return null;
  if (start > 0 && !/\s/.test(before[start - 1]!)) return null;
  const query = before.slice(start + 1);
  if (query.includes("\n") || query.length > 40) return null;
  if (/\s/.test(query) && matchDivisions(divisions, query).length === 0) return null;
  return { start, query };
}

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/**
 * A division's full name or id written out after an @ and followed by a space, before the
 * caret: picked without the list. Typed letter by letter it fires on the space; pasted
 * ("@Utilities who pays for the detour?") it fires on the whole text. `end` is where
 * the name ends, so removeMention(text, mention, end) takes out just "@Utilities".
 */
export function typedMention(
  text: string,
  caret: number,
  divisions: Division[],
): { mention: Mention; end: number; division: Division } | null {
  const before = text.slice(0, caret);
  // Longest names first, so "Work Zone Traffic Control" wins over a shorter name it starts with.
  const names = divisions
    .flatMap((division) => [division.name, division.id].map((name) => ({ division, name })))
    .sort((a, b) => b.name.length - a.name.length);
  for (let at = before.indexOf("@"); at >= 0; at = before.indexOf("@", at + 1)) {
    if (at > 0 && !/\s/.test(before[at - 1]!)) continue;
    for (const { division, name } of names) {
      const pattern = new RegExp("^" + name.split(/\s+/).map(escape).join("\\s+") + "(?=\\s)", "i");
      const found = pattern.exec(before.slice(at + 1));
      if (found) {
        const end = at + 1 + found[0].length;
        return { mention: { start: at, query: found[0] }, end, division };
      }
    }
  }
  return null;
}

/** The text with the @query taken out (the division shows as the chip instead), and the caret there. */
export function removeMention(text: string, mention: Mention, caret: number): { text: string; caret: number } {
  let after = text.slice(caret);
  let head = text.slice(0, mention.start);
  // One space between the words either side, none at the start.
  if (head.endsWith(" ") || head === "") after = after.replace(/^ +/, "");
  else if (after !== "" && !after.startsWith(" ")) head += " ";
  return { text: head + after, caret: head.length };
}
