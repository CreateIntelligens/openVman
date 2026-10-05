import { useEffect, useRef, useState } from "react";

import { previewAsr, type AsrPreview } from "../../api/settings";
import { useVad } from "../../hooks/useVad";
import { charErrorRate } from "../../utils/charErrorRate";
import { preferredRecorderMimeType, rmsVolume } from "../../utils/liveAudioUtils";
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
 * 批次試辨識：同一段音檔依序送給勾選的引擎，結果並排比較。
 *
 * 一次只送一家：.35 同時多句會排隊變慢，並行送反而量不出各家真正的速度。
 * 帶專案與語言分流，跟正式對話一樣套詞表、開台語分流時聽是不是台語，但引擎照勾選的跑。
 */
export default function BatchTester({ projectId, routes }: BatchTesterProps) {
  const [engines, setEngines] = useState<string[]>([SERVER_ASR_ENGINES[0]]);
  const [reference, setReference] = useState("");
  const [clips, setClips] = useState<Clip[]>([]);
  const [recording, setRecording] = useState(false);
  const [autoSplit, setAutoSplit] = useState(false);
  const [busy, setBusy] = useState(false);
  const [level, setLevel] = useState(0);
  const [error, setError] = useState("");
  const nextId = useRef(1);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const meterFrameRef = useRef<number | null>(null);
  const clipsRef = useRef<Clip[]>([]);
  clipsRef.current = clips;
  // 錄音／自動斷句進來的那一刻要用當下的勾選，不能用建立 callback 時的舊值。
  const contextRef = useRef({ engines, projectId, routes });
  contextRef.current = { engines, projectId, routes };

  const vad = useVad({
    enabled: autoSplit,
    onSpeechCommit: () => {},
    onAudio: (samples) => {
      void runClip(encodeWav(samples, VAD_SAMPLE_RATE), `自動斷句 ${nextId.current}`, "speech.wav");
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
    setBusy(true);
    try {
      for (const engine of chosen) {
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
      }
    } finally {
      setBusy(false);
    }
  }

  function stopTracks() {
    if (meterFrameRef.current !== null) cancelAnimationFrame(meterFrameRef.current);
    meterFrameRef.current = null;
    void audioContextRef.current?.close().catch(() => {});
    audioContextRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    setLevel(0);
  }

  /** 錄音時顯示輸入音量：靜音的麥克風和「講了但沒收到」看起來一模一樣。 */
  function startMeter(stream: MediaStream) {
    try {
      const context = new AudioContext();
      audioContextRef.current = context;
      const analyser = context.createAnalyser();
      analyser.fftSize = 1024;
      context.createMediaStreamSource(stream).connect(analyser);
      const data = new Uint8Array(analyser.frequencyBinCount);
      const tick = () => {
        analyser.getByteTimeDomainData(data);
        setLevel(rmsVolume(data));
        meterFrameRef.current = requestAnimationFrame(tick);
      };
      tick();
    } catch {
      // 音量條只是輔助，拿不到 AudioContext 不該讓錄音失敗。
    }
  }

  async function startRecording() {
    setError("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const mimeType = preferredRecorderMimeType();
      // opus 壓到 24 kbps 時辨識會崩壞（「今仔日天氣袂歹」變「今拿日天氣袂買」），
      // 128 kbps 的結果與未壓縮的 WAV 一致。
      const recorder = new MediaRecorder(stream, {
        ...(mimeType ? { mimeType } : {}),
        audioBitsPerSecond: 128_000,
      });
      const chunks: Blob[] = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size) chunks.push(event.data);
      };
      recorder.onstop = () => {
        stopTracks();
        const blob = new Blob(chunks, { type: mimeType || "audio/webm" });
        if (!blob.size) {
          setError("沒有錄到聲音，請確認麥克風。");
          return;
        }
        void runClip(blob, "錄音");
      };
      recorderRef.current = recorder;
      recorder.start();
      startMeter(stream);
      setRecording(true);
    } catch {
      stopTracks();
      setError("無法存取麥克風，請檢查瀏覽器權限。");
    }
  }

  function stopRecording() {
    recorderRef.current?.stop();
    recorderRef.current = null;
    setRecording(false);
  }

  useEffect(() => () => {
    stopTracks();
    clipsRef.current.forEach((clip) => URL.revokeObjectURL(clip.url));
  }, []);

  const inputBusy = recording || autoSplit;

  return (
    <section className="flex flex-col gap-4" aria-labelledby="asr-batch-title">
      <div className="flex flex-col gap-1">
        <h2 id="asr-batch-title" className="text-sm font-semibold">試辨識</h2>
        <p className="text-xs leading-5 text-content-muted">
          勾幾個引擎，錄一段話、開自動斷句或上傳音檔，同一段音檔會依序送給每一家，結果並排比較。
          跟正式對話一樣套專案詞表與語言分流；開台語分流時另外聽是不是台語，但引擎照勾的跑（正式對話會換成 Breeze）。
          只影響這一次，不會改任何人的設定。
        </p>
      </div>

      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap gap-2" role="group" aria-label="試辨識的引擎">
          {SERVER_ASR_ENGINES.map((id) => {
            const on = engines.includes(id);
            return (
              <button
                key={id}
                type="button"
                aria-pressed={on}
                disabled={busy}
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
          className={recording ? "btn btn-danger" : "btn btn-primary"}
          disabled={autoSplit || busy}
          onClick={() => (recording ? stopRecording() : void startRecording())}
        >
          {recording ? "停止並辨識" : "錄一段"}
        </button>
        <button
          type="button"
          aria-pressed={autoSplit}
          className={autoSplit ? "btn btn-danger" : "btn btn-ghost"}
          disabled={recording || (!vad.supported && !autoSplit)}
          title={vad.supported ? "講完一句自動送出，可以連續講" : "這個瀏覽器載不到 VAD 模型"}
          onClick={() => setAutoSplit(!autoSplit)}
        >
          {autoSplit ? "停止自動斷句" : "自動斷句"}
        </button>
        <label className={`btn btn-ghost ${inputBusy || busy ? "pointer-events-none opacity-50" : "cursor-pointer"}`}>
          上傳音檔
          <input
            type="file"
            accept="audio/*"
            className="sr-only"
            disabled={inputBusy || busy}
            onChange={(event) => {
              const input = event.target;
              const picked = input.files?.[0];
              if (picked) void runClip(picked, picked.name, picked.name);
              // 清 value 要等取完檔案：先清就讀不到 files。清它是為了讓同一個檔案能再選一次。
              input.value = "";
            }}
          />
        </label>
        {recording && (
          <span className="flex items-center gap-2" aria-hidden="true">
            <span className="h-2 w-32 overflow-hidden rounded-full bg-border">
              <span
                className="block h-full rounded-full bg-primary transition-[width] duration-75"
                style={{ width: `${Math.round(level * 100)}%` }}
              />
            </span>
            <span className="text-xs text-content-muted">{level > 0.02 ? "收音中" : "聽不到聲音"}</span>
          </span>
        )}
        {autoSplit && (
          <span role="status" className="text-xs text-content-muted">
            {vad.starting ? "麥克風準備中…" : vad.speaking ? "聽到聲音了…" : "請說話，講完一句會自動送出"}
          </span>
        )}
        {busy && <span role="status" className="text-xs text-content-muted">辨識中…</span>}
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
            {row.state === "pending" && <span className="text-sm text-content-muted">等待中…</span>}
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
