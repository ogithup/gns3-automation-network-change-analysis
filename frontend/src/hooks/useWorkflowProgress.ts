import { useEffect } from "react";

import { createWorkflowSocket } from "../api/client";
import { useWorkflowStore } from "../app/workflowStore";

export function useWorkflowProgress(workflowId: string | null | undefined) {
  const { appendProgressEvent } = useWorkflowStore();

  useEffect(() => {
    if (!workflowId) {
      return undefined;
    }

    const socket = createWorkflowSocket(workflowId, {
      onMessage(event) {
        appendProgressEvent(workflowId, event);
      },
    });

    return () => {
      socket.close();
    };
  }, [appendProgressEvent, workflowId]);
}
