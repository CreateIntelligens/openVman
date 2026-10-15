import { Suspense, lazy } from "react";

import PageTabsShell from "../components/app/PageTabsShell";
import {
  accessSectionOf,
  hasAccess,
  visibleAccessSections,
  type AccessSection,
  type TabAccess,
} from "../components/app/navigation";
import { useAuth } from "../context/AuthContext";
import { useNavigation } from "../context/NavigationContext";

// 各分頁各自 lazy，權限圖譜的 d3-force 不會拖慢專案分頁。
const sectionPages = {
  projects: lazy(() => import("./Projects")),
  accounts: lazy(() => import("./Accounts")),
  "api-keys": lazy(() => import("./ApiKeys")),
  graph: lazy(() => import("./AccessGraph")),
  "embed-keys": lazy(() => import("./EmbedKeys")),
} satisfies Record<AccessSection, unknown>;

export default function Access() {
  const { account } = useAuth();
  const { currentSubView, navigateTo } = useNavigation();
  const access: TabAccess = account?.role ?? "user";
  const tabs = visibleAccessSections(access);
  const section = accessSectionOf(currentSubView);
  const current = tabs.find((item) => item.id === section);
  const SectionPage = sectionPages[section];

  return (
    <PageTabsShell
      idPrefix="access"
      title="專案與權限"
      tabs={tabs}
      active={section}
      onSelect={(next) => {
        if (next !== section) navigateTo("Access", next);
      }}
    >
      {/* App 對直連沒權限的分頁會先擋成權限不足；這裡再保險一次不掛內容。 */}
      {current && hasAccess(access, current.access) && (
        <Suspense
          fallback={
            <div className="flex h-full items-center justify-center text-sm text-content-muted" role="status">
              載入中…
            </div>
          }
        >
          <SectionPage />
        </Suspense>
      )}
    </PageTabsShell>
  );
}
