import { Component, type ReactNode } from "react";

import {
  isStaleChunkError,
  isStaleChunkReloadPending,
  reloadOnceForStaleChunk,
} from "@shared/staleChunkReload";

interface ErrorBoundaryProps {
  children: ReactNode;
  /** screen 佔滿視窗（整個 App 掛掉時沒有外框）；page 只佔頁面區，保留外框。 */
  variant: "screen" | "page";
  /** 換值就清掉錯誤，使用者才能從外框切到別頁。 */
  resetKey?: string;
}

interface ErrorBoundaryState {
  hasError: boolean;
  reloading: boolean;
}

export default class ErrorBoundary extends Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  state: ErrorBoundaryState = { hasError: false, reloading: false };

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true, reloading: isStaleChunkReloadPending() };
  }

  // React 自己會把錯誤印到 console；這裡不再記一次，也不顯示訊息內容，錯誤可能夾帶
  // API 回應或使用者資料。
  componentDidCatch(error: unknown) {
    if (isStaleChunkError(error) && reloadOnceForStaleChunk()) {
      this.setState({ reloading: true });
    }
  }

  componentDidUpdate(previous: ErrorBoundaryProps) {
    if (this.state.hasError && previous.resetKey !== this.props.resetKey) {
      this.setState({ hasError: false, reloading: false });
    }
  }

  render() {
    if (!this.state.hasError) return this.props.children;

    const size = this.props.variant === "screen" ? "h-dvh bg-surface" : "h-full";
    return (
      <div className={`flex ${size} items-center justify-center p-6 text-content`}>
        <div className="space-y-4 text-center">
          <p role="alert">
            {this.state.reloading
              ? "正在重新載入最新版本…"
              : "畫面無法顯示，可能是系統剛更新或連線不穩定。請重新載入，若仍無法使用請聯絡管理員。"}
          </p>
          {/* 重載中也留著按鈕：有未儲存變更時瀏覽器會詢問，使用者可能選擇留下。 */}
          <button
            className="btn btn-primary"
            type="button"
            onClick={() => window.location.reload()}
          >
            重新載入
          </button>
        </div>
      </div>
    );
  }
}
