export interface QaRow {
  question: string;
  answer: string;
}

export function createEmptyQaRow(): QaRow {
  return { question: "", answer: "" };
}

function isBlankRow(row: QaRow): boolean {
  return !row.question.trim() && !row.answer.trim();
}

export function hasIncompleteQaRows(rows: QaRow[]): boolean {
  return rows.some((row) => {
    const q = row.question.trim();
    const a = row.answer.trim();
    return Boolean(q) !== Boolean(a);
  });
}

export function hasUsableQaRow(rows: QaRow[]): boolean {
  return rows.some((row) => row.question.trim() && row.answer.trim());
}

export function qaRowsToMarkdown(rows: QaRow[]): string {
  return rows
    .filter((row) => !isBlankRow(row))
    .map((row) => `## ${row.question.trim()}\n\n${row.answer.trim()}`)
    .join("\n\n");
}
