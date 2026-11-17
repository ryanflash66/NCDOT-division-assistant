import { cleanup, render, screen } from "@testing-library/react";
import { AssistantRuntimeProvider, ThreadPrimitive, useLocalRuntime, type ThreadMessageLike } from "@assistant-ui/react";
import { afterEach, describe, expect, it } from "vitest";
import { AnswerFooter } from "@/components/assistant-ui/elements/answer";
import { answer, payload, question, source } from "@/panels/fixtures";

// The footer under each answer, read from the message's metadata in a real local runtime.
function Harness({ messages }: { messages: ThreadMessageLike[] }) {
  const runtime = useLocalRuntime({ run: async function* () {} }, { initialMessages: messages });
  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ThreadPrimitive.Messages>{() => <AnswerFooter />}</ThreadPrimitive.Messages>
    </AssistantRuntimeProvider>
  );
}

const ask = question("q1", "Who pays for a detour?");

afterEach(cleanup);

describe("AnswerFooter backup notice (DAR-735)", () => {
  it("shows the notice when the backup model wrote the answer", () => {
    render(<Harness messages={[ask, answer("a1", payload([source(1)], { backup_model: true }))]} />);
    expect(screen.getByText("Answered by the backup model.")).toBeTruthy();
    expect(screen.getByText(/double-check the cited page/)).toBeTruthy();
  });

  it("shows nothing when the main model answered, or for an answer saved before the flag", () => {
    render(
      <Harness
        messages={[
          ask,
          answer("a1", payload([source(1)], { backup_model: false })),
          question("q2", "And for a lane closure?"),
          answer("a2", payload([source(1)])),
        ]}
      />,
    );
    expect(screen.queryByText(/backup model/)).toBeNull();
  });

  it("says a refusal came from the backup model", () => {
    render(<Harness messages={[ask, answer("a1", payload([], { backup_model: true }))]} />);
    expect(screen.getByText("Checked by the backup model.")).toBeTruthy();
    expect(screen.queryByText(/double-check the cited page/)).toBeNull();
  });
});
