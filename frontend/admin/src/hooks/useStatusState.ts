import { useCallback, useState } from "react";

export type Status = { type: "success" | "error"; message: string } | null;

export function useStatusState() {
  const [status, setStatus] = useState<Status>(null);

  const setErrorStatus = useCallback((error: unknown) => {
    const message = error instanceof Error ? error.message : String(error);
    setStatus({ type: "error", message });
  }, []);

  return { status, setStatus, setErrorStatus } as const;
}
