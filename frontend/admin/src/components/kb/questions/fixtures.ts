import type { QaAllQuestions, QaQuestionRow } from "../../../api/knowledge";

export function question(overrides: Partial<QaQuestionRow> & Pick<QaQuestionRow, "id" | "question">): QaQuestionRow {
  return {
    answer: "答案",
    image: "",
    url: "",
    language: "zh",
    source: { kind: "file", path: "knowledge/qa/faq.csv", label: "faq.csv" },
    category_ids: ["svc"],
    category_hidden: false,
    hidden_in_file: false,
    off_menu: null,
    no_answer: false,
    document_enabled: true,
    ...overrides,
  };
}

export function sample(): QaAllQuestions {
  return {
    categories: [
      { node_id: "zh", label: "中文", path: ["中文"], parent_id: null, hidden: false },
      { node_id: "svc", label: "服務", path: ["中文", "服務"], parent_id: "zh", hidden: false },
      { node_id: "en", label: "English", path: ["English"], parent_id: null, hidden: true },
    ],
    questions: [
      question({ id: "1", question: "營業時間？", answer: "九點開門", url: "https://example.com" }),
      question({ id: "2", question: "Parking?", answer: "Behind", language: "en", category_ids: ["svc", "en"], image: "map.png" }),
      question({ id: "3", question: "Hello?", language: "en", category_ids: ["en"], category_hidden: true,
        source: { kind: "file", path: "knowledge/qa/guide.md", label: "guide.md" } }),
      question({ id: "4", question: "沒答案？", answer: "", no_answer: true }),
      question({ id: "5", question: "沒掛上？", category_ids: [], off_menu: "never" }),
      question({ id: "6", question: "選單題？", answer: "", language: null, category_ids: ["zh"],
        source: { kind: "menu_only", path: "", label: "只在選單上" } }),
      question({ id: "7", question: "自己加的？", source: { kind: "manual", path: "knowledge/qa/manual_svc_1.md", label: "自己輸入" } }),
    ],
  };
}
