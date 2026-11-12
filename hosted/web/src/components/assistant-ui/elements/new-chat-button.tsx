import type { FC } from "react";
import { useAui, useAuiState } from "@assistant-ui/react";
import { PlusIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useApp } from "@/state";
import { isNewChatView } from "./thread.aui";

/**
 * New chat, in the page header where ChatGPT and Claude put it (DAR-668; it used to be a
 * small button under the composer that testers could not find). The one reset path:
 * the runtime's thread reset (the saved thread follows it, see App.tsx) and the Sources
 * panel back to its empty text. Disabled, not hidden, while there is nothing to clear
 * or an answer is still running, so the control is always in the same place.
 * Below 640 px only the plus shows (the header also holds the two drawer buttons at
 * 375 px); the name stays for screen readers.
 */
export const NewChatButton: FC = () => {
  const aui = useAui();
  const empty = useAuiState(isNewChatView);
  const running = useAuiState((s) => s.thread.isRunning);
  const newChat = () => {
    if (aui.thread().getState().isRunning) return;
    aui.thread().reset();
    useApp.getState().showAnswer(null);
    // The composer is where the next question goes, so the focus goes there, not to the page.
    document.querySelector<HTMLTextAreaElement>(".aui-composer-input")?.focus();
  };
  return (
    <Button type="button" variant="outline" size="sm" title="New chat" disabled={empty || running} onClick={newChat}>
      <PlusIcon aria-hidden="true" />
      <span className="max-sm:sr-only">New chat</span>
    </Button>
  );
};
