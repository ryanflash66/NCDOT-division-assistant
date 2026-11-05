import { useAui } from "@assistant-ui/react";
import { AtSignIcon } from "lucide-react";
import {
  type ChangeEvent,
  type KeyboardEvent,
  type ReactNode,
  type RefObject,
  type SyntheticEvent,
  useId,
  useState,
} from "react";
import { cn } from "@/lib/utils";
import { findMention, matchDivisions, type Mention, removeMention, typedMention } from "@/mention";
import { useApp } from "@/state";
import type { Division } from "@/types";
import { warmUp } from "@/warm";

// The composer's @ picker (DAR-628): type @ to pick the division a question goes to, as in
// Slack. The picked division is the chip at the start of the composer, which always shows
// where the next question goes (with no @, the last division asked) and opens the same
// list when clicked. "I work in" and the left panel's Ask picker are unchanged.

/** Open from a typed @ (its place in the text) or from the chip (nothing to take out). */
type Open = { mention: Mention | null; active: number };

export function useDivisionMention(inputRef: RefObject<HTMLTextAreaElement | null>) {
  const aui = useAui();
  const divisions = useApp((s) => s.divisions);
  const target = useApp((s) => s.divisions.find((d) => d.id === s.target));
  const [open, setOpen] = useState<Open | null>(null);
  const listId = useId();

  const options = open ? matchDivisions(divisions, open.mention?.query ?? "") : [];
  const expanded = !!open && options.length > 0;
  const active = expanded ? Math.min(open.active, options.length - 1) : -1;

  /** `end`: where the @query ends; the caret, when picked from the list. */
  const pick = (division: Division, mention: Mention | null, end?: number) => {
    const el = inputRef.current;
    useApp.getState().setTarget(division.id);
    warmUp();
    setOpen(null);
    if (!el) return;
    let caret = el.selectionStart ?? el.value.length;
    if (mention) {
      const next = removeMention(el.value, mention, end ?? caret);
      aui.composer().setText(next.text);
      // A pasted question keeps the caret where it was, at the end; a picked @ puts it where the @ was.
      caret = end !== undefined && end < caret ? next.text.length - (el.value.length - caret) : next.caret;
    }
    el.focus();
    // After React has written the new text into the textarea.
    requestAnimationFrame(() => el.setSelectionRange(caret, caret));
  };

  const update = (text: string, caret: number) => {
    const typed = typedMention(text, caret, divisions);
    // "@Utilities " typed out or pasted in full: picked as if from the list. Deferred,
    // because the composer stores the typed text after this handler runs.
    if (typed) return queueMicrotask(() => pick(typed.division, typed.mention, typed.end));
    const mention = findMention(text, caret, divisions);
    if (!mention) return setOpen(null);
    setOpen((was) => ({ mention, active: was?.mention?.query === mention.query ? was.active : 0 }));
  };

  const onChange = (e: ChangeEvent<HTMLTextAreaElement>) =>
    update(e.target.value, e.target.selectionStart ?? e.target.value.length);

  // The caret moved (arrows, a click): the list follows whether it is still in an @.
  const onSelect = (e: SyntheticEvent<HTMLTextAreaElement>) => {
    if (!open?.mention) return;
    const el = e.currentTarget;
    update(el.value, el.selectionStart ?? el.value.length);
  };

  // Handled keys are prevented, so the composer doesn't also send on Enter.
  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (!expanded || e.nativeEvent.isComposing) return;
    const n = options.length;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const step = e.key === "ArrowDown" ? 1 : -1;
      setOpen({ ...open, active: (active + step + n) % n });
    } else if (e.key === "Enter" || e.key === "Tab") {
      if (e.shiftKey) return;
      e.preventDefault();
      pick(options[active]!, open.mention);
    } else if (e.key === "Escape") {
      e.preventDefault();
      setOpen(null);
    }
  };

  const onBlur = () => setOpen(null);

  const openFromChip = () => {
    if (open && !open.mention) return setOpen(null);
    const index = divisions.findIndex((d) => d.id === target?.id);
    setOpen({ mention: null, active: Math.max(index, 0) });
    inputRef.current?.focus();
  };

  const optionId = (i: number) => `${listId}-${i}`;

  const inputProps = {
    role: "combobox",
    "aria-autocomplete": "list" as const,
    "aria-expanded": expanded,
    "aria-controls": expanded ? listId : undefined,
    "aria-activedescendant": expanded ? optionId(active) : undefined,
    onChange,
    onSelect,
    onKeyDown,
    onBlur,
  };

  const chip: ReactNode = target ? (
    <button
      type="button"
      onClick={openFromChip}
      // Keeps the focus in the textarea, so the list it opens can be used from the keyboard.
      onMouseDown={(e) => e.preventDefault()}
      aria-label={`Asking ${target.name}. Change division`}
      title="Type @ to pick another division"
      className="aui-division-chip bg-accent text-accent-foreground hover:bg-accent/70 focus-visible:ring-ring/50 inline-flex max-w-full items-center gap-1 self-start rounded-full px-2 py-0.5 text-sm font-medium outline-none focus-visible:ring-2"
    >
      <AtSignIcon className="size-3.5 shrink-0" aria-hidden />
      <span className="truncate">{target.name}</span>
    </button>
  ) : null;

  const list: ReactNode = expanded ? (
    <div
      id={listId}
      role="listbox"
      aria-label="Divisions to ask"
      className="aui-division-list bg-popover text-popover-foreground absolute start-0 bottom-full z-20 mb-2 w-72 max-w-full overflow-hidden rounded-lg border p-1 shadow-md"
    >
      {options.map((d, i) => (
        <div
          key={d.id}
          id={optionId(i)}
          role="option"
          aria-selected={i === active}
          onMouseDown={(e) => e.preventDefault()}
          onMouseEnter={() => setOpen({ ...open!, active: i })}
          onClick={() => pick(d, open!.mention)}
          className={cn(
            "flex cursor-pointer items-baseline justify-between gap-3 rounded-md px-2.5 py-1.5 text-sm",
            i === active && "bg-accent text-accent-foreground",
          )}
        >
          <span>{d.name}</span>
          {d.id === target?.id && <span className="text-muted-foreground text-xs">asking now</span>}
        </div>
      ))}
    </div>
  ) : null;

  return { inputProps, chip, list };
}
