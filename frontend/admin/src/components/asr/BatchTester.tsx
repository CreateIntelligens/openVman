import { useEffect, useRef, useState } from "react";

import { fetchAsrEngines, previewAsr, type AsrPreview } from "../../api/settings";
import { useVad } from "../../hooks/useVad";
import { charErrorRate } from "../../utils/charErrorRate";
import {
  BROWSER_ASR,
  BrowserRecognizer,
  SERVER_ASR_ENGINES,
  STREAM_ASR_ENGINES,
  VAD_SAMPLE_RATE,
  describeAsrEngine as describe,
  encodeWav,
  isStreamAsrEngine,
} from "@shared/speech";
import { streamTestUrl } from "./StreamTester";
import { streamClip } from "./streamClip";

/** 留最近幾段，太多會讓頁面一直變長；每段都佔一個 object URL。 */
const MAX_CLIPS = 5;
/** VAD 斷句後再等瀏覽器辨識這麼久：它的定稿通常比 VAD 晚一點到。 */
const BROWSER_SETTLE_MS = 1_500;
const BROWSER_LANGS: Record<string, string> = {
  zh: "zh-TW", en: "en-US", es: "es-ES", ja: "ja-JP", ko: "ko-KR",
};

// run 是這次請求的序號：重跑時舊請求晚回來不能蓋掉新結果。
type Row = { engine: string; run: number } & (
  | { state: "pending" }
  | { state: "done"; preview: AsrPreview }
  | { state: "error"; message: string }
);

interface Clip {
  id: number;
  label: string;
  url: string;
  blob: Blob;
  filename?: string;
  /** 每個引擎跑過的結果；取消勾選只是不顯示，勾回來不用重跑。 */
  results: Record<string, Row>;
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
 * 音檔留在頁面上：之後再勾的引擎直接拿畫面上的幾段去跑，改了分流或詞表按「重跑」，都不用重傳。
 * 串流引擎（Gemini Live、R2T2 串流）把同一段音檔照真實速度送進 /api/v1/asr/stream 取定稿，
 * 顯示的秒數是講完到定稿；批次引擎是轉寫本身的耗時，兩者意義不同。
 * 瀏覽器內建辨識只能聽麥克風，開始講話時跟 VAD 一起聽，每段歸給 VAD 切出的那一句。
 * 帶專案與語言分流，跟正式對話一樣套詞表、開台語分流時聽是不是台語，但引擎照勾選的跑。
 */
export default function BatchTester({ projectId, routes }: BatchTesterProps) {
  const [browserSupported] = useState(() => new BrowserRecognizer().supported);
  const [offered, setOffered] = useState<string[]>(() => [
    ...SERVER_ASR_ENGINES, ...STREAM_ASR_ENGINES, ...(browserSupported ? [BROWSER_ASR] : []),
  ]);
  const [engines, setEngines] = useState<string[]>([SERVER_ASR_ENGINES[0]]);
  const [reference, setReference] = useState("");
  const [clips, setClips] = useState<Clip[]>([]);
  const [listening, setListening] = useState(false);
  // 連續講時上一句還沒辨識完下一句就送了，用計數而不是布林。
  const [pending, setPending] = useState(0);
  const [error, setError] = useState("");
  const nextId = useRef(1);
  const nextRun = useRef(1);
  // 瀏覽器辨識上一句定稿之後累積的文字，VAD 切出下一段時整包交給那一段。
  const browserHeard = useRef("");
  const browserRef = useRef<BrowserRecognizer | null>(null);
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
        const usable: string[] = [
          ...SERVER_ASR_ENGINES.filter((id) => configured.engines.includes(id)),
          ...STREAM_ASR_ENGINES.filter((id) => configured.stream.includes(id)),
          ...(browserSupported ? [BROWSER_ASR] : []),
        ];
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

  const browserOn = listening && browserSupported && engines.includes(BROWSER_ASR);
  const spoken = routes.filter((route) => route !== "nan");
  const browserLang = BROWSER_LANGS[spoken.length === 1 ? spoken[0] : "zh"] ?? "zh-TW";
  useEffect(() => {
    if (!browserOn) return;
    browserHeard.current = "";
    const recognizer = new BrowserRecognizer({
      lang: browserLang,
      continuous: true,
      onResult: (text) => {
        browserHeard.current += text;
      },
    });
    browserRef.current = recognizer;
    recognizer.start();
    return () => {
      recognizer.dispose();
      browserRef.current = null;
    };
  }, [browserOn, browserLang]);

  const vad = useVad({
    enabled: listening,
    onSpeechCommit: () => {},
    onAudio: (samples) => {
      void runClip(encodeWav(samples, VAD_SAMPLE_RATE), `第 ${nextId.current} 句`, "speech.wav", true);
    },
  });

  function setRow(id: number, row: Row, onlyIfRun?: number) {
    setClips((current) => current.map((clip) => {
      if (clip.id !== id) return clip;
      if (onlyIfRun !== undefined && clip.results[row.engine]?.run !== onlyIfRun) return clip;
      return { ...clip, results: { ...clip.results, [row.engine]: row } };
    }));
  }

  async function runEngine(clip: Pick<Clip, "id" | "blob" | "filename">, engine: string) {
    const { projectId: project, routes: picked } = contextRef.current;
    const run = nextRun.current++;
    setRow(clip.id, { engine, run, state: "pending" });
    setPending((count) => count + 1);
    try {
      const preview = isStreamAsrEngine(engine)
        ? await streamClip(streamTestUrl(engine, project, picked), clip.blob).then(
          ({ text, elapsedSeconds }): AsrPreview => ({ text, provider: engine, elapsed_seconds: elapsedSeconds }),
        )
        : await previewAsr(clip.blob, clip.filename, engine, {
          projectId: project,
          languageRoutes: picked.join(","),
        });
      setRow(clip.id, { engine, run, state: "done", preview }, run);
    } catch (reason) {
      setRow(clip.id, {
        engine,
        run,
        state: "error",
        message: reason instanceof Error ? reason.message : "辨識失敗",
      }, run);
    } finally {
      setPending((count) => count - 1);
    }
  }

  /** 瀏覽器辨識沒有音檔可送：只有麥克風講的那一句，等它定稿後把聽到的字交給這一段。 */
  function takeBrowserResult(clip: Clip) {
    const run = nextRun.current++;
    setRow(clip.id, { engine: BROWSER_ASR, run, state: "pending" });
    window.setTimeout(() => {
      const text = browserHeard.current.trim();
      browserHeard.current = "";
      setRow(clip.id, { engine: BROWSER_ASR, run, state: "done", preview: { text, provider: BROWSER_ASR } }, run);
    }, BROWSER_SETTLE_MS);
  }

  function markBrowserUnavailable(clip: Clip) {
    setRow(clip.id, {
      engine: BROWSER_ASR,
      run: nextRun.current++,
      state: "error",
      message: "瀏覽器內建辨識只能聽麥克風：按「開始講話」時才會一起聽，上傳的音檔或重跑沒辦法用。",
    });
  }

  function runEngineOrBrowser(clip: Clip, engine: string) {
    if (engine === BROWSER_ASR) markBrowserUnavailable(clip);
    else void runEngine(clip, engine);
  }

  function runClip(blob: Blob, label: string, filename?: string, fromMic = false) {
    const { engines: chosen } = contextRef.current;
    if (!chosen.length) {
      setError("至少勾一個引擎。");
      return;
    }
    setError("");
    const clip: Clip = { id: nextId.current++, label, url: URL.createObjectURL(blob), blob, filename, results: {} };
    setClips((current) => {
      const kept = [clip, ...current];
      kept.slice(MAX_CLIPS).forEach((old) => URL.revokeObjectURL(old.url));
      return kept.slice(0, MAX_CLIPS);
    });
    chosen.forEach((engine) => {
      if (engine === BROWSER_ASR && fromMic && browserRef.current) takeBrowserResult(clip);
      else runEngineOrBrowser(clip, engine);
    });
  }

  function toggleEngine(id: string) {
    if (engines.includes(id)) {
      setEngines(engines.filter((engine) => engine !== id));
      return;
    }
    setEngines([...engines, id]);
    // 畫面上的音檔還沒給這家跑過就補跑，不用重傳。
    clipsRef.current
      .filter((clip) => !clip.results[id])
      .forEach((clip) => runEngineOrBrowser(clip, id));
  }

  function rerun(clip: Clip) {
    engines.filter((engine) => engine !== BROWSER_ASR).forEach((engine) => void runEngine(clip, engine));
  }

  useEffect(() => () => {
    clipsRef.current.forEach((clip) => URL.revokeObjectURL(clip.url));
  }, []);

  return (
    <section className="flex flex-col gap-4" aria-labelledby="asr-batch-title">
      <div className="flex flex-col gap-1">
        <h2 id="asr-batch-title" className="text-sm font-semibold">試辨識</h2>
        <p className="text-xs leading-5 text-content-muted">
          勾幾個引擎，按「開始講話」直接講，每講完一句會自動送出，同一句同時給每一家辨識、結果並排比較；也可以上傳音檔。之後再勾的引擎會直接拿下面的音檔去跑；改了分流或詞表按「重跑」。串流引擎照真實速度送，秒數是講完到定稿；瀏覽器內建辨識只在「開始講話」時一起聽。
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
                onClick={() => toggleEngine(id)}
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
        <ClipResult
          key={clip.id}
          clip={clip}
          rows={engines.map((engine) => clip.results[engine]).filter((row): row is Row => Boolean(row))}
          reference={reference}
          onRerun={() => rerun(clip)}
        />
      ))}
    </section>
  );
}

function ClipResult({ clip, rows, reference, onRerun }: {
  clip: Clip;
  rows: Row[];
  reference: string;
  onRerun: () => void;
}) {
  const first = rows.find((row): row is Extract<Row, { state: "done" }> => row.state === "done");
  const check = first?.preview.language_check;
  return (
    <div className="card flex flex-col gap-3 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs font-medium">{clip.label}</span>
        <div className="flex items-center gap-2">
          <audio controls src={clip.url} className="h-8 max-w-full" aria-label={`${clip.label} 回放`} />
          <button
            type="button"
            className="btn btn-ghost px-3 py-1 text-xs"
            disabled={!rows.length || rows.some((row) => row.state === "pending")}
            onClick={onRerun}
            aria-label={`${clip.label} 重跑`}
          >
            重跑
          </button>
        </div>
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
        {rows.map((row) => (
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
