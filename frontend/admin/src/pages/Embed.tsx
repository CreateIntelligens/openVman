import { useState } from "react";
import { postEmbed } from "../api";
import StatusAlert from "../components/StatusAlert";

interface EmbedResult {
  count: number;
  dim: number;
  vectors: number[][];
}

const PREVIEW_LIMIT = 100;

export default function Embed() {
  const [input, setInput] = useState("");
  const [result, setResult] = useState<EmbedResult | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const [copied, setCopied] = useState(false);

  const submit = () => {
    const texts = input.split("\n").map((s) => s.trim()).filter(Boolean);
    if (!texts.length) return;
    setError("");
    setLoading(true);
    setShowAll(false);
    postEmbed<EmbedResult>(texts)
      .then((r) => setResult(r))
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  };

  const copyJson = () => {
    if (!result) return;
    navigator.clipboard.writeText(JSON.stringify(result.vectors, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const allValues = result?.vectors.flat() ?? [];
  const displayValues = showAll ? allValues : allValues.slice(0, PREVIEW_LIMIT);
  const hasMore = allValues.length > PREVIEW_LIMIT;

  return (
    <div className="page-scroll">
      {/* Header */}
      <header className="sticky top-0 z-10 px-8 py-4 bg-background-dark/80 backdrop-blur-md border-b border-primary/10">
        <h2 className="text-2xl font-bold">文字嵌入</h2>
        <p className="text-sm text-slate-400">將原始文字轉換為高維向量嵌入。</p>
      </header>

      <div className="p-8">
        <div className="max-w-4xl space-y-6">
          {/* Input */}
          <div className="bg-primary/5 rounded-xl border border-primary/20 p-6">
            <div className="flex items-center justify-between mb-4">
              <label className="text-sm font-bold" htmlFor="embed-input">輸入文字</label>
              <span className="text-xs text-slate-500">
                {input.length.toLocaleString()} 字元
              </span>
            </div>
            <textarea
              id="embed-input"
              className="w-full bg-background-dark border border-primary/30 rounded-lg p-4 text-slate-100 text-sm focus:ring-2 focus:ring-primary focus:border-transparent resize-none placeholder-slate-500"
              placeholder="每行一筆文字..."
              rows={10}
              value={input}
              onChange={(e) => setInput(e.target.value)}
            />
            <div className="mt-4 flex justify-end">
              <button
                onClick={submit}
                disabled={loading || !input.trim()}
                className="bg-primary hover:bg-primary/90 text-white px-8 py-2.5 rounded-lg font-bold text-sm flex items-center gap-2 shadow-lg shadow-primary/30 transition-all active:scale-95 disabled:opacity-50"
              >
                <span className="material-symbols-outlined">auto_awesome</span>
                {loading ? "嵌入中..." : "嵌入文字"}
              </button>
            </div>
          </div>

          {error && <StatusAlert type="error" message={error} />}

          {/* Result */}
          {result && (
            <div className="bg-primary/5 rounded-xl border border-primary/20 overflow-hidden">
              <div className="px-6 py-4 border-b border-primary/20 bg-primary/10 flex items-center justify-between">
                <h3 className="text-sm font-bold">結果預覽</h3>
                <button
                  onClick={copyJson}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-primary/30 text-xs font-semibold text-primary hover:bg-primary/10 transition-colors"
                >
                  <span className="material-symbols-outlined text-[16px]">
                    {copied ? "check" : "content_copy"}
                  </span>
                  {copied ? "已複製！" : "複製 JSON"}
                </button>
              </div>
              {/* Stats */}
              <div className="grid grid-cols-2 divide-x divide-primary/20 border-b border-primary/20">
                <div className="p-4 text-center">
                  <p className="text-xs text-slate-500 font-medium">數量</p>
                  <p className="text-xl font-black">{result.count}</p>
                </div>
                <div className="p-4 text-center">
                  <p className="text-xs text-slate-500 font-medium">維度</p>
                  <p className="text-xl font-black">{result.dim.toLocaleString()}</p>
                </div>
              </div>
              {/* Vectors preview */}
              <div className="p-6">
                <p className="text-xs font-bold uppercase tracking-wider mb-4">
                  <span className="material-symbols-outlined text-primary text-sm align-middle mr-1">list</span>
                  向量分量 ({showAll ? allValues.length : `${displayValues.length} / ${allValues.length}`})
                </p>
                <div className="grid grid-cols-5 sm:grid-cols-8 gap-2">
                  {displayValues.map((v, i) => (
                    <div
                      key={i}
                      className="bg-background-dark p-2 rounded text-[10px] font-mono text-center border border-primary/10"
                    >
                      {v.toFixed(4)}
                    </div>
                  ))}
                </div>
                {hasMore && !showAll && (
                  <button
                    onClick={() => setShowAll(true)}
                    className="mt-4 px-4 py-2 rounded-lg border border-slate-700 text-xs font-semibold text-slate-300 hover:text-white hover:border-slate-500 transition-colors"
                  >
                    顯示全部 {allValues.length} 個分量
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
