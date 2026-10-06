import { useEffect, useRef, useState } from "react";

import { STREAM_ASR_ENGINES, StreamRecognizer, describeAsrEngine as describe } from "@shared/speech";
import Select from "../Select";

interface Final {
  id: number;
  text: string;
  /** 從按下開始到這句定稿的秒數；連續講好幾句時可以看出每句大概多久出來。 */
  at: number;
}

interface StreamTesterProps {
  projectId: string;
  routes: string[];
}

/** 後台試聽專用：engine 參數只有管理員能用，不必先改自己的辨識偏好。 */
export function streamTestUrl(engine: string, projectId: string, routes: string[]): string {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const params = new URLSearchParams({ engine });
  if (projectId) params.set("project_id", projectId);
  if (routes.length) params.set("language_routes", routes.join(","));
  return `${protocol}://${window.location.host}/api/v1/asr/stream?${params}`;
}

/**
 * 串流試聽：走正式對話用的 /api/v1/asr/stream（nginx → Backend → 引擎），邊講邊出字。
 * 多語分流時 R2T2 收到的是 zhen：.35 會自己分中英西，.37 當中文解碼。
 */
export default function StreamTester({ projectId, routes }: StreamTesterProps) {
  const [engine, setEngine] = useState<string>(STREAM_ASR_ENGINES[1]);
  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState("");
  const [finals, setFinals] = useState<Final[]>([]);
  const [error, setError] = useState("");
  const recognizerRef = useRef<StreamRecognizer | null>(null);
  const startedAt = useRef(0);
  const nextId = useRef(1);
  const urlRef = useRef("");
  urlRef.current = streamTestUrl(engine, projectId, routes);

  useEffect(() => {
    const recognizer = new StreamRecognizer({
      url: () => urlRef.current,
      onInterim: (text) => setInterim(text),
      onResult: (text) => {
        setInterim("");
        setFinals((current) => [
          { id: nextId.current++, text, at: (performance.now() - startedAt.current) / 1000 },
          ...current,
        ].slice(0, 20));
      },
      onError: () => {
        setError("串流連不上：引擎沒設定、上游失敗，或這個帳號不是管理員。");
        setListening(false);
      },
      onListeningChange: (value) => setListening(value),
    });
    recognizerRef.current = recognizer;
    return () => recognizer.dispose();
  }, []);

  async function start() {
    setError("");
    setInterim("");
    setFinals([]);
    startedAt.current = performance.now();
    await recognizerRef.current?.start();
  }

  function stop() {
    recognizerRef.current?.stop();
  }

  const selected = describe(engine);

  return (
    <section className="flex flex-col gap-4" aria-labelledby="asr-stream-title">
      <div className="flex flex-col gap-1">
        <h2 id="asr-stream-title" className="text-sm font-semibold">串流試聽</h2>
        <p className="text-xs leading-5 text-content-muted">
          邊講邊出字，走正式對話的同一條串流路徑，可以連續講好幾句。套用上面勾的語言分流與專案詞表。
          只有一種語言時 R2T2 用那個語言解碼；多種語言時交給它自己判斷：.35 分得出中英西，.37 一律當中文。
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Select
          value={engine}
          disabled={listening}
          ariaLabel="串流試聽的引擎"
          options={STREAM_ASR_ENGINES.map((id) => ({ value: id, label: describe(id).label }))}
          onChange={setEngine}
        />
        <button
          type="button"
          className={listening ? "btn btn-danger" : "btn btn-primary"}
          onClick={() => (listening ? stop() : void start())}
        >
          {listening ? "停止" : "開始收音"}
        </button>
      </div>
      {selected.note && <p className="text-xs leading-5 text-content-muted">{selected.note}</p>}

      {(listening || interim || finals.length > 0) && (
        <div className="card flex flex-col gap-2 p-4" aria-live="polite">
          <p className="min-h-[1.5rem] text-sm text-content-muted">
            {interim || (listening ? "請說話…" : "")}
          </p>
          <ol className="flex flex-col divide-y divide-border">
            {finals.map((final) => (
              <li key={final.id} className="flex flex-wrap items-baseline justify-between gap-2 py-2">
                <span className="text-sm">{final.text}</span>
                <span className="text-xs text-content-muted">開始後 {final.at.toFixed(1)} 秒</span>
              </li>
            ))}
          </ol>
        </div>
      )}
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
    </section>
  );
}
