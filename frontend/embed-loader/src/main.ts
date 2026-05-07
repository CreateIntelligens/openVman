type VmanEventType = "ready" | "message" | "speaking" | "error" | "resize";
type VmanCommandType = "speak" | "interrupt" | "set_persona" | "handshake" | "host_ready";

type VmanEnvelope = {
  source: "vman";
  version: "v1";
  type: string;
  payload: Record<string, unknown>;
};

type VmanEventHandler = (payload: Record<string, unknown>, envelope: VmanEnvelope) => void;

const TAG_NAME = "vman-avatar";
const MESSAGE_SOURCE = "vman";
const MESSAGE_VERSION = "v1";
const DEFAULT_IFRAME_PATH = "/embed/avatar";
const EVENT_TYPES = new Set<VmanEventType>(["ready", "message", "speaking", "error", "resize"]);
const currentScript = document.currentScript as HTMLScriptElement | null;
const scriptOrigin = currentScript?.src ? new URL(currentScript.src, window.location.href).origin : window.location.origin;

function isEnvelope(value: unknown): value is VmanEnvelope {
  if (!value || typeof value !== "object") return false;
  const data = value as Partial<VmanEnvelope>;
  return data.source === MESSAGE_SOURCE
    && data.version === MESSAGE_VERSION
    && typeof data.type === "string"
    && typeof data.payload === "object"
    && data.payload !== null;
}

function envelope(type: VmanCommandType | string, payload: Record<string, unknown> = {}): VmanEnvelope {
  return {
    source: MESSAGE_SOURCE,
    version: MESSAGE_VERSION,
    type,
    payload,
  };
}

class VmanAvatarElement extends HTMLElement {
  static observedAttributes = ["api-key", "persona", "theme", "auto-resize"];

  private iframe: HTMLIFrameElement | null = null;
  private iframeOrigin: string | null = null;
  private ready = false;
  private commandQueue: VmanEnvelope[] = [];
  private subscribers = new Map<string, Set<VmanEventHandler>>();
  private handleMessageBound = (event: MessageEvent) => this.handleMessage(event);

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
  }

  connectedCallback(): void {
    window.addEventListener("message", this.handleMessageBound);
    this.render();
  }

  disconnectedCallback(): void {
    window.removeEventListener("message", this.handleMessageBound);
    this.subscribers.clear();
    this.commandQueue = [];
    this.iframe = null;
    this.iframeOrigin = null;
    this.ready = false;
  }

  attributeChangedCallback(name: string, oldValue: string | null, newValue: string | null): void {
    if (!this.isConnected || oldValue === newValue) return;
    if (name === "auto-resize") return;
    this.render();
  }

  speak(text: string): void {
    const trimmed = text.trim();
    if (!trimmed) return;
    this.send("speak", { text: trimmed });
  }

  interrupt(): void {
    this.send("interrupt");
  }

  setPersona(id: string): void {
    const trimmed = id.trim();
    if (!trimmed) return;
    this.send("set_persona", { id: trimmed });
  }

  send(type: VmanCommandType, payload: Record<string, unknown> = {}): void {
    const message = envelope(type, payload);
    if (!this.ready || !this.iframe?.contentWindow || !this.iframeOrigin) {
      this.commandQueue.push(message);
      return;
    }
    this.postToIframe(message);
  }

  on(type: VmanEventType, handler: VmanEventHandler): () => void {
    const handlers = this.subscribers.get(type) ?? new Set<VmanEventHandler>();
    handlers.add(handler);
    this.subscribers.set(type, handlers);
    return () => this.off(type, handler);
  }

  off(type: VmanEventType, handler: VmanEventHandler): void {
    this.subscribers.get(type)?.delete(handler);
  }

  private render(): void {
    const src = this.buildIframeSrc();
    this.iframeOrigin = new URL(src).origin;
    this.ready = false;
    this.commandQueue = [];

    if (!this.shadowRoot) return;
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          width: 100%;
          max-width: 28rem;
          height: 40rem;
          min-height: 24rem;
          background: transparent;
        }
        .frame {
          width: 100%;
          height: 100%;
          border: 0;
          display: block;
          background: transparent;
        }
      </style>
      <iframe
        class="frame"
        title="openVman avatar"
        sandbox="allow-scripts allow-same-origin"
        allow="autoplay; microphone"
      ></iframe>
    `;

    this.iframe = this.shadowRoot.querySelector("iframe");
    if (this.iframe) {
      this.iframe.onload = () => this.sendHostReady();
      this.iframe.src = src;
    }
  }

  private buildIframeSrc(): string {
    const base = new URL(DEFAULT_IFRAME_PATH, scriptOrigin);
    const apiKey = this.getAttribute("api-key") ?? "";
    const persona = this.getAttribute("persona") ?? "";
    const theme = this.getAttribute("theme") ?? "";
    if (apiKey) base.searchParams.set("api_key", apiKey);
    if (persona) base.searchParams.set("persona", persona);
    if (theme) base.searchParams.set("theme", theme);
    return base.toString();
  }

  private handleMessage(event: MessageEvent): void {
    if (!this.iframeOrigin || event.origin !== this.iframeOrigin) return;
    if (!isEnvelope(event.data)) return;
    const eventType = event.data.type as VmanEventType;
    if (!EVENT_TYPES.has(eventType)) return;

    if (eventType === "ready") {
      this.ready = true;
      this.flushCommandQueue();
    }

    if (eventType === "resize" && this.hasAttribute("auto-resize")) {
      this.applyAutoResize(event.data.payload);
    }

    this.dispatchEvent(new CustomEvent(`vman:${eventType}`, {
      bubbles: true,
      composed: true,
      detail: event.data.payload,
    }));
    this.subscribers.get(eventType)?.forEach((handler) => {
      handler(event.data.payload, event.data);
    });
  }

  private flushCommandQueue(): void {
    const queued = [...this.commandQueue];
    this.commandQueue = [];
    queued.forEach((message) => this.postToIframe(message));
  }

  private postToIframe(message: VmanEnvelope): void {
    if (!this.iframe?.contentWindow || !this.iframeOrigin) return;
    this.iframe.contentWindow.postMessage(message, this.iframeOrigin);
  }

  private sendHostReady(): void {
    this.postToIframe(envelope("host_ready", { origin: window.location.origin }));
  }

  private applyAutoResize(payload: Record<string, unknown>): void {
    const height = Number(payload.height);
    if (Number.isFinite(height) && height > 0) {
      this.style.height = `${Math.ceil(height)}px`;
    }
  }
}

if (!customElements.get(TAG_NAME)) {
  customElements.define(TAG_NAME, VmanAvatarElement);
}

declare global {
  interface HTMLElementTagNameMap {
    "vman-avatar": VmanAvatarElement;
  }

  interface Window {
    VmanAvatarElement: typeof VmanAvatarElement;
  }
}

window.VmanAvatarElement = VmanAvatarElement;
