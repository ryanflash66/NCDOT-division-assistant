import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { AssistantRuntimeProvider, useAuiState, useLocalRuntime, type ThreadMessageLike } from "@assistant-ui/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { NewChatButton } from "@/components/assistant-ui/elements/new-chat-button";
import { answer, payload, question, source } from "@/panels/fixtures";
import { SourcesPanel } from "@/panels/SourcesPanel";
import { useApp } from "@/state";

// A real local runtime holds the thread, as in App.tsx, so the click goes through the
// runtime's own reset; the Sources panel sits next to it to show it empties too.
function Harness({ messages }: { messages: ThreadMessageLike[] }) {
  const runtime = useLocalRuntime({ run: async function* () {} }, { initialMessages: messages });
  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <NewChatButton />
      <textarea className="aui-composer-input" />
      <Count />
      <SourcesPanel />
    </AssistantRuntimeProvider>
  );
}

function Count() {
  const n = useAuiState((s) => s.thread.messages.length);
  return <output data-testid="count">{n}</output>;
}

const thread = [question("q1", "Who pays for a detour?"), answer("a1", payload([source(1)]))];

beforeEach(() => {
  useApp.setState({ activeAnswerId: null, activeAt: 0, focusedSource: null });
});
afterEach(cleanup);

describe("NewChatButton", () => {
  it("is a button named New chat", () => {
    render(<Harness messages={thread} />);
    const button = screen.getByRole("button", { name: "New chat" });
    expect(button.tagName).toBe("BUTTON");
    expect((button as HTMLButtonElement).disabled).toBe(false);
  });

  it("clears the thread and the sources panel, and moves the focus to the composer", () => {
    render(<Harness messages={thread} />);
    expect(screen.getByTestId("count").textContent).toBe("2");
    expect(screen.queryByText(/Passage 1 text/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "New chat" }));

    expect(screen.getByTestId("count").textContent).toBe("0");
    expect(screen.queryByText(/Passage 1 text/)).toBeNull();
    expect(screen.getByText(/The passages an answer uses appear here/)).toBeTruthy();
    expect(useApp.getState().activeAnswerId).toBeNull();
    expect(document.activeElement).toBe(document.querySelector(".aui-composer-input"));
  });

  it("stays in place but disabled when there is nothing to clear", () => {
    render(<Harness messages={[]} />);
    expect((screen.getByRole("button", { name: "New chat" }) as HTMLButtonElement).disabled).toBe(true);
  });
});
