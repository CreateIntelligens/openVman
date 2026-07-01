import { useEffect, useMemo, useState } from "react";
import { fetchKnowledgeQaEntries, type KnowledgeQaEntry } from "../api";
import { fallbackStarterPrompts } from "../components/chat/helpers";

const STARTER_PROMPT_COUNT = 6;

function pickRandom<T>(items: T[], count: number): T[] {
  const shuffled = [...items];
  for (let i = shuffled.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
  }
  return shuffled.slice(0, count);
}

export function useStarterPrompts() {
  const [entries, setEntries] = useState<KnowledgeQaEntry[]>([]);

  useEffect(() => {
    let cancelled = false;
    fetchKnowledgeQaEntries()
      .then((response) => {
        if (!cancelled) setEntries(response.entries);
      })
      .catch(() => {
        if (!cancelled) setEntries([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return useMemo(() => {
    if (entries.length === 0) {
      return fallbackStarterPrompts as readonly string[];
    }
    return pickRandom(
      entries.map((entry) => entry.question),
      STARTER_PROMPT_COUNT,
    );
  }, [entries]);
}
