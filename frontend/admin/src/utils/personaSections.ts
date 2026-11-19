/**
 * 角色管理「表格模式」：把 SOUL.md、AGENTS.md、GUARDRAILS.md 依固定的 `## 標題` 拆成欄位，
 * 存檔時寫回同一份文件。表格模式和原始文件模式改的是同一份檔案。
 *
 * 規則：
 * - 只認第二層 ATX 標題（`## `），程式碼區塊裡的不算。區塊照 CommonMark：記住開頭圍欄的
 *   字元與長度，只有同字元、長度不少於開頭的圍欄才關閉。
 * - 標題要和欄位名稱完全相同（前後空白、結尾的 ` ##` 不計）才算已知欄位；
 *   「角色設定 (Persona)」「角色設定#」這類不完全相同的標題當成其他內容，原樣保留。
 * - 文件裡完全沒有已知標題時，整份放進 fallback 欄位（SOUL 是角色設定、AGENTS 是角色與任務），
 *   但開頭的 `# ` 大標題留在其他內容：後台用它當角色名稱。
 * - 同一個已知標題出現第二次，第二次以後永遠是其他內容。
 * - 寫回時保留原文件的段落順序：已知欄位寫回原本的位置，原本沒有的欄位照固定順序插在
 *   其他已知欄位旁邊；其他內容的段落依標題對回原本的位置。沒改過的文件原封不動。
 * - 空欄位不寫出空標題；但後面還有同名段落時保留空標題，那一段才不會升成正式欄位。
 */

interface Section {
  title: string;
  heading: string;
  body: string;
  /** 標題連同內文的原文（只去掉前後空行），沒改的段落照這份寫回。 */
  text: string;
}

type Slot =
  | { kind: "lead" }
  | { kind: "field"; title: string; raw: string; body: string; headless?: boolean }
  | { kind: "other"; index: number };

export interface SectionDocument {
  fields: Record<string, string>;
  other: string;
  /** 解析時的段落結構與原文；寫回時用來保留順序、沒改就原樣寫回。 */
  layout: Slot[];
  otherSections: Section[];
  source: string;
  loadedFields: Record<string, string>;
  loadedOther: string;
  crlf: boolean;
}

const TITLE = /^ {0,3}#(?!#)[ \t]+\S/;
const ANY_HEADING = /^ {0,3}#{1,6}(?:[ \t]|$)/;

function headingTitle(line: string): string | null {
  const match = /^ {0,3}##([ \t].*|)$/.exec(line);
  if (!match) return null;
  const rest = match[1].replace(/[ \t]+#+[ \t]*$/, "").replace(/^[ \t]*#+[ \t]*$/, "");
  return rest.trim().replace(/\s+/g, " ");
}

/** 逐行走過文件，回報每一行是否在程式碼區塊裡，以及結尾是否還有沒關的區塊。 */
function scanFences(lines: string[]): { inFence: boolean[]; open: boolean } {
  const inFence: boolean[] = [];
  let fence: { char: string; length: number } | null = null;
  for (const line of lines) {
    const match = /^ {0,3}(`{3,}|~{3,})(.*)$/.exec(line);
    if (fence === null) {
      if (match && !(match[1][0] === "`" && match[2].includes("`"))) {
        fence = { char: match[1][0], length: match[1].length };
        inFence.push(true);
        continue;
      }
      inFence.push(false);
      continue;
    }
    inFence.push(true);
    if (match && match[1][0] === fence.char && match[1].length >= fence.length && !match[2].trim()) {
      fence = null;
    }
  }
  return { inFence, open: fence !== null };
}

function tidy(text: string): string {
  return text.replace(/^(?:[ \t]*\n)+/, "").trimEnd();
}

function splitSections(text: string): { lead: string; sections: Section[] } {
  const lines = text.split("\n");
  const { inFence } = scanFences(lines);
  const lead: string[] = [];
  const sections: { title: string; heading: string; lines: string[] }[] = [];
  lines.forEach((line, index) => {
    const title = inFence[index] ? null : headingTitle(line);
    if (title !== null) {
      sections.push({ title, heading: line.trimEnd(), lines: [] });
    } else if (sections.length > 0) {
      sections[sections.length - 1].lines.push(line);
    } else {
      lead.push(line);
    }
  });
  return {
    lead: tidy(lead.join("\n")),
    sections: sections.map(({ title, heading, lines: body }) => ({
      title,
      heading,
      body: tidy(body.join("\n")),
      text: tidy([heading, ...body].join("\n")),
    })),
  };
}

function joinBlocks(blocks: string[]): string {
  return blocks.filter((block) => block.trim()).join("\n\n");
}

function sectionText(section: Section): string {
  return section.text;
}

/** 解析文件。`fallback` 是沒有任何已知標題時，整份要放進的欄位。 */
export function parseSections(
  content: string,
  titles: readonly string[],
  fallback?: string,
): SectionDocument {
  const crlf = content.includes("\r\n");
  const text = content.replace(/\r\n/g, "\n");
  const fields: Record<string, string> = Object.fromEntries(titles.map((title) => [title, ""]));
  const { lead, sections } = splitSections(text);
  const known = new Set(titles);
  const done = (layout: Slot[], otherSections: Section[], other: string): SectionDocument => ({
    fields,
    other,
    layout,
    otherSections,
    source: content,
    loadedFields: { ...fields },
    loadedOther: other,
    crlf,
  });

  if (!sections.some((section) => known.has(section.title))) {
    if (!fallback) return done([{ kind: "lead" }], [], tidy(text));
    // 開頭的 YAML front matter 與 `# ` 大標題留在其他內容，其餘整份放進這一格。
    const body = tidy(text);
    const front = /^---\n[\s\S]*?\n(?:---|\.\.\.)(?:\n|$)/.exec(body)?.[0] ?? "";
    const [first, ...rest] = tidy(body.slice(front.length)).split("\n");
    const hasTitle = first !== undefined && TITLE.test(first);
    const head = joinBlocks([front.trimEnd(), hasTitle ? first.trimEnd() : ""]);
    fields[fallback] = hasTitle ? tidy(rest.join("\n")) : tidy(body.slice(front.length));
    const raw = fields[fallback];
    return done(
      [{ kind: "lead" }, { kind: "field", title: fallback, raw, body: raw, headless: true }],
      [],
      head,
    );
  }

  const layout: Slot[] = [{ kind: "lead" }];
  const otherSections: Section[] = [];
  const seen = new Set<string>();
  for (const section of sections) {
    if (known.has(section.title) && !seen.has(section.title)) {
      seen.add(section.title);
      fields[section.title] = section.body;
      layout.push({ kind: "field", title: section.title, raw: sectionText(section), body: section.body });
    } else {
      layout.push({ kind: "other", index: otherSections.length });
      otherSections.push(section);
    }
  }
  return done(layout, otherSections, joinBlocks([lead, ...otherSections.map(sectionText)]));
}

function sameFields(a: Record<string, string>, b: Record<string, string>): boolean {
  const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
  return [...keys].every((key) => (a[key] ?? "") === (b[key] ?? ""));
}

export function sameSections(a: SectionDocument, b: SectionDocument): boolean {
  return a.other === b.other && sameFields(a.fields, b.fields);
}

interface Plan {
  lead: string;
  /** 依原本的 other 段落編號，排在那個位置的段落（第一個是對回去的，後面是新加的）。 */
  bySlot: Map<number | "lead", Section[]>;
  problems: string[];
}

function fieldText(document: SectionDocument, title: string): string {
  return tidy((document.fields[title] ?? "").replace(/\r\n/g, "\n"));
}

/** 原文沒有已知標題的 fallback 欄位，在其他已知欄位都空著時維持無標題寫回。 */
function staysHeadless(document: SectionDocument, titles: readonly string[], slotTitle: string): boolean {
  const slot = document.layout.find((item) => item.kind === "field" && item.title === slotTitle);
  if (!slot || slot.kind !== "field" || !slot.headless) return false;
  return titles.every((title) => title === slotTitle || !fieldText(document, title));
}

function plan(document: SectionDocument, titles: readonly string[]): Plan {
  const { lead, sections } = splitSections(document.other.replace(/\r\n/g, "\n"));
  const used = new Set<number>();
  const bySlot: Plan["bySlot"] = new Map();
  const problems: string[] = [];
  const known = new Set(titles);
  let previous: number | "lead" = "lead";
  for (const section of sections) {
    const match = document.otherSections.findIndex(
      (original, index) => !used.has(index) && original.heading === section.heading,
    );
    if (match >= 0) {
      used.add(match);
      previous = match;
    } else if (known.has(section.title)) {
      problems.push(`其他內容裡的「## ${section.title}」會被當成正式欄位，請把內容移到「${section.title}」那一格，或改成別的標題。`);
    }
    bySlot.set(previous, [...(bySlot.get(previous) ?? []), section]);
  }
  if (scanFences(document.other.replace(/\r\n/g, "\n").split("\n")).open
    || sections.some((section) => scanFences(sectionText(section).split("\n")).open)
    || scanFences(lead.split("\n")).open) {
    problems.push("其他內容裡有沒有收尾的 ``` 程式碼區塊，請補上結尾再存。");
  }
  for (const title of titles) {
    const body = (document.fields[title] ?? "").replace(/\r\n/g, "\n");
    const lines = body.split("\n");
    const { inFence, open } = scanFences(lines);
    if (open) problems.push(`「${title}」裡有沒有收尾的 \`\`\` 程式碼區塊，請補上結尾再存。`);
    const clash = lines.find((line, index) => {
      const heading = inFence[index] ? null : headingTitle(line);
      return heading !== null && known.has(heading);
    });
    if (clash) problems.push(`「${title}」裡有「${clash.trim()}」這一行，存檔後會變成另一個欄位，請改成別的寫法。`);
    if (!staysHeadless(document, titles, title)) {
      const split = lines.find((line, index) => {
        const heading = inFence[index] ? null : headingTitle(line);
        return heading !== null && !known.has(heading);
      });
      if (split) problems.push(`「${title}」裡的「${split.trim()}」存檔後會移到其他內容，請把 ## 改成 ### 或拿掉。`);
    }
  }
  return { lead, bySlot, problems };
}

/** 存檔前檢查：回傳要請使用者先處理的問題；空陣列代表可以存。 */
export function sectionProblems(document: SectionDocument, titles: readonly string[]): string[] {
  return plan(document, titles).problems;
}

function withTitle(lead: string, title: string): string {
  // 前面有 YAML front matter 時，大標題放在它後面。
  const match = /^---\n[\s\S]*?\n(?:---|\.\.\.)(?:\n|$)/.exec(lead);
  if (!match) return joinBlocks([`# ${title}`, lead]);
  return joinBlocks([match[0].trimEnd(), `# ${title}`, lead.slice(match[0].length)]);
}

/**
 * 寫回文件。沒有任何修改時原樣回傳讀到的內容。
 * `title` 只在原文件沒有任何標題行時補上（那時後台用角色代號當名稱），
 * 免得寫出「## 角色設定」後角色名稱變成「角色設定」。
 */
export function serializeSections(
  document: SectionDocument,
  titles: readonly string[],
  options: { title?: string } = {},
): string {
  if (document.other === document.loadedOther && sameFields(document.fields, document.loadedFields)) {
    return document.source;
  }
  const { lead, bySlot } = plan(document, titles);
  const field = (title: string) => fieldText(document, title);
  const placed = new Set(document.layout.flatMap((slot) => (slot.kind === "field" ? [slot.title] : [])));
  const later = [...bySlot.values()].flat();

  // 原本沒有的欄位：插在固定順序裡下一個已存在欄位之前；後面都沒有就接在上一個之後。
  const layout: Slot[] = [...document.layout];
  for (const title of titles) {
    if (placed.has(title) || !field(title)) continue;
    const order = titles.indexOf(title);
    const nextIndex = layout.findIndex(
      (slot) => slot.kind === "field" && titles.indexOf(slot.title) > order,
    );
    const prevIndex = layout.map((slot) => slot.kind === "field" && titles.indexOf(slot.title) < order).lastIndexOf(true);
    const at = nextIndex >= 0 ? nextIndex : prevIndex >= 0 ? prevIndex + 1 : 1;
    layout.splice(at, 0, { kind: "field", title, raw: "", body: "" });
    placed.add(title);
  }

  const headlessField = (slot: Slot) =>
    slot.kind === "field" && Boolean(slot.headless) && staysHeadless(document, titles, slot.title);
  const writesFieldHeading = layout.some((slot) => {
    if (slot.kind !== "field") return false;
    return field(slot.title)
      ? !headlessField(slot)
      : later.some((section) => section.title === slot.title);
  });

  const blocks: string[] = [];
  for (const slot of layout) {
    if (slot.kind === "lead") {
      const untitled = !document.source.split(/\r?\n/).some((line) => ANY_HEADING.test(line));
      const head = options.title && untitled && writesFieldHeading ? withTitle(lead, options.title) : lead;
      blocks.push(head, ...(bySlot.get("lead") ?? []).map(sectionText));
    } else if (slot.kind === "field") {
      const body = field(slot.title);
      if (body) {
        if (headlessField(slot)) {
          blocks.push(body);
        } else {
          // 沒改過的欄位照原文寫回；原本沒有標題（整份當成這一格）一旦有了其他已知欄位就要補上標題，
          // 不然其他欄位的標題一出現，這段文字下次讀回來就變成其他內容。
          const keepRaw = body === slot.body && slot.raw && !slot.headless;
          blocks.push(keepRaw ? slot.raw : `## ${slot.title}\n\n${body}`);
        }
      } else if (later.some((section) => section.title === slot.title)) {
        blocks.push(`## ${slot.title}`);
      }
    } else {
      blocks.push(...(bySlot.get(slot.index) ?? []).map(sectionText));
    }
  }
  const text = joinBlocks(blocks);
  const result = text ? `${text}\n` : "";
  return document.crlf ? result.replace(/\n/g, "\r\n") : result;
}

export const SOUL_TITLES = ["角色設定", "回應風格"] as const;
export const AGENTS_TITLES = ["角色與任務"] as const;
export const GUARDRAILS_TITLES = ["範圍限制", "回覆格式", "知識庫規則"] as const;
