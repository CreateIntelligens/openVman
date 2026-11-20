import { ApiError, statusMessage } from "../../../api/common";
import { moveQaQuestions, saveQaQuestion, type QaQuestionRow } from "../../../api/knowledge";
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
  const detail = failure.message;
  if (failure.status === 404) {
    if (
      detail === "目標分類不存在" ||
      detail === "這份文件裡沒有這個題目" ||
      detail === "找不到指定文件" ||
      detail.includes("不在原本的分類裡") ||
      detail.includes("不在來源文件裡")
    ) {
      return detail;
    }
    return statusMessage(404);
  }
  if (failure.status !== 400) return statusMessage(failure.status);

  if (/^(同一個分類不能有文字相同的題目|這個分類已經有相同的題目)/.test(detail)) {
    return "這個分類已有相同的問題。請改題目文字，或選擇其他分類。";
  }
  if (
    detail.includes("在目標分類已經有相同的題目") ||
    detail.includes("在同一批移動裡重複") ||
    detail === "這份文件裡已經有相同的題目" ||
    detail === "請指定來源文件" ||
    detail.endsWith("沒有指定來源文件") ||
    detail.endsWith("不是知識庫文件") ||
    detail.endsWith("不是 QA 文件")
  ) {
    return detail;
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
  if (/^(題目不可空白|答案不可空白|這一列沒有題目|選單專用的題目沒有固定答案|這份文件裡沒有這個題目)/.test(detail)) {
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
  projectId?: string,
) {
  const { q, a, img, url, hidden } = form;
  if (row && !from) {
    const source_file = row.source.path;
    const updated: MergedQaItem = { q, a, img, url, hidden, source_file };
    const current: MergedQaItem = baseline ?? {
      q: row.question, a: row.answer, img: row.image, url: row.url,
      hidden: row.hidden_in_file, source_file,
    };
    const contentChanged = rowContent(updated) !== rowContent(current);
    let saved = row;
    // 只選分類或重試掛載時，不需要經過內容儲存的答案驗證。
    if (contentChanged) {
      const result = await saveQaQuestion(
        {
          source_path: source_file,
          original_q: row.question,
          q,
          a,
          img,
          url,
          hidden,
          base_hash: row.content_hash,
        },
        projectId,
      );
      saved = {
        ...row,
        question: result.question.q,
        answer: result.question.a,
        image: result.question.img,
        url: result.question.url,
        hidden_in_file: result.question.hidden,
        content_hash: result.content_hash,
      };
    }
    if (form.category) {
      const savedQuestion: SavedQuestion = { row: saved, item: updated };
      try {
        await moveQaQuestions(
          form.category,
          [{ question: saved.question, source_path: source_file, from_node_ids: [] }],
          projectId,
        );
      } catch (failure) {
        if (!contentChanged) throw failure;
        const reason = questionErrorMessage(failure, "請重新確認題目所在的分類。");
        throw new QuestionActionError(`題目內容已儲存，但放進分類未完成。${reason}`, true, savedQuestion);
      }
    }
    return;
  }

  const category = row ? from : form.category;
  const rows = await api.fetchMergedQa(category);
  const item = row && from ? findMergedRow(rows, row) : undefined;
  if (row && (!item || (baseline && rowContent(baseline) !== rowContent(item)))) {
    throw new QuestionActionError(QUESTION_CONFLICT);
  }
  const source_file = item?.source_file || (a || url ? `knowledge/qa/manual_${category}.md` : "");
  const updated = { ...item, q, a, img, url, hidden, source_file };
  // 內容沒變（例如上次只差移動分類沒完成）就不再寫一次，只重試移動。
  if (!item || rowContent(updated) !== rowContent(item)) {
    const next = item ? rows.map((current) => current === item ? updated : current) : [...rows, updated];
    await api.saveMergedQa(category, next, rows[0]?.base_version);
  }

  if (row && from !== form.category) {
    // 這是唯一保留兩步（先存內容、再搬分類）的地方：內容存在原分類的版本檢查下，
    // 先以 PUT merged(from) 寫回，成功後再呼叫一次 moveQaQuestions 完成跨分類移動。
    // 改名或新增來源檔後，移動仍要使用儲存後的題目定位資料。
    const from_node_ids = row.category_ids.includes(form.category) ? [from, form.category] : [from];
    const saved = { ...row, question: q, source: { ...row.source, path: source_file } };
    const savedQuestion = { row: saved, item: updated };
    try {
      await moveQaQuestions(
        form.category,
        [{ question: saved.question, source_path: source_file, from_node_ids }],
        projectId,
      );
    } catch (failure) {
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
