export interface QaRow {
  question: string;
  answer: string;
  img: string;
  url: string;
  hidden: boolean;
  csvFields?: Record<string, string>;
}

export interface QaCsvDocument {
  headers: string[];
  rows: QaRow[];
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

function parseCsvRecords(content: string): string[][] {
  const records: string[][] = [];
  let record: string[] = [];
  let field = "";
  let quoted = false;

  for (let index = 0; index < content.length; index += 1) {
    const char = content[index];
    if (quoted) {
      if (char === '"' && content[index + 1] === '"') {
        field += '"';
        index += 1;
      } else if (char === '"') {
        quoted = false;
      } else {
        field += char;
      }
      continue;
    }

    if (char === '"') {
      quoted = true;
    } else if (char === ",") {
      record.push(field);
      field = "";
    } else if (char === "\n") {
      record.push(field);
      records.push(record);
      record = [];
      field = "";
    } else if (char !== "\r") {
      field += char;
    }
  }

  if (field || record.length > 0) {
    record.push(field);
    records.push(record);
  }
  return records;
}

export function parseQaCsv(content: string): QaCsvDocument {
  const records = parseCsvRecords(content.replace(/^\uFEFF/, ""));
  const headers = records.shift()?.map((header) => header.trim()) ?? [];
  const rows = records.flatMap((values) => {
    const csvFields = Object.fromEntries(
      headers.map((header, index) => [header, values[index] ?? ""]),
    );
    const question = (csvFields.q ?? csvFields.question ?? "").trim();
    const answer = (csvFields.a ?? csvFields.answer ?? "").trim();
    if (!question && !answer) return [];

    const display = (csvFields.display ?? "true").trim().toLowerCase();
    return [{
      question,
      answer,
      img: (csvFields.img ?? "").trim(),
      url: (csvFields.url ?? "").trim(),
      hidden: ["false", "0", "no", "hidden"].includes(display),
      csvFields,
    }];
  });
  return { headers, rows };
}

function escapeCsvField(value: string): string {
  if (!/[",\r\n]/.test(value)) return value;
  return `"${value.replace(/"/g, '""')}"`;
}

export function qaRowsToCsv(rows: QaRow[], originalHeaders: string[]): string {
  const requiredHeaders = ["index", "q", "a", "img", "url", "display"];
  const headers = [
    ...originalHeaders,
    ...requiredHeaders.filter((header) => !originalHeaders.includes(header)),
  ];
  const lines = rows
    .filter((row) => !isBlankRow(row))
    .map((row, index) => {
      const fields: Record<string, string> = {
        ...(row.csvFields ?? {}),
        index: row.csvFields?.index || String(index + 1),
        q: row.question.trim(),
        a: row.answer.trim(),
        img: row.img.trim(),
        url: row.url.trim(),
        display: row.hidden ? "false" : "true",
      };
      return headers.map((header) => escapeCsvField(fields[header] ?? "")).join(",");
    });
  return [headers.map(escapeCsvField).join(","), ...lines].join("\n");
}
