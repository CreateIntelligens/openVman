import type {
  ClientEvent,
  ClientInitEvent,
  ServerErrorEvent,
  ServerEvent,
  ServerInitAckEvent,
} from "@contracts/generated/typescript/protocol-contracts";
import { validateClientEvent, validateServerEvent } from "../protocol/validators";
import { buildClientInitPayload, DEFAULT_VOICE_SOURCE, type VoiceSource } from "../hooks/liveSessionProtocol";

export type LiveWebSocketState = "connecting" | "connected" | "disconnected";

type LiveWebSocketConfig = {
  clientId: string;
  projectId: string;
  voiceSource?: VoiceSource;
  chatSessionId?: string;
};

type LiveWebSocketCallbacks = {
  onDisconnected?: () => void;
  onError?: (message: string) => void;
  onServerEvent?: (event: ServerEvent) => void;
  onSessionIdChange?: (sessionId: string) => void;
  onStateChange?: (state: LiveWebSocketState) => void;
};

const RECONNECT_DELAY_MS = 3000;

function buildWebSocketUrl(clientId: string): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/${encodeURIComponent(clientId)}`;
}

export class LiveWebSocketManager {
  private callbacks: LiveWebSocketCallbacks = {};
  private config: Required<Pick<LiveWebSocketConfig, "clientId" | "projectId" | "voiceSource">> & Pick<LiveWebSocketConfig, "chatSessionId">;
  private manualDisconnect = false;
  private reconnectGeneration = 0;
  private reconnectTimer: number | null = null;
  private socket: WebSocket | null = null;

  constructor(config: LiveWebSocketConfig, callbacks?: LiveWebSocketCallbacks) {
    this.config = {
      clientId: config.clientId,
      projectId: config.projectId,
      voiceSource: config.voiceSource ?? DEFAULT_VOICE_SOURCE,
      chatSessionId: config.chatSessionId,
    };
    if (callbacks) {
      this.callbacks = callbacks;
    }
  }

  setCallbacks(callbacks: LiveWebSocketCallbacks): void {
    this.callbacks = callbacks;
  }

  updateConfig(config: LiveWebSocketConfig): void {
    this.config = {
      clientId: config.clientId,
      projectId: config.projectId,
      voiceSource: config.voiceSource ?? DEFAULT_VOICE_SOURCE,
      chatSessionId: config.chatSessionId,
    };
  }

  connect(): void {
    this.clearReconnectTimer();
    const current = this.socket;
    if (current && (current.readyState === WebSocket.OPEN || current.readyState === WebSocket.CONNECTING)) {
      return;
    }

    this.manualDisconnect = false;
    this.callbacks.onStateChange?.("connecting");
    this.callbacks.onError?.("");

    const socket = new WebSocket(buildWebSocketUrl(this.config.clientId));
    const openGeneration = this.reconnectGeneration;
    this.socket = socket;

    socket.onopen = () => {
      const initEvent: ClientInitEvent = buildClientInitPayload({
        clientId: this.config.clientId,
        projectId: this.config.projectId,
        voiceSource: this.config.voiceSource,
        sessionId: this.config.chatSessionId,
      });
      this.sendEvent(initEvent);
    };

    socket.onmessage = (message) => {
      try {
        const payload = JSON.parse(message.data) as Record<string, unknown>;
        if (payload.event === "ping") {
          socket.send(JSON.stringify({ event: "pong", timestamp: payload.timestamp ?? Date.now() }));
          return;
        }

        const event = validateServerEvent(payload);
        this.handleServerEvent(event);
      } catch (reason) {
        console.error("Failed to handle live WebSocket event:", reason);
        this.callbacks.onError?.("收到無效的 Live 事件");
      }
    };

    socket.onerror = () => {
      this.callbacks.onError?.("Live WebSocket 發生錯誤");
    };

    socket.onclose = () => {
      if (this.socket === socket) {
        this.socket = null;
      }
      this.callbacks.onSessionIdChange?.("");
      this.callbacks.onStateChange?.("disconnected");
      this.callbacks.onDisconnected?.();

      if (!this.manualDisconnect && openGeneration !== this.reconnectGeneration) {
        this.connect();
        return;
      }
      this.scheduleReconnect();
    };
  }

  disconnect(): void {
    this.manualDisconnect = true;
    this.clearReconnectTimer();
    const socket = this.socket;
    this.socket = null;
    this.callbacks.onSessionIdChange?.("");
    this.callbacks.onStateChange?.("disconnected");
    if (socket && socket.readyState !== WebSocket.CLOSED) {
      socket.close();
    }
  }

  restart(): void {
    this.manualDisconnect = false;
    this.clearReconnectTimer();
    const socket = this.socket;
    if (!socket || socket.readyState === WebSocket.CLOSED) {
      this.connect();
      return;
    }
    this.reconnectGeneration += 1;
    socket.close();
  }

  dispose(): void {
    this.disconnect();
  }

  sendEvent(payload: ClientEvent): boolean {
    const socket = this.socket;
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      return false;
    }
    const validated = validateClientEvent(payload);
    socket.send(JSON.stringify(validated));
    return true;
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private handleServerEvent(event: ServerEvent): void {
    if (event.event === "server_init_ack") {
      const ack = event as ServerInitAckEvent;
      if (ack.status === "ok") {
        this.callbacks.onSessionIdChange?.(ack.session_id);
        this.callbacks.onStateChange?.("connected");
        this.callbacks.onError?.("");
      } else {
        this.callbacks.onError?.(ack.message || "Live 連線初始化失敗");
        this.callbacks.onStateChange?.("disconnected");
      }
    } else if (event.event === "server_error") {
      this.callbacks.onError?.((event as ServerErrorEvent).message);
    }

    this.callbacks.onServerEvent?.(event);
  }

  private scheduleReconnect(): void {
    this.clearReconnectTimer();
    if (this.manualDisconnect) {
      return;
    }

    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      if (!this.manualDisconnect) {
        this.connect();
      }
    }, RECONNECT_DELAY_MS);
  }
}

