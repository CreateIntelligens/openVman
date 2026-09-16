import { useEffect, useRef, useState, type FormEvent } from "react";

import { fetchTtsProviders, synthesizeSpeechPreview, type TtsProvider } from "../api/tts";
import Select from "../components/Select";

const SAMPLE_TEXT = "你好，歡迎使用 openVman。這是一段語音試聽，請確認聲音與語速是否合適。";

function defaultVoice(provider?: TtsProvider): string {
  if (provider?.voices.includes(provider.default_voice)) return provider.default_voice;
  return provider?.voices[0] || "";
}

export default function Tts() {
  const [providers, setProviders] = useState<TtsProvider[]>([]);
  const [provider, setProvider] = useState("");
  const [voice, setVoice] = useState("");
  const [text, setText] = useState(SAMPLE_TEXT);
  const [loading, setLoading] = useState(true);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [loadError, setLoadError] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [audioUrl, setAudioUrl] = useState("");
  const audioRef = useRef<HTMLAudioElement>(null);
  const requestRef = useRef<AbortController | null>(null);
  const urlRef = useRef("");
  const activeProvider = providers.find((item) => item.id === provider);
  const canSubmit = !loading && !loadError && Boolean(activeProvider && text.trim());

  useEffect(() => {
    let disposed = false;
    setLoading(true);
    setLoadError("");
    fetchTtsProviders().then((items) => {
      if (disposed) return;
      // 明確選定供應商，才能比較各個聲音；不把自動 fallback 當成一個聲音。
      const selectable = items.filter((item) => item.id !== "auto" && item.voices.length > 0);
      setProviders(selectable);
      setProvider(selectable[0]?.id || "");
      setVoice(defaultVoice(selectable[0]));
    }).catch(() => {
      if (!disposed) setLoadError("無法載入可用聲音，請重試。");
    }).finally(() => {
      if (!disposed) setLoading(false);
    });
    return () => { disposed = true; };
  }, [loadAttempt]);

  useEffect(() => {
    return () => {
      requestRef.current?.abort();
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    };
  }, []);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audioUrl || !audio) return;
    let disposed = false;
    void audio.play().catch(() => {
      if (!disposed) setStatus((previous) => `${previous} 請按下方播放鍵開始試聽。`);
    });
    return () => {
      disposed = true;
      audio.pause();
    };
  }, [audioUrl]);

  function clearAudio(): void {
    audioRef.current?.pause();
    if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    urlRef.current = "";
    setAudioUrl("");
  }

  function resetPlaybackState(): void {
    clearAudio();
    setStatus("");
    setError("");
  }

  function stop(): void {
    requestRef.current?.abort();
    requestRef.current = null;
    setBusy(false);
    clearAudio();
    setStatus("已停止試聽。");
  }

  async function submit(event: FormEvent): Promise<void> {
    event.preventDefault();
    if (!canSubmit || requestRef.current) return;
    resetPlaybackState();
    setBusy(true);
    const controller = new AbortController();
    requestRef.current = controller;
    try {
      const result = await synthesizeSpeechPreview(text.trim(), provider, voice, controller.signal);
      if (controller.signal.aborted) return;
      const url = URL.createObjectURL(result.audio);
      urlRef.current = url;
      setAudioUrl(url);
      const actualName = providers.find((item) => item.id === result.provider)?.name
        || result.provider || activeProvider?.name || "";
      setStatus(result.fallback
        ? `原選聲音未能提供，本次由 ${actualName} 備援產生。`
        : `語音已就緒 · ${actualName}`);
    } catch (reason) {
      if (!controller.signal.aborted) {
        setError(reason instanceof Error ? reason.message : "語音產生失敗，請重試。");
      }
    } finally {
      if (requestRef.current === controller) {
        requestRef.current = null;
        setBusy(false);
      }
    }
  }

  return (
    <div className="page-scroll">
      <header className="border-b border-border bg-surface-raised px-4 py-4 md:px-8">
        <h1 className="page-title">TTS 試聽</h1>
        <p className="page-subtitle">選擇聲音，輸入一段文字，直接聽聽效果。</p>
      </header>
      <form onSubmit={(event) => void submit(event)} className="flex flex-col gap-6 p-4 md:p-8">
        {loading && <p role="status" className="text-sm text-content-muted">載入可用聲音中…</p>}
        {loadError && <p role="alert" className="text-sm text-danger">{loadError}</p>}
        {!loading && !providers.length && !loadError && (
          <p role="status" className="text-sm text-content-muted">目前沒有可試聽的聲音，請聯絡管理員配置聲音授權。</p>
        )}
        {!loading && (loadError || !providers.length) && (
          <button
            type="button"
            className="btn btn-ghost self-start"
            onClick={() => setLoadAttempt((value) => value + 1)}
          >
            重新載入聲音
          </button>
        )}
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div className="min-w-0 space-y-2">
            <span className="text-sm font-medium">供應商</span>
            <Select
              ariaLabel="供應商"
              value={provider}
              disabled={loading || busy || !providers.length}
              placeholder="選擇供應商"
              options={providers.map((item) => ({ value: item.id, label: item.name }))}
              onChange={(id) => {
                resetPlaybackState();
                setProvider(id);
                setVoice(defaultVoice(providers.find((item) => item.id === id)));
              }}
            />
          </div>
          <div className="min-w-0 space-y-2">
            <span className="text-sm font-medium">聲音</span>
            <Select
              ariaLabel="聲音"
              value={voice}
              disabled={loading || busy || !activeProvider}
              placeholder="選擇聲音"
              options={(activeProvider?.voices || []).map((value) => ({ value, label: value }))}
              onChange={(value) => {
                resetPlaybackState();
                setVoice(value);
              }}
            />
          </div>
        </div>
        <div className="space-y-2">
          <label htmlFor="tts-preview-text" className="text-sm font-medium">試聽文字</label>
          <textarea
            id="tts-preview-text"
            className="input w-full resize-y"
            rows={5}
            maxLength={1000}
            value={text}
            disabled={busy}
            required
            aria-describedby="tts-preview-limit"
            onChange={(event) => {
              resetPlaybackState();
              setText(event.target.value);
            }}
          />
          <p id="tts-preview-limit" className="text-sm text-content-muted">{text.length} / 1000 字</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <button type="submit" className="btn btn-primary whitespace-nowrap" disabled={!canSubmit || busy}>
            {busy ? "語音產生中…" : "試聽"}
          </button>
          {(busy || audioUrl) && (
            <button type="button" className="btn btn-ghost whitespace-nowrap" onClick={stop}>
              停止試聽
            </button>
          )}
        </div>
        {error && <p role="alert" className="text-sm text-danger">{error}</p>}
        {status && <p role="status" className="text-sm text-content-muted">{status}</p>}
        {audioUrl && (
          <audio
            ref={audioRef}
            src={audioUrl}
            controls
            aria-label="試聽播放器"
            className="w-full"
            onError={() => setError("音訊無法播放，請換一個聲音或重新試聽。")}
          />
        )}
      </form>
    </div>
  );
}
