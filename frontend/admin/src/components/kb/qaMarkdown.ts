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

const QA_HEADING_RE = /^##\s+(.+?)\s*$/gm;

/** Inverse of {@link qaRowsToMarkdown}: split ``## question`` blocks back into rows. */
export function parseQaMarkdown(content: string): QaRow[] {
  const headings = [...content.matchAll(QA_HEADING_RE)];
  return headings.map((match, index) => {
    const question = match[1].trim();
    const start = (match.index ?? 0) + match[0].length;
    const end = index + 1 < headings.length ? (headings[index + 1].index ?? content.length) : content.length;
    const answer = content.slice(start, end).trim();
    return { question, answer };
  });
}
