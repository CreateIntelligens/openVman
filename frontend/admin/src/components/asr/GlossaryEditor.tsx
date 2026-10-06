import { useEffect, useState } from "react";

import { fetchKnowledgeDocument, saveKnowledgeDocument } from "../../api/knowledge";

export const GLOSSARY_PATH = "ASR_PROMPT.md";

/** 「常見誤聽：A→B」這種對照行只給對話模型看，不送辨識引擎。 */
function isMapping(line: string): boolean {
  return /→|->/.test(line);
}

export function summarizeGlossary(content: string) {
  const lines = content
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith("#") && !line.startsWith("＃"));
  return {
    terms: lines.filter((line) => !isMapping(line)).length,
    mappings: lines.filter(isMapping).length,
  };
}

/**
 * 專案詞表（workspace 根目錄的 ASR_PROMPT.md）。Breeze、R2T2、OpenAI 會把正確的詞當
 * 辨識前文，Gemini 串流逐詞拿去加權（customVocabulary），對話模型另外拿到「常見誤聽」
 * 對照自己改回來；SenseVoice、小米不吃。
 */
export default function GlossaryEditor({ projectId }: { projectId: string }) {
  const [content, setContent] = useState("");
  const [saved, setSaved] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    setNotice("");
    fetchKnowledgeDocument(GLOSSARY_PATH)
      .then((document) => {
        if (cancelled) return;
        setContent(document.content);
        setSaved(document.content);
      })
      .catch((reason: unknown) => {
        if (cancelled) return;
        const message = reason instanceof Error ? reason.message : "";
        // 沒建過詞表的專案回 404，當成空的；其他錯誤才要讓人知道。
        if (message.includes("找不到")) {
          setContent("");
          setSaved("");
        } else {
          setError(message || "讀不到詞表。");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  async function save() {
    setSaving(true);
    setError("");
    setNotice("");
    try {
      await saveKnowledgeDocument(GLOSSARY_PATH, content);
      setSaved(content);
      // Backend 把詞表快取 60 秒，存檔後不會馬上套用到下一句。
      setNotice("已儲存，約一分鐘內生效。");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "儲存失敗，請重試。");
    } finally {
      setSaving(false);
    }
  }

  const { terms, mappings } = summarizeGlossary(content);
  const dirty = content !== saved;

  return (
    <section className="flex flex-col gap-3" aria-labelledby="asr-glossary-title">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="asr-glossary-title" className="text-sm font-semibold">專案詞表</h2>
        {!loading && (
          <span className="text-xs text-content-muted">
            {terms} 個詞・{mappings} 條誤聽對照
          </span>
        )}
      </div>
      <p className="text-xs leading-5 text-content-muted">
        一行一個，或用頓號、逗號分開；有空白的詞（例如 DIVA PRO）算一個詞。Breeze、R2T2（批次與串流）、OpenAI 會拿這些詞當辨識前文，
        Gemini 串流取前 100 個詞加權，型號、品牌名比較容易聽對；SenseVoice、小米不吃。寫成「常見誤聽：沉睡泵→沉水泵」的行只給回答的模型看，不送辨識引擎，免得把錯字也教給它。
        「#」開頭的行是說明。
      </p>
      <textarea
        className="input min-h-[8rem] w-full resize-y font-mono text-xs"
        value={content}
        disabled={loading || saving}
        aria-label="專案詞表內容"
        placeholder={loading ? "讀取中…" : "DIVA\n沉水泵 泵浦 揚程\n常見誤聽：沉睡泵→沉水泵"}
        onChange={(event) => {
          setContent(event.target.value);
          setNotice("");
        }}
      />
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          className="btn btn-primary"
          disabled={!dirty || saving || loading}
          onClick={() => void save()}
        >
          {saving ? "儲存中…" : "儲存詞表"}
        </button>
        {dirty && !saving && (
          <button type="button" className="btn btn-ghost" onClick={() => setContent(saved)}>
            還原
          </button>
        )}
        {notice && <span role="status" className="text-xs text-content-muted">{notice}</span>}
      </div>
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
    </section>
  );
}
