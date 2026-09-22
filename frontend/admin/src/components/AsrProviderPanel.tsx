import { useEffect, useRef, useState } from "react";

import {
  clearAsrProvider,
  fetchAsrProvider,
  previewAsr,
  setAsrProvider,
  type SystemSetting,
} from "../api/settings";
import { preferredRecorderMimeType, rmsVolume } from "../utils/liveAudioUtils";
import { describeAsrEngine as describe } from "@shared/speech";
import Select from "./Select";

export default function AsrProviderPanel() {
  const [setting, setSetting] = useState<SystemSetting | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [elapsed, setElapsed] = useState<number | null>(null);
  const [level, setLevel] = useState(0);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const meterFrameRef = useRef<number | null>(null);

  useEffect(() => {
    let disposed = false;
    fetchAsrProvider()
      .then((value) => { if (!disposed) setSetting(value); })
      .catch(() => { if (!disposed) setError("無法載入語音辨識設定。"); })
      .finally(() => { if (!disposed) setLoading(false); });
    return () => { disposed = true; };
  }, []);

  async function apply(action: () => Promise<SystemSetting>, done: string) {
    setBusy(true);
    setError("");
    setStatus("");
    try {
      setSetting(await action());
      setStatus(done);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "設定失敗，請重試。");
    } finally {
      setBusy(false);
    }
  }

  async function sendForTranscription(clip: Blob, filename?: string) {
    setTranscribing(true);
    setError("");
    setElapsed(null);
    try {
      const preview = await previewAsr(clip, filename);
      setTranscript(preview.text);
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

  if (loading) {
    return <p role="status" className="text-sm text-content-muted">載入語音辨識設定中…</p>;
  }
  if (!setting) {
    return <p role="alert" className="text-sm text-danger">{error || "無法載入語音辨識設定。"}</p>;
  }

  const active = describe(setting.effective);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold">預設語音辨識引擎</h2>
        <p className="text-xs leading-5 text-content-muted">
          使用者沒有自己選的時候用這個。變更立即生效，不需重新啟動；所選引擎無法
          使用時，系統會自動改用其他已設定的引擎，不會讓辨識中斷。
          要讓某個帳號能自己換引擎，到「帳號」頁授權給他。
        </p>
        <Select
          value={setting.effective}
          disabled={busy}
          ariaLabel="語音辨識引擎"
          options={setting.options.map((id) => ({ value: id, label: describe(id).label }))}
          onChange={(next) => {
            if (next === setting.effective) return;
            void apply(() => setAsrProvider(next), `預設已改為 ${describe(next).label}。`);
          }}
        />
        {active.note && (
          <p className="text-xs leading-5 text-content-muted">{active.note}</p>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <span className="text-xs text-content-muted">
          {setting.overridden
            ? "預設值由後台指定，已覆寫部署設定。"
            : "預設值沿用部署設定（.env）。"}
        </span>
        {setting.overridden && (
          <button
            type="button"
            className="btn btn-ghost"
            disabled={busy}
            onClick={() => void apply(clearAsrProvider, "預設已改回部署設定。")}
          >
            改回部署設定
          </button>
        )}
      </div>

      <div className="flex flex-col gap-3 border-t border-border pt-6">
        <h2 className="text-sm font-semibold">試辨識</h2>
        <p className="text-xs leading-5 text-content-muted">
          錄一段話或上傳音檔，看目前的引擎辨識成什麼。走的是正式對話用的同一
          條路徑，所以結果就是實際會發生的行為。用同一個檔案切換引擎再試一次，
          就能直接比較兩家的差異。
        </p>
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

      {status && <p role="status" className="text-sm text-content-muted">{status}</p>}
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
    </div>
  );
}
