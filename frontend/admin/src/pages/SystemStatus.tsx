import PageTabsShell from "../components/app/PageTabsShell";
import { useAdminSubView } from "../hooks/useAdminSubView";
import Health from "./Health";
import Monitoring from "./Monitoring";

type SystemView = "health" | "monitoring";

const TABS: { id: SystemView; label: string }[] = [
  { id: "health", label: "健康" },
  { id: "monitoring", label: "監控" },
];

const VIEW_IDS = TABS.map((item) => item.id);

export default function SystemStatus() {
  const [view, setView] = useAdminSubView<SystemView>(
    "SystemStatus",
    "health",
    VIEW_IDS,
  );

  // 只掛目前分頁：離開健康分頁就停掉 30 秒輪詢，沒進監控分頁就不載入 Grafana iframe。
  return (
    <PageTabsShell
      idPrefix="system"
      title="系統狀態"
      tabs={TABS}
      active={view}
      onSelect={setView}
    >
      {view === "health" ? <Health /> : <Monitoring />}
    </PageTabsShell>
  );
}
