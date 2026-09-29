import { useEffect, useRef, useState } from "react";

import { previewAsr } from "../api/settings";
import { preferredRecorderMimeType, rmsVolume } from "../utils/liveAudioUtils";
import { SERVER_ASR_ENGINES, describeAsrEngine as describe } from "@shared/speech";
import Select from "./Select";

/**
 * 後台「語音」頁的 ASR 分頁：試辨識，用同一段音檔比較各家引擎。
 *
 * 以前這裡還有「全站預設引擎」，2026-09-24 拔掉：沒選過的人一律用部署設定的
 * ASR_PROVIDER，每個人要換就在聊天室或前台自己選，能選哪些由帳號頁授權。這裡
 * 選的引擎只影響這一次試辨識。
 */
export default function AsrProviderPanel() {
  const [engine, setEngine] = useState<string>(SERVER_ASR_ENGINES[0]);
  const [error, setError] = useState("");
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [answeredBy, setAnsweredBy] = useState("");
  const [elapsed, setElapsed] = useState<number | null>(null);
  const [level, setLevel] = useState(0);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const meterFrameRef = useRef<number | null>(null);

  async function sendForTranscription(clip: Blob, filename?: string) {
    setTranscribing(true);
    setError("");
    setElapsed(null);
    try {
      const preview = await previewAsr(clip, filename, engine);
      setTranscript(preview.text);
      setAnsweredBy(preview.provider);
      setElapsed(preview.elapsed_seconds ?? null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "辨識失敗，請重試。");
    } finally {
      setTranscribing(false);
    }
  }

  function stopTracks() {
    if (meterFrameRef.current !== null) {
      cancelAnimationFrame(meterFrameRef.current);
      meterFrameRef.current = null;
    }
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
    setTranscript("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const mimeType = preferredRecorderMimeType();
      // 明確指定位元率：opus 壓到 24 kbps 時辨識會崩壞（實測「今仔日天氣袂歹」
      // 變成「今拿日天氣袂買」），128 kbps 的結果與未壓縮的 WAV 完全一致。
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
        const clip = new Blob(chunks, { type: mimeType || "audio/webm" });
        if (!clip.size) {
          setError("沒有錄到聲音，請確認麥克風。");
          return;
        }
        void sendForTranscription(clip);
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

  useEffect(() => stopTracks, []);

  const selected = describe(engine);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3">
        <h2 className="text-sm font-semibold">試辨識</h2>
        <p className="text-xs leading-5 text-content-muted">
          選一個引擎，錄一段話或上傳音檔，看它辨識成什麼。走的是正式對話用的同一
          條路徑，所以結果就是實際會發生的行為。用同一個檔案換引擎再試一次，就能
          直接比較。這裡選的只影響這次試辨識；每個人用哪個引擎由他自己在聊天室或
          前台選，能選哪些到「帳號」頁授權，沒選過的人用部署設定。
        </p>
        <Select
          value={engine}
          disabled={recording || transcribing}
          ariaLabel="試辨識的引擎"
          options={SERVER_ASR_ENGINES.map((id) => ({ value: id, label: describe(id).label }))}
          onChange={setEngine}
        />
        {selected.note && (
          <p className="text-xs leading-5 text-content-muted">{selected.note}</p>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            className={recording ? "btn btn-danger" : "btn btn-secondary"}
            disabled={transcribing}
            onClick={() => (recording ? stopRecording() : void startRecording())}
          >
            {recording ? "停止並辨識" : "開始錄音"}
          </button>
          <label className={`btn btn-ghost ${recording || transcribing ? "pointer-events-none opacity-50" : "cursor-pointer"}`}>
            上傳音檔
            <input
              type="file"
              accept="audio/*"
              className="sr-only"
              disabled={recording || transcribing}
              onChange={(event) => {
                const input = event.target;
                const picked = input.files?.[0];
                if (picked) {
                  setTranscript("");
                  void sendForTranscription(picked, picked.name);
                }
                // 清 value 要等取完檔案：清掉會一併清空 files，先清就什麼都
                // 讀不到。清它是為了讓同一個檔案選第二次仍會觸發 change。
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
              <span className="text-xs text-content-muted">
                {level > 0.02 ? "收音中" : "聽不到聲音"}
              </span>
            </span>
          )}
          {transcribing && (
            <span role="status" className="text-sm text-content-muted">辨識中…</span>
          )}
        </div>
        {transcript && (
          <div className="flex flex-col gap-1">
            <p className="rounded-md border border-border bg-surface px-4 py-3 text-sm">
              {transcript}
            </p>
            {answeredBy && answeredBy !== engine && (
              // 指定的引擎沒回應時會由備援接手，不講清楚會以為是選的那家辨識的。
              <p className="text-xs text-content-muted">
                {describe(engine).label} 沒有回應，這次由 {describe(answeredBy).label} 辨識。
              </p>
            )}
            {elapsed !== null && (
              // 這是這一次實測到的耗時，不是對引擎的效能承諾：同一個引擎會隨
              // 音檔長度與 GPU 當下負載變動，拿它跨次比較要留意這點。
              <p className="text-xs text-content-muted">
                本次辨識耗時 {elapsed.toFixed(2)} 秒（不含上傳與轉檔）
              </p>
            )}
          </div>
        )}
      </div>

      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
    </div>
  );
}
