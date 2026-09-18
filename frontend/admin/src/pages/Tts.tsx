import { useState } from "react";

import AsrProviderPanel from "../components/AsrProviderPanel";
import TtsPreviewPanel from "../components/TtsPreviewPanel";

type Tab = "tts" | "asr";

const TABS: { id: Tab; label: string }[] = [
  { id: "tts", label: "TTS 試聽" },
  { id: "asr", label: "語音辨識" },
];

export default function Voice() {
  const [tab, setTab] = useState<Tab>("tts");

  return (
    <div className="page-scroll p-6 lg:p-8">
      <header className="mb-5 flex flex-wrap items-center gap-x-6 gap-y-1 border-b border-border">
        <h1 className="page-title whitespace-nowrap">語音</h1>
        <nav
          className="flex"
          aria-label="語音功能"
          role="tablist"
          onKeyDown={(event) => {
            if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
            event.preventDefault();
            const tabs = event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]');
            const current = TABS.findIndex((item) => item.id === tab);
            const next = event.key === "Home"
              ? 0
              : event.key === "End"
                ? TABS.length - 1
                : (current + (event.key === "ArrowRight" ? 1 : TABS.length - 1)) % TABS.length;
            tabs[next]?.focus();
            tabs[next]?.click();
          }}
        >
          {TABS.map((item) => (
            <button
              key={item.id}
              className={`-mb-px whitespace-nowrap border-b-2 px-3 py-3 text-left ${
                tab === item.id
                  ? "border-primary text-content"
                  : "border-transparent text-content-muted hover:text-content"
              }`}
              type="button"
              role="tab"
              id={`voice-${item.id}-tab`}
              aria-controls="voice-panel"
              aria-selected={tab === item.id}
              tabIndex={tab === item.id ? 0 : -1}
              onClick={() => setTab(item.id)}
            >
              <span className="block text-sm font-semibold">{item.label}</span>
            </button>
          ))}
        </nav>
      </header>

      <div id="voice-panel" role="tabpanel" aria-labelledby={`voice-${tab}-tab`}>
        {tab === "tts" ? <TtsPreviewPanel /> : <AsrProviderPanel />}
      </div>
    </div>
  );
}
