import AsrProviderPanel from "../components/AsrProviderPanel";
import TtsPreviewPanel from "../components/TtsPreviewPanel";
import PageTabsShell from "../components/app/PageTabsShell";
import { useAdminSubView } from "../hooks/useAdminSubView";

type Tab = "tts" | "asr";

const TABS: { id: Tab; label: string }[] = [
  { id: "tts", label: "TTS 試聽" },
  { id: "asr", label: "語音辨識" },
];

const TAB_IDS = TABS.map((entry) => entry.id);

export default function Voice() {
  const [tab, setTab] = useAdminSubView<Tab>("Voice", "tts", TAB_IDS);

  return (
    <PageTabsShell idPrefix="voice" title="語音" tabs={TABS} active={tab} onSelect={setTab}>
      <div className="page-scroll p-4 sm:p-6 lg:p-8">
        {tab === "tts" ? <TtsPreviewPanel /> : <AsrProviderPanel />}
      </div>
    </PageTabsShell>
  );
}
