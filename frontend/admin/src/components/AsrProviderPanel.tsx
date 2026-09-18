import { useEffect, useRef, useState } from "react";

import {
  clearAsrProvider,
  fetchAsrProvider,
  previewAsr,
  setAsrProvider,
  type SystemSetting,
} from "../api/settings";
import { preferredRecorderMimeType } from "../utils/liveAudioUtils";
import Select from "./Select";

// 選單上只有代號的話，使用者無從判斷該選哪個。寫辨識行為的差異，不寫
// 延遲秒數——那隨文字長度與 GPU 負載變動，標在介面上等於給一個做不到的承諾。
const ENGINE_NOTES: Record<string, { label: string; note: string }> = {
  sensevoice: {
    label: "SenseVoice-Small",
    note: "聽得懂臺語並以臺語漢字輸出，臺語場景建議用這個。",
  },
  breeze: {
    label: "Breeze-ASR-26",
    note: "臺語會轉寫成華語：語意保留、用字不保留。",
  },
  openai: {
    label: "OpenAI Whisper",
    note: "需要 API 金鑰，語音會送出到外部服務。",
  },
};

function describe(id: string): { label: string; note: string } {
  return ENGINE_NOTES[id] ?? { label: id, note: "" };
}

export default function AsrProviderPanel() {
  const [setting, setSetting] = useState<SystemSetting | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [transcript, setTranscript] = useState("");
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

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

  function stopTracks() {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
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
        setTranscribing(true);
        previewAsr(clip)
          .then((result) => setTranscript(result.text))
          .catch((reason) => setError(
            reason instanceof Error ? reason.message : "辨識失敗，請重試。",
          ))
          .finally(() => setTranscribing(false));
      };
      recorderRef.current = recorder;
      recorder.start();
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
        <h2 className="text-sm font-semibold">語音辨識引擎</h2>
        <p className="text-xs leading-5 text-content-muted">
          全站共用，變更立即生效，不需重新啟動。所選引擎無法使用時，系統會自動改用
          其他已設定的引擎，不會讓辨識中斷。
        </p>
        <Select
          value={setting.effective}
          disabled={busy}
          ariaLabel="語音辨識引擎"
          options={setting.options.map((id) => ({ value: id, label: describe(id).label }))}
          onChange={(next) => {
            if (next === setting.effective) return;
            void apply(() => setAsrProvider(next), `已改用 ${describe(next).label}。`);
          }}
        />
        {active.note && (
          <p className="text-xs leading-5 text-content-muted">{active.note}</p>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <span className="text-xs text-content-muted">
          {setting.overridden
            ? "目前由後台指定，已覆寫部署設定。"
            : "目前沿用部署設定（.env）。"}
        </span>
        {setting.overridden && (
          <button
            type="button"
            className="btn btn-ghost"
            disabled={busy}
            onClick={() => void apply(clearAsrProvider, "已改回部署設定。")}
          >
            改回部署設定
          </button>
        )}
      </div>

      <div className="flex flex-col gap-3 border-t border-border pt-6">
        <h2 className="text-sm font-semibold">試辨識</h2>
        <p className="text-xs leading-5 text-content-muted">
          錄一段話，看目前的引擎辨識成什麼。走的是正式對話用的同一條路徑，
          所以結果就是實際會發生的行為。
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
          {transcribing && (
            <span role="status" className="text-sm text-content-muted">辨識中…</span>
          )}
        </div>
        {transcript && (
          <p className="rounded-md border border-border bg-surface px-4 py-3 text-sm">
            {transcript}
          </p>
        )}
      </div>

      {status && <p role="status" className="text-sm text-content-muted">{status}</p>}
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
    </div>
  );
}
