/**
 * 角色管理「表格模式」：把 SOUL.md、AGENTS.md、GUARDRAILS.md 依固定的 `## 標題` 拆成欄位，
 * 存檔時寫回同一份文件。表格模式和原始文件模式改的是同一份檔案。
 *
 * 規則：
 * - 只認頂格（行首沒有空白）的第二層 ATX 標題（`## `）；程式碼區塊、文件開頭的 YAML front
 *   matter（`---` 到 `---`／`...`）裡的不算，清單裡縮排的 `## ` 也不算。程式碼區塊記住開頭圍欄的
 *   字元與長度，只有同字元、長度不少於開頭的圍欄才關閉；縮排的圍欄（清單裡的程式碼）也算。
 * - 標題要和欄位名稱完全相同（前後空白、結尾的 ` ##` 不計）才算已知欄位；
 *   「角色設定 (Persona)」「角色設定#」這類不完全相同的標題當成其他內容，原樣保留。
 * - 文件裡完全沒有已知標題時，整份放進 fallback 欄位（SOUL 是角色設定、AGENTS 是角色與任務），
 *   但開頭的 `# ` 大標題留在其他內容：後台用它當角色名稱。
 * - 同一個已知標題出現第二次，第二次以後永遠是其他內容。
 * - 寫回時保留原文件的段落順序：已知欄位寫回原本的位置，原本沒有的欄位照固定順序插在
 *   其他已知欄位旁邊；其他內容的段落依標題對回原本的位置，使用者在其他內容裡調換的順序照新的寫。
 *   沒改過的文件原封不動。
 * - 空欄位不寫出空標題；但後面還有同名段落時保留空標題，那一段才不會升成正式欄位。所有欄位都
 *   清空、其他內容卻還有段落時也留一個空標題，不然下次讀回來整份會被放進 fallback 欄位。
 * - 存檔前用 `serializeChecked` 把寫出的文字再解析一次，欄位與其他內容要和畫面上一樣才存。
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
  /** 沒有任何已知標題時整份放進的欄位；寫回時要避免清空欄位後整份被收進這一格。 */
  fallback?: string;
}

const TITLE = /^ {0,3}#(?!#)[ \t]+\S/;
const ANY_HEADING = /^ {0,3}#{1,6}(?:[ \t]|$)/;

function headingTitle(line: string): string | null {
  // 只認頂格：清單項目裡縮排的 `## ` 是那一項的內容，不是段落標題。
  const match = /^##([ \t].*|)$/.exec(line);
  if (!match) return null;
  const rest = match[1].replace(/[ \t]+#+[ \t]*$/, "").replace(/^[ \t]*#+[ \t]*$/, "");
  return rest.trim().replace(/\s+/g, " ");
}

/** 文件開頭 YAML front matter 結尾那一行的位置；沒有 front matter 時是 -1。 */
function frontMatterEnd(lines: string[]): number {
  if (lines[0] !== "---") return -1;
  return lines.findIndex((line, index) => index > 0 && (line === "---" || line === "..."));
}

/**
 * 逐行走過文件，回報每一行是否在程式碼區塊（或開頭的 front matter）裡，以及結尾是否還有沒關的區塊。
 * `frontMatter` 只給從文件開頭算起的文字用；欄位內文不是文件開頭，裡面的 `---` 是分隔線。
 */
function scanFences(lines: string[], frontMatter = false): { inFence: boolean[]; open: boolean } {
  const inFence: boolean[] = [];
  let fence: { char: string; length: number } | null = null;
  const front = frontMatter ? frontMatterEnd(lines) : -1;
  for (const [index, line] of lines.entries()) {
    if (index <= front) {
      inFence.push(true);
      continue;
    }
    // 圍欄不限縮排：清單裡的程式碼區塊常縮排四格，裡面的 `## ` 不能被當成標題。
    const match = /^[ \t]*(`{3,}|~{3,})(.*)$/.exec(line);
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

/** 開頭的 front matter 原文（含結尾那一行的換行）；沒有時是空字串。 */
function frontMatterBlock(text: string): string {
  const lines = text.split("\n");
  const end = frontMatterEnd(lines);
  if (end < 0) return "";
  return lines.slice(0, end + 1).join("\n") + (end + 1 < lines.length ? "\n" : "");
}

/** 其他內容除了開頭的 front matter 與 `# ` 大標題之外是否還有東西。 */
function onlyHead(other: string): boolean {
  const text = tidy(other.replace(/\r\n/g, "\n"));
  const body = tidy(text.slice(frontMatterBlock(text).length));
  const [first = "", ...rest] = body.split("\n");
  return (TITLE.test(first) ? rest.join("\n") : body).trim() === "";
}

function tidy(text: string): string {
  return text.replace(/^(?:[ \t]*\n)+/, "").trimEnd();
}

/** `text` 一定從文件開頭算起（整份文件或其他內容），開頭的 front matter 不拆。 */
function splitSections(text: string): { lead: string; sections: Section[] } {
  const lines = text.split("\n");
  const { inFence } = scanFences(lines, true);
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
    fallback,
  });

  if (!sections.some((section) => known.has(section.title))) {
    if (!fallback) return done([{ kind: "lead" }], [], tidy(text));
    // 開頭的 YAML front matter 與 `# ` 大標題留在其他內容，其餘整份放進這一格。
    const body = tidy(text);
    const front = frontMatterBlock(body);
    const afterFront = body.slice(front.length);
    const gap = /^(?:[ \t]*\n)*/.exec(afterFront)?.[0] ?? "";
    const [first, ...rest] = afterFront.slice(gap.length).split("\n");
    const hasTitle = first !== undefined && TITLE.test(first);
    // 照原文切出 front matter 與大標題（中間的空行也照舊），存回去再讀才會一模一樣。
    const head = tidy(hasTitle ? body.slice(0, front.length + gap.length + first.length) : front);
    fields[fallback] = hasTitle ? tidy(rest.join("\n")) : tidy(afterFront);
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

/** 最長遞增子序列（略過 -1），回傳留在原位的項目索引。 */
function increasingRun(values: number[]): Set<number> {
  const length: number[] = [];
  const before: number[] = [];
  let best = -1;
  values.forEach((value, index) => {
    length[index] = 0;
    before[index] = -1;
    if (value < 0) return;
    length[index] = 1;
    for (let earlier = 0; earlier < index; earlier += 1) {
      if (values[earlier] >= 0 && values[earlier] < value && length[earlier] + 1 > length[index]) {
        length[index] = length[earlier] + 1;
        before[index] = earlier;
      }
    }
    if (best < 0 || length[index] > length[best]) best = index;
  });
  const kept = new Set<number>();
  for (let index = best; index >= 0; index = before[index]) kept.add(index);
  return kept;
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
  // 其他內容多了段落或前言時也要補標題，不然下次讀回來那些內容會被收進這一格。
  return titles.every((title) => title === slotTitle || !fieldText(document, title)) && onlyHead(document.other);
}

function plan(document: SectionDocument, titles: readonly string[]): Plan {
  const { lead, sections } = splitSections(document.other.replace(/\r\n/g, "\n"));
  const used = new Set<number>();
  const bySlot: Plan["bySlot"] = new Map();
  const problems: string[] = [];
  const known = new Set(titles);
  const matches = sections.map((section) => {
    const match = document.otherSections.findIndex(
      (original, index) => !used.has(index) && original.heading === section.heading,
    );
    if (match >= 0) used.add(match);
    return match;
  });
  // 順序沒變的段落（最長遞增子序列）留在原本的位置；被使用者調換過的，接在前一段後面，
  // 寫出的順序才會和其他內容裡看到的一樣。
  const anchored = increasingRun(matches);
  let previous: number | "lead" = "lead";
  sections.forEach((section, index) => {
    if (anchored.has(index)) {
      previous = matches[index];
    } else if (matches[index] < 0 && known.has(section.title)) {
      problems.push(`其他內容裡的「## ${section.title}」會被當成正式欄位，請把內容移到「${section.title}」那一格，或改成別的標題。`);
    }
    bySlot.set(previous, [...(bySlot.get(previous) ?? []), section]);
  });
  if (scanFences(document.other.replace(/\r\n/g, "\n").split("\n"), true).open
    || sections.some((section) => scanFences(sectionText(section).split("\n")).open)
    || scanFences(lead.split("\n"), true).open) {
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
  const front = frontMatterBlock(lead);
  if (!front) return joinBlocks([`# ${title}`, lead]);
  return joinBlocks([front.trimEnd(), `# ${title}`, lead.slice(front.length)]);
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
  return render(document, titles, options).text;
}

/**
 * 寫回文件，並把結果再解析一次：欄位與其他內容（照使用者排的順序）要和畫面上一模一樣，
 * `intact` 才是 true。不一樣就代表這份文件的結構表格模式存不回去，不能寫。
 */
export function serializeChecked(
  document: SectionDocument,
  titles: readonly string[],
  options: { title?: string } = {},
): { text: string; intact: boolean } {
  const { text, head } = render(document, titles, options);
  const reread = parseSections(text, titles, document.fallback);
  const { sections } = splitSections(document.other.replace(/\r\n/g, "\n"));
  const expectedOther = joinBlocks([head, ...sections.map(sectionText)]);
  const intact = reread.other === expectedOther
    && titles.every((title) => reread.fields[title] === fieldText(document, title));
  return { text, intact };
}

function render(
  document: SectionDocument,
  titles: readonly string[],
  options: { title?: string },
): { text: string; head: string } {
  const { lead, bySlot } = plan(document, titles);
  if (document.other === document.loadedOther && sameFields(document.fields, document.loadedFields)) {
    return { text: document.source, head: lead };
  }
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
  const writesHeading = (slot: Slot) => slot.kind === "field" && (field(slot.title)
    ? !headlessField(slot)
    : later.some((section) => section.title === slot.title));
  // 欄位全空、其他內容卻還有段落時：一個已知標題都沒寫出去，下次讀回來會整份收進 fallback 欄位。
  // 留下第一個欄位的空標題，其他內容才留在其他內容。
  const anchorSlot = document.fallback
    && !layout.some((slot) => writesHeading(slot) || (slot.kind === "field" && field(slot.title)))
    && !onlyHead(document.other)
    ? layout.find((slot) => slot.kind === "field")
    : undefined;
  const writesFieldHeading = anchorSlot !== undefined || layout.some(writesHeading);

  const blocks: string[] = [];
  let head = lead;
  for (const slot of layout) {
    if (slot.kind === "lead") {
      const untitled = !document.source.split(/\r?\n/).some((line) => ANY_HEADING.test(line));
      head = options.title && untitled && writesFieldHeading ? withTitle(lead, options.title) : lead;
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
      } else if (slot === anchorSlot || later.some((section) => section.title === slot.title)) {
        blocks.push(`## ${slot.title}`);
      }
    } else {
      blocks.push(...(bySlot.get(slot.index) ?? []).map(sectionText));
    }
  }
  const text = joinBlocks(blocks);
  const result = text ? `${text}\n` : "";
  return { text: document.crlf ? result.replace(/\n/g, "\r\n") : result, head };
}

export const SOUL_TITLES = ["角色設定", "回應風格"] as const;
export const AGENTS_TITLES = ["角色與任務"] as const;
export const GUARDRAILS_TITLES = ["範圍限制", "回覆格式", "知識庫規則"] as const;
