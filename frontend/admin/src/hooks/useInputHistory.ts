import { useCallback, useEffect, useRef, useState } from "react";

const STORAGE_KEY = "openvman.chat.history";
const MAX_ENTRIES = 50;

function readHistory(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((item): item is string => typeof item === "string").slice(0, MAX_ENTRIES);
  } catch {
    return [];
  }
}

function writeHistory(entries: string[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(entries.slice(0, MAX_ENTRIES)));
  } catch {
    // ignore quota/security errors
  }
}

function normalizeMessages(messages: string[]): string[] {
  return messages
    .map((message) => message.trim())
    .filter((message): message is string => message.length > 0);
}

export interface UseInputHistoryResult {
  push: (message: string) => void;
  seed: (messages: string[]) => void;
  onKeyDown: (
    event: React.KeyboardEvent<HTMLTextAreaElement>,
    currentValue: string,
    setValue: (next: string) => void,
  ) => boolean;
}

export function useInputHistory(): UseInputHistoryResult {
  const [history, setHistory] = useState<string[]>(() => readHistory());
  const historyRef = useRef(history);
  historyRef.current = history;

  // cursor: -1 = not cycling (showing draft); 0..n-1 = index into history
  const cursorRef = useRef<number>(-1);
  const draftRef = useRef<string>("");

  useEffect(() => {
    writeHistory(history);
  }, [history]);

  const resetBrowsing = useCallback((draft = "") => {
    cursorRef.current = -1;
    draftRef.current = draft;
  }, []);

  const restoreDraft = useCallback((setValue: (next: string) => void) => {
    const draft = draftRef.current;
    resetBrowsing();
    setValue(draft);
  }, [resetBrowsing]);

  const seed = useCallback((messages: string[]) => {
    // Input is chronological (oldest → newest); history stores newest-first.
    const cleaned = normalizeMessages(messages).reverse();
    if (cleaned.length === 0) return;
    setHistory((prev) => {
      const seen = new Set(prev);
      const additions: string[] = [];
      for (const message of cleaned) {
        if (seen.has(message)) continue;
        seen.add(message);
        additions.push(message);
      }
      if (additions.length === 0) return prev;
      return [...prev, ...additions].slice(0, MAX_ENTRIES);
    });
  }, []);

  const push = useCallback((message: string) => {
    const trimmed = message.trim();
    if (!trimmed) return;
    resetBrowsing();
    setHistory((prev) => {
      if (prev[0] === trimmed) return prev;
      return [trimmed, ...prev].slice(0, MAX_ENTRIES);
    });
  }, [resetBrowsing]);

  const onKeyDown = useCallback(
    (
      event: React.KeyboardEvent<HTMLTextAreaElement>,
      currentValue: string,
      setValue: (next: string) => void,
    ): boolean => {
      const list = historyRef.current;
      const key = event.key;

      if (key !== "ArrowUp" && key !== "ArrowDown" && key !== "Escape") {
        return false;
      }

      const target = event.currentTarget;
      const caretAtStart =
        target.selectionStart === 0 && target.selectionEnd === 0;
      const isEmpty = currentValue.length === 0;
      const inHistory = cursorRef.current >= 0;

      // Only engage when empty, caret at start, or already cycling.
      if (!isEmpty && !caretAtStart && !inHistory) {
        return false;
      }

      switch (key) {
      case "ArrowUp": {
        if (list.length === 0) return false;
        const nextIndex = Math.min(cursorRef.current + 1, list.length - 1);
        if (nextIndex === cursorRef.current) {
          event.preventDefault();
          return true;
        }
        if (cursorRef.current === -1) {
          draftRef.current = currentValue;
        }
        cursorRef.current = nextIndex;
        event.preventDefault();
        setValue(list[nextIndex]);
        return true;
      }
      case "ArrowDown": {
        if (!inHistory) return false;
        const nextIndex = cursorRef.current - 1;
        event.preventDefault();
        if (nextIndex < 0) {
          restoreDraft(setValue);
          return true;
        }
        cursorRef.current = nextIndex;
        setValue(list[nextIndex]);
        return true;
      }
      case "Escape":
        if (!inHistory) return false;
        event.preventDefault();
        restoreDraft(setValue);
        return true;
      default:
        return false;
      }
    },
    [restoreDraft],
  );

  return { push, seed, onKeyDown };
}
