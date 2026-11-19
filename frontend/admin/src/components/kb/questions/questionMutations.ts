import { ApiError, statusMessage } from "../../../api/common";
import type { QaQuestionRow } from "../../../api/knowledge";
import type { MergedQaItem, useQaNodes } from "../../../hooks/useQaNodes";

export type QuestionApi = Pick<ReturnType<typeof useQaNodes>,
  "fetchMergedQa" | "saveMergedQa" | "addQaEntry" | "removeQaEntry" | "uploadImage">;

/** 內容已寫入但移動分類沒完成時，重試要用剛存好的題目定位與內容，才不會被當成別人改過。 */
export interface SavedQuestion {
  row: QaQuestionRow;
  item: MergedQaItem;
}

export class QuestionActionError extends Error {
  constructor(message: string, readonly saved = false, readonly savedQuestion?: SavedQuestion) {
    super(message);
  }
}

export const QUESTION_CONFLICT = "有人同時修改了題目，請重新整理後再改。";

export function questionErrorMessage(failure: unknown, fallback: string) {
  if (failure instanceof QuestionActionError) return failure.message;
  if (!(failure instanceof ApiError)) return fallback;
  if (failure.status === 409) return QUESTION_CONFLICT;
  if (failure.status !== 400) return statusMessage(failure.status);

  const detail = failure.message;
  if (/^(同一個分類不能有文字相同的題目|這個分類已經有相同的題目)/.test(detail)) {
    return "這個分類已有相同的問題。請改題目文字，或選擇其他分類。";
  }
  if (detail.startsWith("改名後") && detail.includes("裡的題目重複")) {
    return "改名後會和另一個掛載分類裡的題目重複，請換個問題文字。";
  }
  if (detail.includes("不是 UTF-8") || detail.includes("無法照原格式存回") || detail.includes("讀不懂")) {
    return "無法用原格式儲存來源文件，請先到文件頁檢查格式。";
  }
  if (/^(這些題目已經有別的答案|文件裡這些題目重複)/.test(detail)) {
    return "來源文件有重複題目或不同答案，請先到文件頁處理。";
  }
  if (/^(題目不可空白|這一列沒有題目|選單專用的題目沒有固定答案|這份文件裡沒有這個題目)/.test(detail)) {
    return detail;
  }
  return statusMessage(400);
}

export interface QuestionDraft {
  q: string;
  a: string;
  img: string;
  url: string;
  hidden: boolean;
  category: string;
}

function canonicalSource(path: string) {
  return path.replace(/^\.\//, "").replace(/^knowledge\//, "");
}

export function findMergedRow(rows: MergedQaItem[], row: QaQuestionRow) {
  return rows.find((item) =>
    item.q === row.question && canonicalSource(item.source_file) === canonicalSource(row.source.path),
  );
}

async function requireMergedRow(api: QuestionApi, category: string, row: QaQuestionRow) {
  const rows = await api.fetchMergedQa(category);
  const item = findMergedRow(rows, row);
  if (!item) throw new QuestionActionError("找不到這一題。請重新開啟題目後再試。");
  return { rows, item };
}

export async function setQuestionVisibility(api: QuestionApi, row: QaQuestionRow, category: string, hidden: boolean) {
  const { rows, item } = await requireMergedRow(api, category, row);
  if (Boolean(item.hidden) === hidden) return;
  await api.saveMergedQa(category, rows.map((current) => current === item ? { ...item, hidden } : current), item.base_version);
}

export async function detachQuestion(api: QuestionApi, row: QaQuestionRow, category: string) {
  const { item } = await requireMergedRow(api, category, row);
  await api.removeQaEntry(category, item.q, item.source_file);
}

export async function moveQuestion(api: QuestionApi, row: QaQuestionRow, from: string[], to: string) {
  const sources = from.filter((id) => id !== to);
  const alreadyAtTarget = row.category_ids.includes(to);
  if (!sources.length && alreadyAtTarget) return "unchanged";
  if (!alreadyAtTarget) {
    if (row.source.path) {
      await api.addQaEntry(to, row.question, row.source.path);
    } else {
      const { item } = await requireMergedRow(api, sources[0], row);
      const destination = await api.fetchMergedQa(to);
      if (destination.some((current) => current.q === item.q)) {
        throw new QuestionActionError("目標分類已有相同問題。");
      }
      const { base_version: _version, original_q: _original, ...copy } = item;
      await api.saveMergedQa(to, [...destination, copy], destination[0]?.base_version);
    }
  }

  let incomplete = false;
  for (const category of sources) {
    try {
      await detachQuestion(api, row, category);
    } catch {
      incomplete = true;
    }
  }
  return incomplete ? "partial" : "moved";
}

export async function deleteQuestion(api: QuestionApi, row: QaQuestionRow) {
  const [last, ...otherCategories] = row.category_ids;
  if (!last) throw new QuestionActionError("請開啟來源文件刪除這一題。");
  if (otherCategories.length) await requireMergedRow(api, last, row);
  let detached = false;
  try {
    for (const category of otherCategories) {
      await detachQuestion(api, row, category);
      detached = true;
    }
    // 留下最後一個掛載用整批儲存刪除，後端才會一併移除來源文件裡的題目。
    const { rows, item } = await requireMergedRow(api, last, row);
    if (item.also_in?.length) throw new QuestionActionError("題目已掛到其他分類，請重新確認刪除範圍。");
    await api.saveMergedQa(last, rows.filter((current) => current !== item), item.base_version);
  } catch (failure) {
    if (!detached) throw failure;
    throw new QuestionActionError("部分分類已移除這一題。請重新確認題目是否仍在，再繼續刪除。", true);
  }
}

function rowContent(value: MergedQaItem) {
  return JSON.stringify([value.q, value.a, value.img ?? "", value.url ?? "", Boolean(value.hidden), value.source_file]);
}

export async function saveQuestion(
  api: QuestionApi,
  row: QaQuestionRow | null,
  from: string,
  form: QuestionDraft,
  baseline?: MergedQaItem,
) {
  const category = row ? from : form.category;
  const rows = await api.fetchMergedQa(category);
  const item = row && from ? findMergedRow(rows, row) : undefined;
  if (row && (!item || (baseline && rowContent(baseline) !== rowContent(item)))) {
    throw new QuestionActionError(QUESTION_CONFLICT);
  }
  const { q, a, img, url, hidden } = form;
  const source_file = item?.source_file || (a || url ? `knowledge/qa/manual_${category}.md` : "");
  const updated = { ...item, q, a, img, url, hidden, source_file };
  // 內容沒變（例如上次只差移動分類沒完成）就不再寫一次，只重試移動。
  if (!item || rowContent(updated) !== rowContent(item)) {
    const next = item ? rows.map((current) => current === item ? updated : current) : [...rows, updated];
    await api.saveMergedQa(category, next, rows[0]?.base_version);
  }

  if (row && from !== form.category) {
    // 改名或新增來源檔後，移動仍要使用儲存後的題目定位資料。
    const saved = { ...row, question: q, source: { ...row.source, path: source_file } };
    const savedQuestion = { row: saved, item: updated };
    try {
      const destination = await api.fetchMergedQa(form.category);
      saved.category_ids = findMergedRow(destination, saved) ? [form.category] : [];
      const result = await moveQuestion(api, saved, [from], form.category);
      if (result === "partial") {
        throw new QuestionActionError("題目內容已儲存，也已加入目標分類，但尚未從原分類移除。", true, savedQuestion);
      }
    } catch (failure) {
      if (failure instanceof QuestionActionError && failure.saved) throw failure;
      const reason = questionErrorMessage(failure, "請重新確認題目所在的分類。");
      throw new QuestionActionError(`題目內容已儲存，但移動分類未完成。${reason}`, true, savedQuestion);
    }
  }
}

export async function reorderQuestions(api: QuestionApi, category: string, moving: QaQuestionRow, target: QaQuestionRow) {
  const rows = await api.fetchMergedQa(category);
  const movingRow = findMergedRow(rows, moving);
  const targetRow = findMergedRow(rows, target);
  if (!movingRow || !targetRow) {
    throw new QuestionActionError("題目已更新。請確認最新清單後再調整順序。");
  }
  const from = rows.indexOf(movingRow);
  const to = rows.indexOf(targetRow);
  if (from === to) return;
  const [entry] = rows.splice(from, 1);
  rows.splice(to, 0, entry);
  await api.saveMergedQa(category, rows, entry.base_version);
}
