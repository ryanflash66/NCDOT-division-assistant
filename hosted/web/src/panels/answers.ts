import type { ThreadMessage } from "@assistant-ui/react";
import type { AnswerMetadata, Source } from "@/types";

// Which answer the right panel shows, read from assistant-ui's thread, where the runtime
// adapter (DAR-631) leaves each answer's payload in its message's metadata.custom.

export type ShownAnswer = {
  id: string;
  question: string;
  sources: Source[];
};

function payloadOf(message: ThreadMessage) {
  return (message.metadata.custom as AnswerMetadata | undefined)?.payload;
}

function isFinished(message: ThreadMessage): boolean {
  return message.role === "assistant" && message.status?.type === "complete" && !!payloadOf(message);
}

/** The text of the question an answer replies to: the user message before it. */
function questionBefore(messages: readonly ThreadMessage[], index: number): string {
  for (let i = index - 1; i >= 0; i--) {
    const m = messages[i];
    if (m.role !== "user") continue;
    return m.content
      .map((part) => (part.type === "text" ? part.text : ""))
      .join(" ")
      .trim();
  }
  return "";
}

/**
 * The answer picked with a citation click or showAnswer (activeId, picked at activeAt), or
 * the newest finished answer when none is picked, the picked one has left the thread, or a
 * newer answer started after the pick: the old page switched to each answer as it finished,
 * and this keeps doing that whether or not the adapter calls showAnswer. Only finished
 * answers with a payload count, so a reply still streaming or an error leaves the panel on
 * the last real answer.
 */
export function pickAnswer(
  messages: readonly ThreadMessage[],
  activeId: string | null,
  activeAt: number,
): ShownAnswer | null {
  let newest = -1;
  let picked = -1;
  messages.forEach((m, i) => {
    if (!isFinished(m)) return;
    newest = i;
    if (m.id === activeId) picked = i;
  });
  if (newest < 0) return null;
  const startedAfterPick = +messages[newest].createdAt > activeAt;
  const index = picked >= 0 && !startedAfterPick ? picked : newest;
  const message = messages[index];
  const sources = payloadOf(message)?.sources;
  return {
    id: message.id,
    question: questionBefore(messages, index),
    sources: Array.isArray(sources) ? sources : [],
  };
}

/** What a page label showing a printed page number means, for its title attribute. */
export const PRINTED_PAGE_TITLE = "Printed page number (PDF page index)";

/**
 * The printed page number(s) of a source, [first, last], when the index knows them and they
 * differ from the PDF index; null otherwise (older saved answers have no printed pages).
 */
function printedPages(source: Source): [string, string] | null {
  const first = source.printed_page;
  if (!first || !source.page) return null;
  const last = source.printed_page_end || first;
  const sameAsPdf = first === String(source.page) && last === String(source.page_end || source.page);
  return sameAsPdf ? null : [first, last];
}

/**
 * "PDF page 12" or "PDF pages 12–13", or null when the page is unknown. When the page prints
 * another number (DAR-654), that comes first: "p.13 (PDF p.37)", "pp.13–14 (PDF pp.37–38)".
 * Readers check a citation against the printed number (Dr. Namian read "page 37" as wrong
 * because the page prints "13"), while the link can only open the PDF at its index.
 */
export function pagesText(source: Source): string | null {
  if (!source.page) return null;
  const range = !!source.page_end && source.page_end !== source.page;
  const printed = printedPages(source);
  if (!printed) return range ? `PDF pages ${source.page}–${source.page_end}` : `PDF page ${source.page}`;
  const pdf = range ? `PDF pp.${source.page}–${source.page_end}` : `PDF p.${source.page}`;
  const [first, last] = printed;
  return first === last ? `p.${first} (${pdf})` : `pp.${first}–${last} (${pdf})`;
}

/** The title attribute for pagesText's label: set only when it shows a printed page number. */
export function pagesTitle(source: Source): string | undefined {
  return printedPages(source) ? PRINTED_PAGE_TITLE : undefined;
}
