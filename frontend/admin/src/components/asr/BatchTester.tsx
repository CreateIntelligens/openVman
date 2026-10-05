import { useEffect, useRef, useState } from "react";

import { fetchAsrEngines, previewAsr, type AsrPreview } from "../../api/settings";
import { useVad } from "../../hooks/useVad";
import { charErrorRate } from "../../utils/charErrorRate";
import { SERVER_ASR_ENGINES, VAD_SAMPLE_RATE, describeAsrEngine as describe, encodeWav } from "@shared/speech";

/** 留最近幾段，太多會讓頁面一直變長；每段都佔一個 object URL。 */
const MAX_CLIPS = 5;

type Row =
  | { engine: string; state: "pending" }
  | { engine: string; state: "done"; preview: AsrPreview }
  | { engine: string; state: "error"; message: string };

interface Clip {
  id: number;
  label: string;
  url: string;
  rows: Row[];
}

interface BatchTesterProps {
  projectId: string;
  routes: string[];
}

/**
 * 批次試辨識：同一段音檔同時送給勾選的引擎，結果並排比較。
 *
 * 每家是不同機器，一家各送一句不會互相排隊，耗時由後端各自量，並行不影響比較。
 * 只列部署設定齊全的引擎：沒設定的選了也只會被備援接走。
 * 收音一律走 VAD：講完一句自動送出，連續講就一句一句出結果，跟正式對話一樣。
 * 帶專案與語言分流，跟正式對話一樣套詞表、開台語分流時聽是不是台語，但引擎照勾選的跑。
 */
export default function BatchTester({ projectId, routes }: BatchTesterProps) {
  const [offered, setOffered] = useState<string[]>([...SERVER_ASR_ENGINES]);
  const [engines, setEngines] = useState<string[]>([SERVER_ASR_ENGINES[0]]);
  const [reference, setReference] = useState("");
  const [clips, setClips] = useState<Clip[]>([]);
  const [listening, setListening] = useState(false);
  // 連續講時上一句還沒辨識完下一句就送了，用計數而不是布林。
  const [pending, setPending] = useState(0);
  const [error, setError] = useState("");
  const nextId = useRef(1);
  const clipsRef = useRef<Clip[]>([]);
  clipsRef.current = clips;
  // VAD 送出那一刻要用當下的勾選，不能用建立 callback 時的舊值。
  const contextRef = useRef({ engines, projectId, routes });
  contextRef.current = { engines, projectId, routes };

  useEffect(() => {
    let cancelled = false;
    fetchAsrEngines()
      .then((configured) => {
        if (cancelled) return;
        const usable: string[] = SERVER_ASR_ENGINES.filter((id) => configured.includes(id));
        setOffered(usable);
        setEngines((current) => {
          const kept = current.filter((id) => usable.includes(id));
          return kept.length ? kept : usable.slice(0, 1);
        });
      })
      // 讀不到就照全部列，試辨識本身還是能用。
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const vad = useVad({
    enabled: listening,
    onSpeechCommit: () => {},
    onAudio: (samples) => {
      void runClip(encodeWav(samples, VAD_SAMPLE_RATE), `第 ${nextId.current} 句`, "speech.wav");
    },
  });

  function updateRow(id: number, engine: string, row: Row) {
    setClips((current) => current.map((clip) => (clip.id === id
      ? { ...clip, rows: clip.rows.map((existing) => (existing.engine === engine ? row : existing)) }
      : clip)));
  }

  async function runClip(blob: Blob, label: string, filename?: string) {
    const { engines: chosen, projectId: project, routes: picked } = contextRef.current;
    if (!chosen.length) {
      setError("至少勾一個引擎。");
      return;
    }
    setError("");
    const id = nextId.current++;
    const clip: Clip = {
      id,
      label,
      url: URL.createObjectURL(blob),
      rows: chosen.map((engine) => ({ engine, state: "pending" })),
    };
    setClips((current) => {
      const kept = [clip, ...current];
      kept.slice(MAX_CLIPS).forEach((old) => URL.revokeObjectURL(old.url));
      return kept.slice(0, MAX_CLIPS);
    });
    setPending((count) => count + 1);
    try {
      await Promise.all(chosen.map(async (engine) => {
        try {
          const preview = await previewAsr(blob, filename, engine, {
            projectId: project,
            languageRoutes: picked.join(","),
          });
          updateRow(id, engine, { engine, state: "done", preview });
        } catch (reason) {
          updateRow(id, engine, {
            engine,
            state: "error",
            message: reason instanceof Error ? reason.message : "辨識失敗",
          });
        }
      }));
    } finally {
      setPending((count) => count - 1);
    }
  }

  useEffect(() => () => {
    clipsRef.current.forEach((clip) => URL.revokeObjectURL(clip.url));
  }, []);

  return (
    <section className="flex flex-col gap-4" aria-labelledby="asr-batch-title">
      <div className="flex flex-col gap-1">
        <h2 id="asr-batch-title" className="text-sm font-semibold">試辨識</h2>
        <p className="text-xs leading-5 text-content-muted">
          勾幾個引擎，按「開始講話」直接講，每講完一句會自動送出，同一句同時給每一家辨識、結果並排比較；也可以上傳音檔。
          跟正式對話一樣套專案詞表與語言分流；開台語分流時另外聽是不是台語，但引擎照勾的跑（正式對話會換成 Breeze）。
          只影響這一次，不會改任何人的設定。
        </p>
      </div>

      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap gap-2" role="group" aria-label="試辨識的引擎">
          {offered.map((id) => {
            const on = engines.includes(id);
            return (
              <button
                key={id}
                type="button"
                aria-pressed={on}
                onClick={() => setEngines(on ? engines.filter((e) => e !== id) : [...engines, id])}
                className={`btn px-3 py-1 text-xs ${on ? "btn-primary" : "btn-ghost"}`}
              >
                {describe(id).label}
              </button>
            );
          })}
        </div>
        {engines.length > 0 && (
          <ul className="flex flex-col gap-1 text-xs leading-5 text-content-muted">
            {engines.map((id) => {
              const { label, note } = describe(id);
              return note ? <li key={id}><span className="font-medium">{label}</span>：{note}</li> : null;
            })}
          </ul>
        )}
      </div>

      <label className="flex flex-col gap-1 text-xs text-content-muted">
        參考文字（選填：填了就算錯字率，跟 voice_e2e 同一個算法）
        <input
          className="input"
          value={reference}
          placeholder="例如：沉水泵最深可以放多深？"
          onChange={(event) => setReference(event.target.value)}
        />
      </label>

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          aria-pressed={listening}
          className={listening ? "btn btn-danger" : "btn btn-primary"}
          disabled={!vad.supported && !listening}
          title={vad.supported ? "講完一句自動送出，可以連續講" : "這個瀏覽器載不到 VAD 模型"}
          onClick={() => setListening(!listening)}
        >
          {listening ? "停止講話" : "開始講話"}
        </button>
        <label className={`btn btn-ghost ${listening ? "pointer-events-none opacity-50" : "cursor-pointer"}`}>
          上傳音檔
          <input
            type="file"
            accept="audio/*"
            className="sr-only"
            disabled={listening}
            onChange={(event) => {
              const input = event.target;
              const picked = input.files?.[0];
              if (picked) void runClip(picked, picked.name, picked.name);
              // 清 value 要等取完檔案：先清就讀不到 files。清它是為了讓同一個檔案能再選一次。
              input.value = "";
            }}
          />
        </label>
        {listening && (
          <span role="status" className="text-xs text-content-muted">
            {vad.starting ? "麥克風準備中…" : vad.speaking ? "聽到聲音了…" : "請說話，講完一句會自動送出"}
          </span>
        )}
        {pending > 0 && <span role="status" className="text-xs text-content-muted">辨識中…</span>}
      </div>

      {error && <p role="alert" className="text-sm text-danger">{error}</p>}

      {clips.map((clip) => (
        <ClipResult key={clip.id} clip={clip} reference={reference} />
      ))}
    </section>
  );
}

function ClipResult({ clip, reference }: { clip: Clip; reference: string }) {
  const first = clip.rows.find((row): row is Extract<Row, { state: "done" }> => row.state === "done");
  const check = first?.preview.language_check;
  return (
    <div className="card flex flex-col gap-3 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs font-medium">{clip.label}</span>
        <audio controls src={clip.url} className="h-8 max-w-full" aria-label={`${clip.label} 回放`} />
      </div>
      {first && (
        <div className="flex flex-wrap gap-2 text-xs">
          <span className="chip">分流：{(first.preview.language_routes ?? []).join("、") || "—"}</span>
          <span className="chip">{first.preview.glossary ? "有套用專案詞表" : "沒有套用詞表"}</span>
          {check && (
            <span className="chip">
              台語判斷：{check.result === "nan" ? "是台語" : check.result === "timeout" ? "逾時" : check.result === "failed" ? "失敗" : "不是台語"}（{check.ms} ms）
            </span>
          )}
        </div>
      )}
      <ul className="flex flex-col divide-y divide-border">
        {clip.rows.map((row) => (
          <li key={row.engine} className="flex flex-col gap-1 py-2">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <span className="text-xs font-medium">{describe(row.engine).label}</span>
              {row.state === "done" && (
                <span className="text-xs text-content-muted">
                  {row.preview.elapsed_seconds !== undefined && `${row.preview.elapsed_seconds.toFixed(2)} 秒`}
                  {reference.trim() && `・錯字率 ${(charErrorRate(reference, row.preview.text) * 100).toFixed(1)}%`}
                </span>
              )}
            </div>
            {row.state === "pending" && <span className="text-sm text-content-muted">辨識中…</span>}
            {row.state === "error" && <span className="text-sm text-danger">{row.message}</span>}
            {row.state === "done" && (
              <>
                <p className="text-sm">{row.preview.text || "（沒有辨識出文字）"}</p>
                {row.preview.provider && row.preview.provider !== row.engine && (
                  // 指定的引擎沒回應時會由備援接手，不講清楚會以為是選的那家辨識的。
                  <p className="text-xs text-content-muted">
                    {describe(row.engine).label} 沒有回應，這次由 {describe(row.preview.provider).label} 辨識。
                  </p>
                )}
              </>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
