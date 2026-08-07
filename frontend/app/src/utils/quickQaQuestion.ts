const GENERIC_TOPIC_LABELS = new Set(["常見問題", "分類選單"]);

export interface QuickQaQuestionText {
  displayText: string;
  sendText: string;
}

function normalizeQuestionText(value: string): string {
  return value
    .replace(/\s+/g, " ")
    .trim()
    .replace(/[?？]+$/, "")
    .trim();
}

export function buildQuickQaQuestionText(
  rawQuestion: string,
  rawTopic: string,
): QuickQaQuestionText {
  const question = rawQuestion.trim();
  const topic = rawTopic.trim();

  if (!topic || GENERIC_TOPIC_LABELS.has(topic)) {
    const displayText = normalizeQuestionText(question) || question;
    return { displayText, sendText: displayText };
  }

  const shortQuestion = normalizeQuestionText(
    question.split(topic).join(" "),
  );
  const displayText = shortQuestion || normalizeQuestionText(question) || question;
  const sendText = displayText === topic ? topic : `${topic} ${displayText}`;

  return { displayText, sendText };
}
