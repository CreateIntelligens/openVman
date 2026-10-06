/**
 * Quick Q&A panel copy and visibility rules, kept free of Vue so tests can run them directly.
 *
 * 快速問答第一層可以是「中文／English／Español」這種語言分類（鶴記 2026-10-01 起）。
 * 選了 English 之後按鈕和提示還是中文，訪客看不懂怎麼返回；所以介面語言跟著
 * 路徑上的語言分類走，還沒選語言時用中文。
 */

export type QuickQaLanguage = "zh" | "en" | "es" | "ja" | "ko";

export interface QuickQaCopy {
  title: string;
  back: string;
  backHint: string;
  close: string;
  loading: string;
  empty: string;
  retry: string;
  loadFailed: string;
}

const COPY: Record<QuickQaLanguage, QuickQaCopy> = {
  zh: {
    title: "快速問題", back: "返回", backHint: "返回上一層", close: "關閉",
    loading: "正在載入問答分類...", empty: "此分類尚無問答內容", retry: "重新整理",
    loadFailed: "載入問答分類失敗",
  },
  en: {
    title: "Quick questions", back: "Back", backHint: "Back to the previous level", close: "Close",
    loading: "Loading questions...", empty: "No questions in this category yet", retry: "Retry",
    loadFailed: "Could not load the questions",
  },
  es: {
    title: "Preguntas rápidas", back: "Volver", backHint: "Volver al nivel anterior", close: "Cerrar",
    loading: "Cargando preguntas...", empty: "Esta categoría aún no tiene preguntas", retry: "Reintentar",
    loadFailed: "No se pudieron cargar las preguntas",
  },
  ja: {
    title: "よくある質問", back: "戻る", backHint: "前の階層に戻る", close: "閉じる",
    loading: "質問を読み込み中...", empty: "このカテゴリにはまだ質問がありません", retry: "再読み込み",
    loadFailed: "質問を読み込めませんでした",
  },
  ko: {
    title: "빠른 질문", back: "뒤로", backHint: "이전 단계로", close: "닫기",
    loading: "질문을 불러오는 중...", empty: "이 분류에는 아직 질문이 없습니다", retry: "다시 시도",
    loadFailed: "질문을 불러오지 못했습니다",
  },
};

// 語言分類的名稱照該語言自己的寫法；比對時忽略大小寫與前後空白。
const LANGUAGE_LABELS: Record<string, QuickQaLanguage> = {
  "中文": "zh", "華語": "zh", "繁體中文": "zh",
  "english": "en",
  "español": "es", "espanol": "es",
  "日本語": "ja",
  "한국어": "ko",
};

export function languageOfLabel(label: string): QuickQaLanguage | null {
  return LANGUAGE_LABELS[label.trim().toLowerCase()] ?? null;
}

/** The panel language: the deepest language category on the path, else Chinese. */
export function quickQaLanguage(path: Array<{ label?: string }>): QuickQaLanguage {
  for (let index = path.length - 1; index >= 0; index -= 1) {
    const language = languageOfLabel(path[index].label ?? "");
    if (language) return language;
  }
  return "zh";
}

export function quickQaCopy(language: QuickQaLanguage): QuickQaCopy {
  return COPY[language];
}

/** Topics hidden in the admin console stay out of the avatar menu. */
export function visibleNodes<T extends { hidden?: boolean }>(nodes: T[] | undefined): T[] {
  return (nodes ?? []).filter((node) => !node.hidden);
}

export interface SuggestedQuestion {
  /** 按鈕上顯示的題目。 */
  label: string;
  /** 實際送出的文字：跟快速問答面板一樣前面帶主題，檢索才找得到同一題。 */
  message: string;
  sourcePath?: string;
}

interface SuggestionNode {
  label?: string;
  node_id?: string;
  order?: number;
  hidden?: boolean;
  qa_entries?: Array<{ question: string; source_path?: string; hidden?: boolean }>;
  children?: SuggestionNode[];
}

/**
 * 輸入框上方的推薦問題：從快速問答各主題輪流挑題，讓來賓一眼看到能問什麼。
 *
 * 每個主題先拿第一題，不夠再回頭拿第二題：主題多時各取一題，只有一個主題（例如鶴記
 * 94 題都在同一類）時也湊得滿。第一層是語言分類時只看中文那一類（沒有中文就看第一個），
 * 不然中英西混在一起。
 */
export function suggestedQuestions(nodes: SuggestionNode[] | undefined, limit = 4): SuggestedQuestion[] {
  const byOrder = (list: SuggestionNode[] | undefined) =>
    [...visibleNodes(list)].sort((a, b) => (a.order ?? 0) - (b.order ?? 0));
  let roots = byOrder(nodes);
  const languages = roots.filter((node) => languageOfLabel(node.label ?? ""));
  if (languages.length) {
    const chinese = languages.find((node) => languageOfLabel(node.label ?? "") === "zh") ?? languages[0];
    roots = byOrder(chinese.children);
  }
  const topics: Array<{ topic: string; entries: Array<{ question: string; source_path?: string }> }> = [];
  const walk = (list: SuggestionNode[]) => {
    for (const node of list) {
      const entries = (node.qa_entries ?? []).filter((item) => !item.hidden);
      if (entries.length) topics.push({ topic: (node.label || node.node_id || "").trim(), entries });
      walk(byOrder(node.children));
    }
  };
  walk(roots);
  const picked: SuggestedQuestion[] = [];
  for (let round = 0; picked.length < limit && topics.some((t) => t.entries.length > round); round++) {
    for (const { topic, entries } of topics) {
      const entry = entries[round];
      if (!entry || picked.length >= limit) continue;
      picked.push({
        label: entry.question,
        message: topic ? `${topic} ${entry.question}` : entry.question,
        sourcePath: entry.source_path,
      });
    }
  }
  return picked;
}
