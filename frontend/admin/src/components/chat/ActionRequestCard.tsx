import { useState } from "react";
import { apiUrl, projectUrl } from "../../api/common";
import type { ActionRequest, ActionRisk } from "../../api";
import { useNavigation } from "../../context/NavigationContext";
import type { Tab } from "../app/navigation";

type Status = "pending" | "confirming" | "confirmed" | "cancelled" | "error";

const RISK_STYLES: Record<ActionRisk, string> = {
  low: "bg-accent-50 text-accent-700 border-accent-100",
  medium: "bg-amber-50 text-amber-700 border-amber-200",
  high: "bg-red-50 text-red-700 border-red-200",
};

function resolveNavTarget(request: ActionRequest): { tab: Tab; subView?: string } | null {
  if (request.nav_target?.tab) {
    return { tab: request.nav_target.tab as Tab, subView: request.nav_target.sub_view ?? undefined };
  }
  // Backwards-compat: "Tab:subView" in endpoint before nav_target existed.
  const [tab, subView] = (request.endpoint || "").split(":");
  if (!tab) return null;
  return { tab: tab as Tab, subView: subView || undefined };
}

export default function ActionRequestCard({
  request,
  onConfirmed,
  onCancelled,
}: {
  request: ActionRequest;
  onConfirmed?: (request: ActionRequest) => void;
  onCancelled?: (request: ActionRequest) => void;
}) {
  const [status, setStatus] = useState<Status>("pending");
  const [errorMsg, setErrorMsg] = useState("");
  const { navigateTo } = useNavigation();

  const riskClass = RISK_STYLES[request.risk] ?? RISK_STYLES.medium;
  const isNavigate = request.kind === "navigate";
  const isEmbed = request.kind === "embed";

  const navigate = () => {
    const target = resolveNavTarget(request);
    if (!target) {
      setStatus("error");
      setErrorMsg("導航目標未指定");
      return;
    }
    navigateTo(target.tab, target.subView);
    setStatus("confirmed");
    onConfirmed?.(request);
  };

  const confirm = async () => {
    setStatus("confirming");
    setErrorMsg("");
    try {
      const res = await fetch(apiUrl(request.endpoint), {
        method: request.method || "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request.params ?? {}),
      });
      if (!res.ok) {
        throw new Error(`${res.status} ${res.statusText}`);
      }
      setStatus("confirmed");
      onConfirmed?.(request);
    } catch (err) {
      setStatus("error");
      setErrorMsg(String(err));
    }
  };

  const cancel = () => {
    setStatus("cancelled");
    onCancelled?.(request);
  };

  const disabled = status !== "pending";
  const showActions = status === "pending" || status === "confirming" || status === "error";

  if (isEmbed) {
    return (
      <div className="mt-3 rounded-lg border border-border bg-surface-raised overflow-hidden text-sm">
        <div className="flex items-center gap-2 px-3 py-2 border-b border-border">
          <span className="material-symbols-outlined text-[16px] text-content-muted">hub</span>
          <span className="font-medium text-content">{request.label}</span>
          {request.reason && (
            <span className="text-xs text-content-subtle truncate">{request.reason}</span>
          )}
        </div>
        <iframe
          src={projectUrl(request.endpoint)}
          title={request.label}
          className="w-full border-0 bg-white dark:bg-slate-950/30"
          style={{ height: "520px" }}
        />
      </div>
    );
  }

  return (
    <div className="mt-3 rounded-lg border border-border bg-surface-raised p-3 text-sm">
      <div className="flex items-center gap-2 mb-2">
        <span className="material-symbols-outlined text-[16px] text-content-muted">bolt</span>
        <span className="font-medium text-content">{request.label}</span>
        <span
          className={`ml-auto rounded-sm border px-1.5 py-0.5 text-[10px] uppercase tracking-wider ${riskClass}`}
        >
          {request.risk}
        </span>
      </div>
      <p className="mb-3 text-content-muted leading-relaxed">{request.description}</p>
      {request.reason && (
        <p className="mb-3 italic text-content-subtle text-xs leading-relaxed">
          建議原因：{request.reason}
        </p>
      )}
      {status === "error" && <p className="mb-2 text-xs text-red-600">執行失敗：{errorMsg}</p>}
      {status === "confirmed" && (
        <p className="text-xs text-accent-600">✓ 已觸發。結果將稍後顯示。</p>
      )}
      {status === "cancelled" && <p className="text-xs text-content-subtle">已取消。</p>}
      {showActions && (
        <div className="flex gap-2">
          {isNavigate ? (
            <button type="button" onClick={navigate} className="btn btn-primary text-xs py-1 px-3">
              前往
            </button>
          ) : (
            <>
              <button
                type="button"
                onClick={confirm}
                disabled={status === "confirming"}
                className="btn btn-primary text-xs py-1 px-3"
              >
                {status === "confirming" ? "執行中…" : "確認"}
              </button>
              <button
                type="button"
                onClick={cancel}
                disabled={disabled}
                className="btn btn-ghost text-xs py-1 px-3"
              >
                取消
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
