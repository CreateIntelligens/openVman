import { useCallback, useEffect, useMemo, useState } from "react";

import { type MergedQaItem, useQaNodes } from "../../../hooks/useQaNodes";

interface MergedCsvPaneProps {
  nodeId: string | null;
  nodeLabel?: string;
  onSuccess?: () => void;
}

interface LocalMergedQaItem extends MergedQaItem {
  _localId: string;
}

type EditableMergedQaField = "q" | "a" | "img" | "url" | "hidden";

function localRowId(prefix: string): string {
  return `${prefix}_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`;
}

function cloneRows(rows: LocalMergedQaItem[]): LocalMergedQaItem[] {
  return rows.map((row) => ({ ...row }));
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

export default function MergedCsvPane({
  nodeId,
  nodeLabel = "",
  onSuccess,
}: MergedCsvPaneProps) {
  const { fetchMergedQa, saveMergedQa } = useQaNodes();

  const [rows, setRows] = useState<LocalMergedQaItem[]>([]);
  const [originalRows, setOriginalRows] = useState<LocalMergedQaItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusMsg, setStatusMsg] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const loadMergedQa = useCallback(async (id: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchMergedQa(id);
      const mapped = data.map((item, idx) => ({
        ...item,
        _localId: item.index || localRowId(`init_${idx}`),
      }));
      setRows(mapped);
      setOriginalRows(cloneRows(mapped));
    } catch (error: unknown) {
      setError(errorMessage(error, "無法取得問答合併檢視資料"));
    } finally {
      setLoading(false);
    }
  }, [fetchMergedQa]);

  useEffect(() => {
    if (nodeId) {
      loadMergedQa(nodeId);
      setStatusMsg(null);
    } else {
      setRows([]);
      setOriginalRows([]);
    }
  }, [nodeId, loadMergedQa]);

  if (!nodeId) {
    return (
      <div className="flex flex-col items-center justify-center h-full p-8 text-slate-400 dark:text-slate-500 bg-white dark:bg-slate-900/30 rounded-xl border border-dashed border-slate-200 dark:border-slate-800">
        <span className="material-symbols-outlined text-[3rem] mb-3 text-slate-300 dark:text-slate-600">
          drafts
        </span>
        <p className="text-sm font-medium">請從左側側邊欄選擇一個知識節點以檢視並編輯問答數據</p>
      </div>
    );
  }

  const isDirty = useMemo(
    () => JSON.stringify(rows) !== JSON.stringify(originalRows),
    [rows, originalRows],
  );

  const handleCellChange = (
    index: number,
    field: EditableMergedQaField,
    value: string | boolean,
  ) => {
    const next = rows.map((row, i) => {
      if (i === index) {
        return { ...row, [field]: value };
      }
      return row;
    });
    setRows(next);
  };

  const handleAddRow = () => {
    const defaultSourceFile =
      rows.length > 0 && rows[0].source_file
        ? rows[0].source_file
        : `knowledge/manual_${nodeId}.md`;

    const newRow: LocalMergedQaItem = {
      q: "",
      a: "",
      img: "",
      url: "",
      source_file: defaultSourceFile,
      hidden: false,
      _localId: localRowId("new"),
    };
    setRows([...rows, newRow]);
  };

  const handleRemoveRow = (index: number) => {
    const next = rows.filter((_, i) => i !== index);
    setRows(next);
  };

  const handleCancel = () => {
    setRows(cloneRows(originalRows));
    setStatusMsg(null);
  };

  const handleSave = async () => {
    const hasEmptyField = rows.some((row) => !row.q.trim() || !row.a.trim());
    if (hasEmptyField) {
      setStatusMsg({ type: "error", text: "儲存失敗：所有問答欄位皆必須填寫問題與答案" });
      return;
    }

    setSaving(true);
    setStatusMsg(null);
    try {
      const payload = rows.map(({ _localId, ...r }) => ({
        ...r,
        q: r.q.trim(),
        a: r.a.trim(),
        img: r.img?.trim() || "",
        url: r.url?.trim() || "",
      }));
      await saveMergedQa(nodeId, payload);
      setStatusMsg({ type: "success", text: "問答變更已成功同步至伺服器並重新編製索引！" });
      await loadMergedQa(nodeId);
      onSuccess?.();
    } catch (error: unknown) {
      setStatusMsg({ type: "error", text: errorMessage(error, "儲存合併問答失敗") });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-col h-full bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden shadow-sm">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between border-b border-slate-200 dark:border-slate-800 px-6 py-4 gap-3 bg-slate-50/50 dark:bg-slate-950/20 shrink-0">
        <div>
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-[1.25rem] text-primary">view_list</span>
            <span className="text-base font-bold text-slate-800 dark:text-slate-100">
              合併檢視編輯器
            </span>
          </div>
          {nodeLabel && (
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
              目前節點：<span className="font-semibold text-slate-700 dark:text-slate-300">{nodeLabel}</span> ({nodeId})
            </p>
          )}
        </div>

        {isDirty && (
          <span className="self-start sm:self-center px-2 py-0.5 text-[0.7rem] font-bold text-amber-700 bg-amber-50 dark:text-amber-300 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800/30 rounded-md animate-pulse">
            有未儲存變更
          </span>
        )}
      </div>

      {(error || statusMsg) && (
        <div className="px-6 pt-4 shrink-0">
          {error && (
            <div className="flex items-start gap-2 rounded-lg bg-red-50 text-red-800 p-3 text-xs dark:bg-red-950/30 dark:text-red-300 border border-red-200 dark:border-red-900/30">
              <span className="material-symbols-outlined text-[1.125rem] shrink-0 mt-0.5">error</span>
              <div>{error}</div>
            </div>
          )}
          {statusMsg && (
            <div
              className={`flex items-start gap-2.5 rounded-lg p-3 text-xs leading-relaxed ${
                statusMsg.type === "success"
                  ? "bg-green-50 text-green-800 dark:bg-green-950/30 dark:text-green-300 border border-green-200 dark:border-green-800/30"
                  : "bg-red-50 text-red-800 dark:bg-red-950/30 dark:text-red-300 border border-red-200 dark:border-red-800/30"
              }`}
            >
              <span className="material-symbols-outlined text-[1.125rem] shrink-0 mt-0.5">
                {statusMsg.type === "success" ? "check_circle" : "error"}
              </span>
              <div>{statusMsg.text}</div>
            </div>
          )}
        </div>
      )}

      <div className="flex-1 overflow-auto p-6 min-h-0">
        {loading ? (
          <div className="flex flex-col items-center justify-center h-full text-slate-500 py-12">
            <span className="material-symbols-outlined animate-spin text-[2rem] mb-2 text-primary">
              sync
            </span>
            <p className="text-xs">正在載入合併問答數據...</p>
          </div>
        ) : rows.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-slate-400 dark:text-slate-500 py-12 space-y-2">
            <span className="material-symbols-outlined text-[2.5rem]">
              table_rows_page
            </span>
            <p className="text-sm font-medium">此節點尚無任何問答數據</p>
            <p className="text-xs">請點擊下方「新增一列」或使用「上傳對話框」匯入問答</p>
          </div>
        ) : (
          <div className="border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden min-w-[50rem]">
            <table className="w-full text-left border-collapse table-fixed">
              <thead>
                <tr className="bg-slate-50 dark:bg-slate-950/50 border-b border-slate-200 dark:border-slate-800 text-xs font-bold text-slate-500 dark:text-slate-400">
                  <th className="py-3 px-4 w-[4%] text-center">#</th>
                  <th className="py-3 px-4 w-[28%]">問題 (Question)</th>
                  <th className="py-3 px-4 w-[28%]">答案 (Answer)</th>
                  <th className="py-3 px-4 w-[12%]">圖片 ID</th>
                  <th className="py-3 px-4 w-[12%]">外部連結 URL</th>
                  <th className="py-3 px-4 w-[8%] text-center">可見性</th>
                  <th className="py-3 px-4 w-[8%] text-center">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800 text-sm">
                {rows.map((row, idx) => (
                  <tr
                    key={row._localId}
                    className={`hover:bg-slate-50/50 dark:hover:bg-slate-800/30 transition-colors ${
                      row.hidden ? "opacity-60 bg-slate-50/20 dark:bg-slate-950/10" : ""
                    }`}
                  >
                    <td className="py-2.5 px-4 text-center text-xs font-mono text-slate-400 dark:text-slate-500">
                      <div className="group relative cursor-help">
                        {idx + 1}
                        <div className="absolute left-1/2 -translate-x-1/2 bottom-full mb-2 hidden group-hover:block bg-slate-850 text-white text-[0.65rem] py-1 px-2 rounded shadow-lg whitespace-nowrap z-10 font-sans">
                          來源檔案：{row.source_file}
                        </div>
                      </div>
                    </td>

                    <td className="py-2 px-3 align-top">
                      <textarea
                        value={row.q}
                        onChange={(e) => handleCellChange(idx, "q", e.target.value)}
                        placeholder="請輸入問題"
                        rows={2}
                        className="w-full resize-none bg-transparent outline-none focus:bg-white dark:focus:bg-slate-850 p-1.5 border border-transparent focus:border-slate-300 dark:focus:border-slate-700 rounded text-xs leading-relaxed text-slate-800 dark:text-slate-200 transition-all focus:shadow-sm"
                      />
                    </td>

                    <td className="py-2 px-3 align-top">
                      <textarea
                        value={row.a}
                        onChange={(e) => handleCellChange(idx, "a", e.target.value)}
                        placeholder="請輸入答案"
                        rows={2}
                        className="w-full resize-none bg-transparent outline-none focus:bg-white dark:focus:bg-slate-850 p-1.5 border border-transparent focus:border-slate-300 dark:focus:border-slate-700 rounded text-xs leading-relaxed text-slate-800 dark:text-slate-200 transition-all focus:shadow-sm"
                      />
                    </td>

                    <td className="py-2 px-3 align-top">
                      <input
                        type="text"
                        value={row.img || ""}
                        onChange={(e) => handleCellChange(idx, "img", e.target.value)}
                        placeholder="圖片 ID"
                        className="w-full bg-transparent outline-none focus:bg-white dark:focus:bg-slate-850 p-1.5 border border-transparent focus:border-slate-300 dark:focus:border-slate-700 rounded text-xs font-mono text-slate-700 dark:text-slate-300 transition-all focus:shadow-sm"
                      />
                    </td>

                    <td className="py-2 px-3 align-top">
                      <input
                        type="text"
                        value={row.url || ""}
                        onChange={(e) => handleCellChange(idx, "url", e.target.value)}
                        placeholder="外部連結"
                        className="w-full bg-transparent outline-none focus:bg-white dark:focus:bg-slate-850 p-1.5 border border-transparent focus:border-slate-300 dark:focus:border-slate-700 rounded text-xs text-slate-700 dark:text-slate-300 transition-all focus:shadow-sm"
                      />
                    </td>

                    <td className="py-2 px-3 text-center align-middle">
                      <button
                        type="button"
                        onClick={() => handleCellChange(idx, "hidden", !row.hidden)}
                        className={`inline-flex items-center justify-center p-1.5 rounded-lg transition-colors ${
                          row.hidden
                            ? "bg-slate-100 hover:bg-slate-200 text-slate-400 dark:bg-slate-800 dark:hover:bg-slate-700"
                            : "bg-green-50 hover:bg-green-100 text-green-600 dark:bg-green-950/20 dark:hover:bg-green-950/40 dark:text-green-400"
                        }`}
                        title={row.hidden ? "目前已隱藏，點擊以顯示" : "目前顯示中，點擊以隱藏"}
                      >
                        <span className="material-symbols-outlined text-[1.125rem]">
                          {row.hidden ? "visibility_off" : "visibility"}
                        </span>
                      </button>
                    </td>

                    <td className="py-2 px-3 text-center align-middle">
                      <button
                        type="button"
                        onClick={() => handleRemoveRow(idx)}
                        className="inline-flex items-center justify-center p-1.5 rounded-lg text-slate-400 hover:text-red-600 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/20 transition-all"
                        title="刪除此行"
                      >
                        <span className="material-symbols-outlined text-[1.125rem]">delete</span>
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="flex items-center justify-between border-t border-slate-200 dark:border-slate-800 px-6 py-4 bg-slate-50/50 dark:bg-slate-950/20 shrink-0">
        <button
          type="button"
          onClick={handleAddRow}
          disabled={loading || saving}
          className="inline-flex items-center gap-1.5 rounded-lg border border-primary/30 bg-primary/5 px-4 py-2 text-xs font-semibold text-primary transition-colors hover:bg-primary/10 disabled:opacity-40"
        >
          <span className="material-symbols-outlined text-[1.1rem]">add</span>
          新增一列
        </button>

        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={handleCancel}
            disabled={loading || saving || !isDirty}
            className="rounded-lg border border-slate-200 dark:border-slate-700 px-4 py-2 text-xs font-semibold text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-white dark:hover:bg-slate-800 transition-colors disabled:opacity-45"
          >
            取消
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={loading || saving || !isDirty}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-4.5 py-2 text-xs font-semibold text-white transition-colors hover:bg-primary/90 disabled:opacity-45"
          >
            {saving ? (
              <>
                <span className="material-symbols-outlined text-[1.1rem] animate-spin">sync</span>
                儲存中...
              </>
            ) : (
              <>
                <span className="material-symbols-outlined text-[1.1rem]">save</span>
                儲存變更
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
