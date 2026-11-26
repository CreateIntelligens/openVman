import { useEffect, useRef, useState, type ChangeEvent } from "react";

import { fetchReplyLinks, saveReplyLinks, type ReplyLinks } from "../../api";
import { useUnsavedChanges } from "../../context/NavigationGuardContext";
import { useQaNodes, type QaNode } from "../../hooks/useQaNodes";
import QaImagePreview from "./QaImagePreview";

const EMPTY: ReplyLinks = { contact_image_id: null, catalog_url: null };

function collectImageIds(nodes: QaNode[], found = new Set<string>()): Set<string> {
  for (const node of nodes) {
    for (const entry of node.qa_entries ?? []) if (entry.image_id) found.add(entry.image_id);
    if (node.children) collectImageIds(node.children, found);
  }
  return found;
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/**
 * 回覆附件：專案每則回覆都會附上的聯絡圖片（例如洽詢用 QR code）與型錄網址。
 * 兩者都是專案層級，不綁人設；前台自己決定怎麼顯示。
 */
export default function ReplyAttachmentsButton({ projectId }: { projectId: string }) {
  const [open, setOpen] = useState(false);
  const [saved, setSaved] = useState<ReplyLinks>(EMPTY);
  const [imageDraft, setImageDraft] = useState<string | null>(null);
  const [urlDraft, setUrlDraft] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [status, setStatus] = useState<{ type: "success" | "error"; message: string } | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const latest = useRef(0);
  const { nodesTree, fetchTree, uploadImage } = useQaNodes(projectId);

  const dirty = imageDraft !== saved.contact_image_id || (urlDraft.trim() || null) !== saved.catalog_url;
  useUnsavedChanges("reply-attachments", dirty, "回覆附件", saving);

  const apply = (links: ReplyLinks) => {
    setSaved(links);
    setImageDraft(links.contact_image_id);
    setUrlDraft(links.catalog_url ?? "");
  };

  useEffect(() => {
    if (!open) return;
    const request = ++latest.current;
    setLoading(true);
    setLoadFailed(false);
    setStatus(null);
    void fetchReplyLinks(projectId)
      .then((links) => { if (request === latest.current) apply(links); })
      .catch((error) => {
        if (request !== latest.current) return;
        setLoadFailed(true);
        setStatus({ type: "error", message: errorText(error) });
      })
      .finally(() => { if (request === latest.current) setLoading(false); });
    void fetchTree().catch(() => undefined);
    // fetchTree 隨專案換身分；只在打開或換專案時讀一次。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, projectId]);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (!panelRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      buttonRef.current?.focus();
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  const persist = async (next: ReplyLinks, done: string) => {
    if (saving) return;
    setSaving(true);
    setStatus(null);
    try {
      apply(await saveReplyLinks(projectId, next));
      setStatus({ type: "success", message: done });
    } catch (error) {
      setStatus({ type: "error", message: errorText(error) });
    } finally {
      setSaving(false);
    }
  };

  const upload = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setUploading(true);
    setStatus(null);
    try {
      const { image_id } = await uploadImage(file);
      setImageDraft(image_id);
    } catch (error) {
      setStatus({ type: "error", message: errorText(error) });
    } finally {
      setUploading(false);
    }
  };

  const known = collectImageIds(nodesTree);
  if (imageDraft) known.add(imageDraft);
  const imageIds = [...known];
  const configured = Boolean(saved.contact_image_id || saved.catalog_url);

  return (
    <div className="sm:relative" ref={panelRef}>
      <button
        ref={buttonRef}
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-haspopup="dialog"
        className="btn btn-ghost max-sm:px-2"
      >
        <span aria-hidden="true" className="material-symbols-outlined hidden text-[1rem] sm:inline">qr_code_2</span>
        回覆附件{configured ? "（已設定）" : ""}
      </button>
      {open && (
        <div
          role="dialog"
          aria-label="回覆附件設定"
          className="absolute inset-x-4 top-full z-50 mt-1 max-h-[calc(100dvh-17.5rem)] overflow-y-auto rounded-lg border border-border bg-surface-raised p-4 shadow-lg sm:inset-x-auto sm:left-0 sm:max-h-[calc(100dvh-14rem)] sm:w-[24rem]"
        >
          <h2 className="text-sm font-semibold text-content">回覆附件</h2>
          <p className="mt-1 mb-3 text-xs text-content-muted">
            這個專案的每則回覆都會帶上這兩項，不論有沒有答案；顯示方式由前台決定。
          </p>

          <section className="flex flex-col gap-2" aria-label="聯絡圖片">
            <h3 className="text-sm font-medium text-content">聯絡圖片（例如洽詢用 QR code）</h3>
            {imageDraft ? <QaImagePreview imageId={imageDraft} alt="目前的聯絡圖片" /> : (
              <p className="text-xs text-content-muted">還沒有設定聯絡圖片。</p>
            )}
            {imageIds.length > 0 && (
              <div role="radiogroup" aria-label="從已上傳的圖片挑選" className="flex flex-wrap gap-2">
                {imageIds.map((id) => (
                  <button
                    key={id}
                    type="button"
                    role="radio"
                    aria-checked={imageDraft === id}
                    aria-label={`選用圖片 ${id}`}
                    disabled={loading || loadFailed}
                    onClick={() => setImageDraft(id)}
                    className={`rounded border p-1 ${imageDraft === id ? "border-primary" : "border-border"}`}
                  >
                    <QaImagePreview imageId={id} alt={`圖片 ${id}`} compact />
                  </button>
                ))}
              </div>
            )}
            <label className="flex flex-col gap-1 text-xs text-content-muted">
              上傳新圖片
              <input type="file" accept="image/*" disabled={uploading || saving} onChange={(event) => void upload(event)} />
            </label>
          </section>

          <section className="mt-4 flex flex-col gap-2" aria-label="型錄網址">
            <label htmlFor="reply-catalog-url" className="text-sm font-medium text-content">型錄網址</label>
            <input
              id="reply-catalog-url"
              type="url"
              className="input"
              maxLength={500}
              placeholder="https://"
              disabled={loading || loadFailed}
              value={urlDraft}
              onChange={(event) => setUrlDraft(event.target.value)}
            />
            <p className="text-xs text-content-muted">只收 https 網址，最多 500 字。前台會顯示「查看型錄」。</p>
          </section>

          <div className="mt-4 flex flex-wrap gap-2">
            <button
              type="button"
              className="btn btn-primary"
              disabled={saving || uploading || loading || loadFailed || !dirty}
              onClick={() => void persist({ contact_image_id: imageDraft, catalog_url: urlDraft.trim() || null }, "已儲存回覆附件")}
            >
              儲存
            </button>
            <button
              type="button"
              className="btn btn-ghost"
              disabled={saving || !saved.contact_image_id}
              onClick={() => void persist({ ...saved, contact_image_id: null }, "已清除聯絡圖片")}
            >
              清除聯絡圖片
            </button>
            <button
              type="button"
              className="btn btn-ghost"
              disabled={saving || !saved.catalog_url}
              onClick={() => void persist({ ...saved, catalog_url: null }, "已清除型錄網址")}
            >
              清除型錄網址
            </button>
          </div>
          {status && (
            <p role={status.type === "error" ? "alert" : "status"} className={`mt-2 text-xs ${status.type === "error" ? "text-danger" : "text-content-muted"}`}>
              {status.message}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
