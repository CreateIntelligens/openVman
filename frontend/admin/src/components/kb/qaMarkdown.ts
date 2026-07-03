export interface QaRow {
  question: string;
  answer: string;
  img: string;
  url: string;
  hidden: boolean;
}

export function createEmptyQaRow(): QaRow {
  return { question: "", answer: "", img: "", url: "", hidden: false };
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

const QA_HEADING_RE = /^##\s+(.+?)\s*$/gm;
const QA_METADATA_RE = /<!--\s*qa_metadata:\s*({.*?})\s*-->/;

// Mirrors backend qa_csv.qa_markdown_block: metadata travels in an HTML
// comment so the file stays a valid markdown document and round-trips.
export function qaRowsToMarkdown(rows: QaRow[]): string {
  return rows
    .filter((row) => !isBlankRow(row))
    .map((row) => {
      const metadata: Record<string, unknown> = {
        img: row.img.trim(),
        url: row.url.trim(),
      };
      if (row.hidden) {
        metadata.hidden = true;
      }
      const metadataStr = JSON.stringify(metadata);
      return `## ${row.question.trim()}\n\n${row.answer.trim()}\n<!-- qa_metadata: ${metadataStr} -->`;
    })
    .join("\n\n");
}

function maskCodeBlockHeadings(content: string): string {
  return content.replace(/```[\s\S]*?```/g, (block) =>
    block.replace(/[^\n]/g, " "),
  );
}

/** Inverse of {@link qaRowsToMarkdown}: mirrors backend qa_csv.parse_qa_markdown. */
export function parseQaMarkdown(content: string): QaRow[] {
  const masked = maskCodeBlockHeadings(content);
  const headings = [...masked.matchAll(QA_HEADING_RE)];
  const rows: QaRow[] = [];

  for (let index = 0; index < headings.length; index++) {
    const match = headings[index];
    const question = match[1].trim();
    if (!question) continue;

    const start = (match.index ?? 0) + match[0].length;
    const end = index + 1 < headings.length
      ? (headings[index + 1].index ?? content.length)
      : content.length;
    let answer = content.slice(start, end).trim();

    let img = "";
    let url = "";
    let hidden = false;
    const metaMatch = answer.match(QA_METADATA_RE);
    if (metaMatch) {
      try {
        const meta: unknown = JSON.parse(metaMatch[1]);
        if (meta && typeof meta === "object") {
          const record = meta as Record<string, unknown>;
          img = typeof record.img === "string" ? record.img : "";
          url = typeof record.url === "string" ? record.url : "";
          hidden = Boolean(record.hidden);
        }
      } catch {
        // 非法 JSON 時視為無 metadata，但仍移除註解（與後端一致）
      }
      answer = answer.replace(QA_METADATA_RE, "").trim();
    }

    rows.push({ question, answer, img, url, hidden });
  }

  return rows;
}
