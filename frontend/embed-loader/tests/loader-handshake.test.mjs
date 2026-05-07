import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import test from "node:test";
import vm from "node:vm";

function createRuntime() {
  const posts = [];
  const listeners = new Map();
  const registry = new Map();

  class FakeIframe {
    constructor() {
      this.contentWindow = {
        postMessage: (message, targetOrigin) => {
          posts.push({ message, targetOrigin });
        },
      };
      this.onload = null;
      this._src = "";
    }

    set src(value) {
      this._src = value;
    }

    get src() {
      return this._src;
    }
  }

  class FakeShadowRoot {
    constructor() {
      this.iframe = null;
    }

    set innerHTML(_value) {
      this.iframe = new FakeIframe();
    }

    querySelector(selector) {
      return selector === "iframe" ? this.iframe : null;
    }
  }

  class FakeHTMLElement {
    constructor() {
      this.attributes = new Map();
      this.dispatchedEvents = [];
      this.isConnected = false;
      this.shadowRoot = null;
      this.style = {};
    }

    attachShadow() {
      this.shadowRoot = new FakeShadowRoot();
      return this.shadowRoot;
    }

    dispatchEvent(event) {
      this.dispatchedEvents.push(event);
      return true;
    }

    getAttribute(name) {
      return this.attributes.get(name) ?? null;
    }

    hasAttribute(name) {
      return this.attributes.has(name);
    }

    setAttribute(name, value) {
      this.attributes.set(name, String(value));
    }
  }

  class FakeCustomEvent {
    constructor(type, init) {
      this.type = type;
      this.detail = init?.detail;
      this.bubbles = Boolean(init?.bubbles);
      this.composed = Boolean(init?.composed);
    }
  }

  const window = {
    location: new URL("https://tenant.example/page"),
    addEventListener: (type, handler) => {
      const handlers = listeners.get(type) ?? [];
      handlers.push(handler);
      listeners.set(type, handlers);
    },
    removeEventListener: (type, handler) => {
      listeners.set(
        type,
        (listeners.get(type) ?? []).filter((candidate) => candidate !== handler),
      );
    },
  };

  const context = {
    console,
    CustomEvent: FakeCustomEvent,
    HTMLElement: FakeHTMLElement,
    URL,
    customElements: {
      define: (name, elementClass) => registry.set(name, elementClass),
      get: (name) => registry.get(name),
    },
    document: {
      currentScript: { src: "https://openvman.example/vman-embed.js" },
    },
    window,
  };
  context.globalThis = context;

  return {
    context,
    dispatchMessage: (event) => {
      for (const handler of listeners.get("message") ?? []) {
        handler(event);
      }
    },
    posts,
  };
}

function loadEmbedLoader() {
  const runtime = createRuntime();
  const source = readFileSync(resolve("dist/vman-embed.js"), "utf-8");
  vm.runInNewContext(source, runtime.context);
  return runtime;
}

function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

test("loader sends host_ready on iframe load before flushing queued commands", () => {
  const runtime = loadEmbedLoader();
  const ElementClass = runtime.context.window.VmanAvatarElement;
  const element = new ElementClass();
  element.setAttribute("api-key", "secret");

  element.isConnected = true;
  element.connectedCallback();
  element.speak("hello");

  const iframe = element.shadowRoot.querySelector("iframe");
  assert.equal(typeof iframe.onload, "function");

  iframe.onload();

  assert.deepEqual(plain(runtime.posts), [
    {
      message: {
        source: "vman",
        version: "v1",
        type: "host_ready",
        payload: { origin: "https://tenant.example" },
      },
      targetOrigin: "https://openvman.example",
    },
  ]);

  runtime.dispatchMessage({
    origin: "https://openvman.example",
    data: {
      source: "vman",
      version: "v1",
      type: "ready",
      payload: { capabilities: ["speak"] },
    },
  });

  assert.deepEqual(
    plain(runtime.posts).map((post) => post.message.type),
    ["host_ready", "speak"],
  );
});
