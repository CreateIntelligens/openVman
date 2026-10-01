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
