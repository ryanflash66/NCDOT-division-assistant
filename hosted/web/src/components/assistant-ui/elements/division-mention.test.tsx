import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { AssistantRuntimeProvider, useLocalRuntime, type ChatModelAdapter } from "@assistant-ui/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Thread } from "@/components/assistant-ui/elements/thread.aui";
import { TooltipProvider } from "@/components/ui/tooltip";
import { DIVISIONS } from "@/panels/fixtures";
import { useApp } from "@/state";

const asked: { text: string; target: string | null }[] = [];

const adapter: ChatModelAdapter = {
  async run({ messages }) {
    const last = messages.at(-1)!;
    const text = last.content.map((p) => (p.type === "text" ? p.text : "")).join("");
    asked.push({ text, target: useApp.getState().target });
    return { content: [{ type: "text", text: "ok" }] };
  },
};

function Harness() {
  const runtime = useLocalRuntime(adapter);
  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <TooltipProvider>
        <Thread autoFocus={false} />
      </TooltipProvider>
    </AssistantRuntimeProvider>
  );
}

beforeEach(() => {
  asked.length = 0;
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(null))));
  // jsdom has no ResizeObserver; the thread viewport uses it to size things.
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  // Asking Work Zone (the second division, as setDivisions does with the first as asker).
  act(() => {
    useApp.getState().setDivisions(DIVISIONS, 500);
    useApp.getState().setAsker("utilities");
    useApp.getState().setTarget("wztc");
  });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const input = () => screen.getByRole("combobox", { name: "Your question" }) as HTMLTextAreaElement;

function type(text: string) {
  const el = input();
  fireEvent.change(el, { target: { value: text, selectionStart: text.length, selectionEnd: text.length } });
}

describe("the composer's @ division picker", () => {
  it("shows where the question goes as a chip, before any @", () => {
    render(<Harness />);
    expect(screen.getByRole("button", { name: "Asking Work Zone Traffic Control. Change division" })).toBeTruthy();
    expect(input().getAttribute("aria-expanded")).toBe("false");
  });

  it("opens the list on @, filters it, and picks with the arrow keys and Enter", async () => {
    render(<Harness />);
    type("@");
    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Work Zone Traffic Controlasking now",
      "Utilities",
    ]);
    expect(input().getAttribute("aria-expanded")).toBe("true");
    fireEvent.keyDown(input(), { key: "ArrowDown" });
    expect(screen.getAllByRole("option")[1]!.getAttribute("aria-selected")).toBe("true");
    await act(async () => {
      fireEvent.keyDown(input(), { key: "Enter" });
    });
    expect(useApp.getState().target).toBe("utilities");
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(input().value).toBe("");
    // Enter picked the division; it didn't send the question.
    expect(asked).toEqual([]);
    expect(useApp.getState().asker).toBe("utilities");
  });

  it("picks by click and keeps the rest of the question", async () => {
    render(<Harness />);
    type("who pays? @ut");
    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual(["Utilities"]);
    await act(async () => {
      fireEvent.click(screen.getByRole("option"));
    });
    expect(useApp.getState().target).toBe("utilities");
    expect(input().value).toBe("who pays? ");
  });

  it("picks a division typed out in full", async () => {
    render(<Harness />);
    await act(async () => {
      type("@Utilities ");
      await Promise.resolve();
    });
    expect(useApp.getState().target).toBe("utilities");
    expect(input().value).toBe("");
  });

  it("picks a division pasted with the question", async () => {
    render(<Harness />);
    await act(async () => {
      type("@Utilities who pays for the detour?");
      await Promise.resolve();
    });
    expect(useApp.getState().target).toBe("utilities");
    expect(input().value).toBe("who pays for the detour?");
  });

  it("closes on Escape without changing the division", () => {
    render(<Harness />);
    type("@");
    fireEvent.keyDown(input(), { key: "Escape" });
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(useApp.getState().target).toBe("wztc");
  });

  it("opens the same list from the chip", () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: /Asking Work Zone/ }));
    expect(screen.getAllByRole("option")).toHaveLength(2);
    expect(screen.getAllByRole("option")[0]!.getAttribute("aria-selected")).toBe("true");
  });
});
