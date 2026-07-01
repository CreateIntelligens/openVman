import { type ChangeEvent, type DragEvent, useMemo, useRef, useState } from "react";

import { type ManualQaInput, type QaNode, useQaNodes } from "../../../hooks/useQaNodes";

type UploadTab = "csv" | "manual" | "image";
type DialogMessage = { type: "success" | "error"; text: string };
type ManualQaRow = Required<ManualQaInput>;

interface UploadDialogProps {
  open: boolean;
  onClose: () => void;
  nodesTree: QaNode[];
  onSuccess?: () => void;
  defaultNodeId?: string;
}

interface FlatNode {
  node_id: string;
  label: string;
  depth: number;
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

function flattenNodes(nodes: QaNode[], depth = 0, visited = new Set<string>()): FlatNode[] {
  const result: FlatNode[] = [];
  nodes.forEach((node) => {
    if (visited.has(node.node_id)) return;
    visited.add(node.node_id);
    result.push({ node_id: node.node_id, label: node.label, depth });
    if (node.children && node.children.length > 0) {
      result.push(...flattenNodes(node.children, depth + 1, visited));
    }
  });
  return result;
}

export default function UploadDialog({
  open,
  onClose,
  nodesTree,
  onSuccess,
  defaultNodeId = "",
}: UploadDialogProps) {
  const { uploadCsv, addManualQa, uploadImage, cleanupImages } = useQaNodes();

  const [selectedNodeId, setSelectedNodeId] = useState(defaultNodeId);
  const [activeTab, setActiveTab] = useState<UploadTab>("csv");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<DialogMessage | null>(null);

  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [isCsvDragOver, setIsCsvDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [manualRows, setManualRows] = useState<ManualQaRow[]>([
    { q: "", a: "", img: "", url: "" },
  ]);

  const [imageFile, setImageFile] = useState<File | null>(null);
  const [isImageDragOver, setIsImageDragOver] = useState(false);
  const [uploadedImages, setUploadedImages] = useState<string[]>([]);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);

  const flatNodes = useMemo(() => flattenNodes(nodesTree), [nodesTree]);

  const handleClose = () => {
    if (loading) return;
    setCsvFile(null);
    setManualRows([{ q: "", a: "", img: "", url: "" }]);
    setImageFile(null);
    setMessage(null);
    onClose();
  };

  const handleCsvDragOver = (e: DragEvent) => {
    e.preventDefault();
    setIsCsvDragOver(true);
  };

  const handleCsvDragLeave = () => {
    setIsCsvDragOver(false);
  };

  const handleCsvDrop = (e: DragEvent) => {
    e.preventDefault();
    setIsCsvDragOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const file = e.dataTransfer.files[0];
      if (file.name.endsWith(".csv")) {
        setCsvFile(file);
        setMessage(null);
      } else {
        setMessage({ type: "error", text: "請上傳符合格式的 CSV 檔案" });
      }
    }
  };

  const handleCsvSelect = (e: ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setCsvFile(e.target.files[0]);
      setMessage(null);
    }
  };

  const handleCsvUploadSubmit = async () => {
    if (!selectedNodeId || !csvFile) return;
    setLoading(true);
    setMessage(null);
    try {
      await uploadCsv(selectedNodeId, csvFile);
      setMessage({ type: "success", text: "CSV 檔案上傳並解析成功！" });
      setCsvFile(null);
      onSuccess?.();
    } catch (error: unknown) {
      setMessage({ type: "error", text: errorMessage(error, "上傳 CSV 失敗") });
    } finally {
      setLoading(false);
    }
  };

  const handleAddRow = () => {
    setManualRows([...manualRows, { q: "", a: "", img: "", url: "" }]);
  };

  const handleRemoveRow = (index: number) => {
    if (manualRows.length === 1) {
      setManualRows([{ q: "", a: "", img: "", url: "" }]);
    } else {
      setManualRows(manualRows.filter((_, i) => i !== index));
    }
  };

  const handleRowChange = (index: number, field: keyof ManualQaRow, value: string) => {
    const updated = manualRows.map((row, i) => {
      if (i === index) {
        return { ...row, [field]: value };
      }
      return row;
    });
    setManualRows(updated);
  };

  const handleManualSubmit = async () => {
    if (!selectedNodeId) return;
    const validRows = manualRows
      .filter((row) => row.q.trim() !== "" && row.a.trim() !== "")
      .map((row) => ({
        q: row.q.trim(),
        a: row.a.trim(),
        img: row.img.trim() || undefined,
        url: row.url.trim() || undefined,
      }));

    if (validRows.length === 0) {
      setMessage({ type: "error", text: "請填寫至少一筆完整的問題與答案" });
      return;
    }

    setLoading(true);
    setMessage(null);
    try {
      await addManualQa(selectedNodeId, validRows);
      setMessage({ type: "success", text: `成功新增 ${validRows.length} 筆問答！` });
      setManualRows([{ q: "", a: "", img: "", url: "" }]);
      onSuccess?.();
    } catch (error: unknown) {
      setMessage({ type: "error", text: errorMessage(error, "新增手動問答失敗") });
    } finally {
      setLoading(false);
    }
  };

  const handleImageDragOver = (e: DragEvent) => {
    e.preventDefault();
    setIsImageDragOver(true);
  };

  const handleImageDragLeave = () => {
    setIsImageDragOver(false);
  };

  const handleImageDrop = (e: DragEvent) => {
    e.preventDefault();
    setIsImageDragOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const file = e.dataTransfer.files[0];
      if (file.type.startsWith("image/")) {
        setImageFile(file);
        setMessage(null);
      } else {
        setMessage({ type: "error", text: "請上傳圖片檔案 (PNG, JPG, SVG 等)" });
      }
    }
  };

  const handleImageSelect = (e: ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setImageFile(e.target.files[0]);
      setMessage(null);
    }
  };

  const handleImageUploadSubmit = async () => {
    if (!imageFile) return;
    setLoading(true);
    setMessage(null);
    try {
      const res = await uploadImage(imageFile);
      setUploadedImages((prev) => [res.image_id, ...prev]);
      setImageFile(null);
      setMessage({ type: "success", text: "圖片上傳成功！" });
    } catch (error: unknown) {
      setMessage({ type: "error", text: errorMessage(error, "上傳圖片失敗") });
    } finally {
      setLoading(false);
    }
  };

  const handleCopyImageId = (id: string) => {
    const fallbackCopy = () => {
      try {
        const textarea = document.createElement("textarea");
        textarea.value = id;
        textarea.style.position = "fixed";
        textarea.style.opacity = "0";
        document.body.appendChild(textarea);
        textarea.select();
        const success = document.execCommand("copy");
        document.body.removeChild(textarea);
        if (success) {
          setCopiedId(id);
          setTimeout(() => setCopiedId(null), 2000);
        } else {
          setMessage({ type: "error", text: "無法複製圖片 ID，請手動選取複製" });
        }
      } catch {
        setMessage({ type: "error", text: "無法複製圖片 ID，請手動選取複製" });
      }
    };

    if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
      navigator.clipboard.writeText(id)
        .then(() => {
          setCopiedId(id);
          setTimeout(() => setCopiedId(null), 2000);
        })
        .catch(() => {
          fallbackCopy();
        });
    } else {
      fallbackCopy();
    }
  };

  const handleCleanupImages = async () => {
    if (!window.confirm("確定要清理所有未使用的圖片嗎？此操作將會刪除後端伺服器上未被任何問答引用的圖片檔案。")) return;
    setLoading(true);
    setMessage(null);
    try {
      const res = await cleanupImages();
      setMessage({
        type: "success",
        text: `清理完成！共刪除了 ${res.deleted_files.length} 個未使用的圖片檔案。`,
      });
    } catch (error: unknown) {
      setMessage({ type: "error", text: errorMessage(error, "清理圖片失敗") });
    } finally {
      setLoading(false);
    }
  };

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === e.currentTarget) handleClose();
      }}
    >
      <div
        className="mx-4 flex max-h-[90dvh] w-full max-w-4xl flex-col rounded-2xl border border-slate-200 bg-white shadow-2xl dark:border-slate-800 dark:bg-slate-900"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4 dark:border-slate-800">
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-[1.25rem] text-primary">cloud_upload</span>
            <span className="text-base font-semibold text-slate-900 dark:text-white">上傳與新增問答數據</span>
          </div>
          <button
            onClick={handleClose}
            className="rounded-lg p-1.5 text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-white"
          >
            <span className="material-symbols-outlined text-[1.125rem]">close</span>
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          <div className="space-y-2">
            <label className="block text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">
              目標節點 <span className="text-red-500">*</span>
            </label>
            <select
              value={selectedNodeId}
              onChange={(e) => {
                setSelectedNodeId(e.target.value);
                setMessage(null);
              }}
              className="w-full rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-950 focus:border-primary/50 focus:outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-white"
            >
              <option value="">-- 請選擇目標節點 --</option>
              {flatNodes.map((n) => (
                <option key={n.node_id} value={n.node_id}>
                  {"\u00A0\u00A0\u00A0\u00A0".repeat(n.depth)}
                  {n.depth > 0 ? "├─ " : ""}
                  {n.label} ({n.node_id})
                </option>
              ))}
            </select>
            {!selectedNodeId && (
              <p className="text-xs text-amber-500 flex items-center gap-1">
                <span className="material-symbols-outlined text-[0.875rem]">info</span>
                請先選擇一個目標節點，以啟用 CSV 上傳與手動輸入功能。
              </p>
            )}
          </div>

          <div className="border-b border-slate-200 dark:border-slate-800">
            <div className="flex gap-4">
              <button
                onClick={() => {
                  setActiveTab("csv");
                  setMessage(null);
                }}
                className={`pb-3 text-sm font-semibold transition-all border-b-2 px-1 ${
                  activeTab === "csv"
                    ? "border-primary text-primary"
                    : "border-transparent text-slate-500 hover:text-slate-700 dark:hover:text-slate-300"
                }`}
              >
                CSV 上傳
              </button>
              <button
                onClick={() => {
                  setActiveTab("manual");
                  setMessage(null);
                }}
                className={`pb-3 text-sm font-semibold transition-all border-b-2 px-1 ${
                  activeTab === "manual"
                    ? "border-primary text-primary"
                    : "border-transparent text-slate-500 hover:text-slate-700 dark:hover:text-slate-300"
                }`}
              >
                手動輸入
              </button>
              <button
                onClick={() => {
                  setActiveTab("image");
                  setMessage(null);
                }}
                className={`pb-3 text-sm font-semibold transition-all border-b-2 px-1 ${
                  activeTab === "image"
                    ? "border-primary text-primary"
                    : "border-transparent text-slate-500 hover:text-slate-700 dark:hover:text-slate-300"
                }`}
              >
                上傳圖片
              </button>
            </div>
          </div>

          {message && (
            <div
              className={`flex items-start gap-2.5 rounded-lg p-3 text-xs leading-relaxed ${
                message.type === "success"
                  ? "bg-green-50 text-green-800 dark:bg-green-950/30 dark:text-green-300 border border-green-200 dark:border-green-800/30"
                  : "bg-red-50 text-red-800 dark:bg-red-950/30 dark:text-red-300 border border-red-200 dark:border-red-800/30"
              }`}
            >
              <span className="material-symbols-outlined text-[1.125rem] shrink-0 mt-0.5">
                {message.type === "success" ? "check_circle" : "error"}
              </span>
              <div>{message.text}</div>
            </div>
          )}

          {activeTab === "csv" && (
            <div className="space-y-4">
              <div
                onDragOver={handleCsvDragOver}
                onDragLeave={handleCsvDragLeave}
                onDrop={handleCsvDrop}
                onClick={() => fileInputRef.current?.click()}
                className={`flex flex-col items-center justify-center border-2 border-dashed rounded-xl p-8 cursor-pointer transition-all duration-150 ${
                  isCsvDragOver
                    ? "border-primary bg-primary/5"
                    : "border-slate-200 dark:border-slate-800 hover:border-slate-300 dark:hover:border-slate-700 bg-slate-50/50 dark:bg-slate-950/20"
                }`}
              >
                <input
                  type="file"
                  ref={fileInputRef}
                  onChange={handleCsvSelect}
                  accept=".csv"
                  className="hidden"
                />
                <span className="material-symbols-outlined text-[2.5rem] text-slate-400 dark:text-slate-500 mb-3">
                  csv
                </span>
                {csvFile ? (
                  <div className="text-center space-y-1">
                    <p className="text-sm font-bold text-slate-800 dark:text-slate-200">{csvFile.name}</p>
                    <p className="text-xs text-slate-500">{(csvFile.size / 1024).toFixed(2)} KB</p>
                  </div>
                ) : (
                  <div className="text-center space-y-1">
                    <p className="text-sm font-medium text-slate-700 dark:text-slate-300">
                      拖放 CSV 檔案至此，或點擊以瀏覽電腦檔案
                    </p>
                    <p className="text-xs text-slate-400">僅支援 .csv 格式</p>
                  </div>
                )}
              </div>

              <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-950/40">
                <h4 className="text-xs font-bold uppercase tracking-wider text-slate-700 dark:text-slate-300 mb-2.5 flex items-center gap-1.5">
                  <span className="material-symbols-outlined text-[1rem] text-primary">rule</span>
                  CSV 欄位別名映射規則
                </h4>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs text-slate-600 dark:text-slate-400">
                  <div className="space-y-1">
                    <span className="font-semibold text-slate-800 dark:text-slate-200">問 / Q：</span>
                    <code className="bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 rounded text-primary">
                      question, q, 問題, query, 問
                    </code>
                  </div>
                  <div className="space-y-1">
                    <span className="font-semibold text-slate-800 dark:text-slate-200">答 / A：</span>
                    <code className="bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 rounded text-primary">
                      answer, a, 答案, reply, 答
                    </code>
                  </div>
                  <div className="space-y-1">
                    <span className="font-semibold text-slate-800 dark:text-slate-200">圖片 / Image ID：</span>
                    <code className="bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 rounded text-primary">
                      image_id, img, 圖片, image, pic
                    </code>
                  </div>
                  <div className="space-y-1">
                    <span className="font-semibold text-slate-800 dark:text-slate-200">連結 / URL：</span>
                    <code className="bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 rounded text-primary">
                      url, link, 連結, 外部連結
                    </code>
                  </div>
                </div>
                <p className="text-[0.7rem] text-slate-400 dark:text-slate-500 mt-3 italic">
                  * 提示：系統會自動尋找符合上述別名的首行欄位進行對應，欄位順序不限。
                </p>
              </div>

              <div className="flex justify-end pt-2">
                <button
                  type="button"
                  onClick={handleCsvUploadSubmit}
                  disabled={loading || !selectedNodeId || !csvFile}
                  className="inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-primary/90 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  <span className={`material-symbols-outlined text-[1.125rem] ${loading ? "animate-spin" : ""}`}>
                    {loading ? "sync" : "upload"}
                  </span>
                  {loading ? "上傳中..." : "上傳並解析 CSV"}
                </button>
              </div>
            </div>
          )}

          {activeTab === "manual" && (
            <div className="space-y-4">
              <div className="space-y-3">
                {manualRows.map((row, index) => (
                  <div
                    key={index}
                    className="relative rounded-xl border border-slate-200 bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-950/40 space-y-3"
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold text-slate-500 dark:text-slate-400">
                        問答項目 #{index + 1}
                      </span>
                      <button
                        type="button"
                        onClick={() => handleRemoveRow(index)}
                        className="rounded-md p-1 text-slate-500 hover:bg-slate-200 hover:text-red-600 dark:text-slate-400 dark:hover:bg-slate-800 transition-colors"
                        title="移除此項"
                      >
                        <span className="material-symbols-outlined text-[1rem]">delete</span>
                      </button>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <div className="space-y-1">
                        <label className="text-xs font-medium text-slate-600 dark:text-slate-400">
                          問題 <span className="text-red-500">*</span>
                        </label>
                        <input
                          type="text"
                          value={row.q}
                          onChange={(e) => handleRowChange(index, "q", e.target.value)}
                          placeholder="請輸入問題內容"
                          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-950 focus:border-primary/50 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-white"
                        />
                      </div>

                      <div className="space-y-1">
                        <label className="text-xs font-medium text-slate-600 dark:text-slate-400">
                          答案 <span className="text-red-500">*</span>
                        </label>
                        <input
                          type="text"
                          value={row.a}
                          onChange={(e) => handleRowChange(index, "a", e.target.value)}
                          placeholder="請輸入答案內容"
                          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-950 focus:border-primary/50 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-white"
                        />
                      </div>

                      <div className="space-y-1">
                        <label className="text-xs font-medium text-slate-600 dark:text-slate-400">
                          圖片 ID (選填)
                        </label>
                        <input
                          type="text"
                          value={row.img}
                          onChange={(e) => handleRowChange(index, "img", e.target.value)}
                          placeholder="可於「上傳圖片」分頁取得並複製"
                          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-950 focus:border-primary/50 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-white"
                        />
                      </div>

                      <div className="space-y-1">
                        <label className="text-xs font-medium text-slate-600 dark:text-slate-400">
                          連結 URL (選填)
                        </label>
                        <input
                          type="text"
                          value={row.url}
                          onChange={(e) => handleRowChange(index, "url", e.target.value)}
                          placeholder="例如 https://example.com"
                          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-950 focus:border-primary/50 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-white"
                        />
                      </div>
                    </div>
                  </div>
                ))}
              </div>

              <div className="flex items-center justify-between pt-2">
                <button
                  type="button"
                  onClick={handleAddRow}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-primary/30 bg-primary/5 px-4 py-2 text-xs font-semibold text-primary transition-colors hover:bg-primary/10"
                >
                  <span className="material-symbols-outlined text-[1rem]">add</span>
                  新增一列
                </button>

                <button
                  type="button"
                  onClick={handleManualSubmit}
                  disabled={loading || !selectedNodeId}
                  className="inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-primary/90 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  <span className={`material-symbols-outlined text-[1.125rem] ${loading ? "animate-spin" : ""}`}>
                    {loading ? "sync" : "save"}
                  </span>
                  {loading ? "儲存中..." : "新增問答項目"}
                </button>
              </div>
            </div>
          )}

          {activeTab === "image" && (
            <div className="space-y-6">
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-500">
                  支援拖曳多個或單個圖片二進位檔案進行上傳。
                </span>
                <button
                  type="button"
                  onClick={handleCleanupImages}
                  disabled={loading}
                  className="inline-flex items-center gap-1 text-xs font-semibold px-3 py-1.5 border border-red-200 dark:border-red-900/50 hover:bg-red-50 dark:hover:bg-red-950/20 text-red-600 dark:text-red-400 rounded-lg transition-colors"
                >
                  <span className="material-symbols-outlined text-[1rem]">delete_sweep</span>
                  清理未使用圖片
                </button>
              </div>

              <div
                onDragOver={handleImageDragOver}
                onDragLeave={handleImageDragLeave}
                onDrop={handleImageDrop}
                onClick={() => imageInputRef.current?.click()}
                className={`flex flex-col items-center justify-center border-2 border-dashed rounded-xl p-8 cursor-pointer transition-all duration-150 ${
                  isImageDragOver
                    ? "border-primary bg-primary/5"
                    : "border-slate-200 dark:border-slate-800 hover:border-slate-300 dark:hover:border-slate-700 bg-slate-50/50 dark:bg-slate-950/20"
                }`}
              >
                <input
                  type="file"
                  ref={imageInputRef}
                  onChange={handleImageSelect}
                  accept="image/*"
                  className="hidden"
                />
                <span className="material-symbols-outlined text-[2.5rem] text-slate-400 dark:text-slate-500 mb-3">
                  image
                </span>
                {imageFile ? (
                  <div className="text-center space-y-1">
                    <p className="text-sm font-bold text-slate-800 dark:text-slate-200">{imageFile.name}</p>
                    <p className="text-xs text-slate-500">{(imageFile.size / 1024).toFixed(2)} KB</p>
                  </div>
                ) : (
                  <div className="text-center space-y-1">
                    <p className="text-sm font-medium text-slate-700 dark:text-slate-300">
                      拖放圖片檔案至此，或點擊以瀏覽電腦檔案
                    </p>
                    <p className="text-xs text-slate-400">支援 PNG, JPG, GIF, WEBP, SVG 等圖片格式</p>
                  </div>
                )}
              </div>

              {imageFile && (
                <div className="flex justify-end">
                  <button
                    type="button"
                    onClick={handleImageUploadSubmit}
                    disabled={loading}
                    className="inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-2 text-sm font-semibold text-white transition-colors hover:bg-primary/90 disabled:opacity-40"
                  >
                    <span className={`material-symbols-outlined text-[1.125rem] ${loading ? "animate-spin" : ""}`}>
                      {loading ? "sync" : "upload"}
                    </span>
                    {loading ? "上傳中..." : "上傳此圖片"}
                  </button>
                </div>
              )}

              {uploadedImages.length > 0 && (
                <div className="space-y-2">
                  <h4 className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                    本對話框已上傳之圖片列表 (點擊以複製 Image ID)
                  </h4>
                  <div className="divide-y divide-slate-100 dark:divide-slate-800 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden bg-white dark:bg-slate-950/20 max-h-[12.5rem] overflow-y-auto">
                    {uploadedImages.map((id) => (
                      <div
                        key={id}
                        onClick={() => handleCopyImageId(id)}
                        className="flex items-center justify-between p-3 hover:bg-slate-50 dark:hover:bg-slate-900 cursor-pointer transition-colors"
                      >
                        <div className="flex items-center gap-2.5 truncate">
                          <span className="material-symbols-outlined text-[1.25rem] text-slate-400 shrink-0">
                            image_search
                          </span>
                          <span className="text-xs font-mono text-slate-700 dark:text-slate-300 truncate">
                            {id}
                          </span>
                        </div>
                        <button
                          type="button"
                          className="flex items-center gap-1.5 text-xs text-primary font-semibold shrink-0"
                        >
                          <span className="material-symbols-outlined text-[1rem]">
                            {copiedId === id ? "check" : "content_copy"}
                          </span>
                          {copiedId === id ? "已複製" : "複製 ID"}
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        <div className="flex items-center justify-end border-t border-slate-200 px-6 py-4 dark:border-slate-800 shrink-0">
          <button
            type="button"
            onClick={handleClose}
            className="rounded-lg border border-slate-200 dark:border-slate-700 px-4 py-2 text-sm text-slate-500 transition-colors hover:bg-slate-50 hover:text-slate-800 dark:text-slate-400 dark:hover:bg-slate-850 dark:hover:text-white"
          >
            關閉
          </button>
        </div>
      </div>
    </div>
  );
}
