import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const testDir = dirname(fileURLToPath(import.meta.url));
const sourceRoot = resolve(testDir, "..");

function read(relativePath) {
  return readFileSync(resolve(sourceRoot, relativePath), "utf8");
}

function transpileModule(source) {
  return ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ES2022,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
}

test("apiFetch keeps the full-page forbidden except for asset, TTS and ASR 403s", async () => {
  const source = read("api/http.ts");
  const compiled = transpileModule(source);
  const moduleUrl = `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`;
  const { apiFetch, setForbiddenHandler } = await import(moduleUrl);

  let forbiddenCalls = 0;
  const originalFetch = globalThis.fetch;

  try {
    setForbiddenHandler(() => {
      forbiddenCalls += 1;
    });

    // 1. Account-level endpoints trigger global forbidden on 403
    globalThis.fetch = async () => new Response(null, { status: 403 });
    await apiFetch("/api/v1/auth/me");
    assert.equal(forbiddenCalls, 1, "GET /api/v1/auth/me 403 must trigger forbiddenHandler");

    await apiFetch("/api/v1/me");
    assert.equal(forbiddenCalls, 2, "GET /api/v1/me 403 must trigger forbiddenHandler");

    // 2. TTS and ASR endpoints must NOT trigger global forbidden on 403
    await apiFetch("/api/v1/tts/stream");
    assert.equal(forbiddenCalls, 2, "/api/v1/tts/stream 403 must NOT trigger forbiddenHandler");

    await apiFetch("/v1/audio/speech");
    assert.equal(forbiddenCalls, 2, "/v1/audio/speech 403 must NOT trigger forbiddenHandler");

    await apiFetch("/api/v1/asr/transcribe");
    assert.equal(forbiddenCalls, 2, "/api/v1/asr/transcribe 403 must NOT trigger forbiddenHandler");

    // 3. Static assets must NOT trigger global forbidden on 403
    await apiFetch("/static/characters/c1/model.vrm");
    assert.equal(forbiddenCalls, 2, "/static/characters 403 must NOT trigger forbiddenHandler");

    // 4. 其他 API 的 403 照舊換成整頁「權限不足」。
    await apiFetch("/api/v1/chat/stream");
    assert.equal(forbiddenCalls, 3, "/api/v1/chat/stream 403 must still trigger forbiddenHandler");

    await apiFetch("/api/v1/projects/proj-1/resources?x=1");
    assert.equal(forbiddenCalls, 4, "/projects resources 403 must still trigger forbiddenHandler");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("useTtsStreamer falls back to project default voice and displays notice on 403", async () => {
  const sharedSource = readFileSync(
    resolve(testDir, "../../../shared/speech/tts/pcm-stream.ts"),
    "utf8",
  );
  const sharedCompiled = transpileModule(sharedSource);
  const sharedUrl = `data:text/javascript;base64,${Buffer.from(sharedCompiled).toString("base64")}`;

  const source = read("composables/useTtsStreamer.ts");
  const compiled = transpileModule(source)
    .replace(
      /import\s*\{\s*apiFetch\s*\}\s*from\s*['"][^'"]+['"];?/,
      "const apiFetch = (url, init) => fetch(url, { ...init, credentials: 'include' });",
    )
    .replace(
      /from\s*['"]@shared\/speech['"];?/,
      `from "${sharedUrl}";`,
    );

  const moduleUrl = `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`;
  const { useTtsStreamer } = await import(moduleUrl);

  const fallbackEvents = [];
  const requestedUrls = [];
  const requestedBodies = [];

  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    requestedUrls.push(String(input));
    const body = JSON.parse(init?.body ?? "{}");
    requestedBodies.push(body);

    // Initial voice is out-of-scope and rejected by backend with 403
    if (body.character === "out-of-scope-voice" || body.voice === "out-of-scope-voice") {
      return new Response(JSON.stringify({ detail: "Voice out of scope" }), {
        status: 403,
        statusText: "Forbidden",
        headers: { "Content-Type": "application/json" },
      });
    }

    // Fallback voice succeeds with 200 WAV
    const pcm = new Int16Array([100, 200, 300, 400]);
    const bytes = new Uint8Array(44 + pcm.byteLength);
    bytes.set([...Buffer.from("RIFF")], 0);
    bytes.set([...Buffer.from("WAVE")], 8);
    bytes.set([...Buffer.from("data")], 36);
    bytes.set(new Uint8Array(pcm.buffer), 44);

    return new Response(bytes, {
      status: 200,
      headers: { "Content-Type": "audio/wav" },
    });
  };

  try {
    let pcmChunkCount = 0;
    const streamer = useTtsStreamer({
      getProjectDefaultVoice: () => "project-default-voice",
      ttsProviders: () => [
        {
          id: "indextts",
          name: "IndexTTS",
          default_voice: "project-default-voice",
          voices: ["project-default-voice", "out-of-scope-voice"],
          voice_items: [
            { id: "project-default-voice", in_project_scope: true },
            { id: "out-of-scope-voice", in_project_scope: false },
          ],
        },
      ],
      onFallback: (fb) => fallbackEvents.push(fb),
      onPcmChunk: () => {
        pcmChunkCount += 1;
      },
    });

    await streamer.speak("測試語音回覆", {
      provider: "indextts",
      voice: "out-of-scope-voice",
      character: "out-of-scope-voice",
    });

    // Verify 403 triggered fallback notification
    assert.equal(fallbackEvents.length, 1);
    assert.equal(fallbackEvents[0].reason, "project_scope_forbidden");
    assert.equal(
      fallbackEvents[0].message,
      "這個聲音在本專案不可用，已改用 project-default-voice",
    );

    // Verify retry occurred with project default voice
    assert.equal(requestedUrls.length, 2);
    assert.equal(requestedBodies[0].character, "out-of-scope-voice");
    assert.equal(requestedBodies[1].character, "project-default-voice");
    assert.ok(pcmChunkCount > 0, "audio chunks were received after fallback");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("useTtsStreamer terminates without infinite loop if fallback voice also returns 403", async () => {
  const sharedSource = readFileSync(
    resolve(testDir, "../../../shared/speech/tts/pcm-stream.ts"),
    "utf8",
  );
  const sharedCompiled = transpileModule(sharedSource);
  const sharedUrl = `data:text/javascript;base64,${Buffer.from(sharedCompiled).toString("base64")}`;

  const source = read("composables/useTtsStreamer.ts");
  const compiled = transpileModule(source)
    .replace(
      /import\s*\{\s*apiFetch\s*\}\s*from\s*['"][^'"]+['"];?/,
      "const apiFetch = (url, init) => fetch(url, { ...init, credentials: 'include' });",
    )
    .replace(
      /from\s*['"]@shared\/speech['"];?/,
      `from "${sharedUrl}";`,
    );

  const moduleUrl = `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`;
  const { useTtsStreamer } = await import(moduleUrl);

  const originalFetch = globalThis.fetch;
  let attempts = 0;
  globalThis.fetch = async () => {
    attempts += 1;
    return new Response(JSON.stringify({ detail: "Forbidden" }), {
      status: 403,
      statusText: "Forbidden",
      headers: { "Content-Type": "application/json" },
    });
  };

  try {
    let capturedError = null;
    const streamer = useTtsStreamer({
      getProjectDefaultVoice: () => "fallback-voice",
      ttsProviders: () => [
        {
          id: "indextts",
          name: "IndexTTS",
          default_voice: "fallback-voice",
          voices: ["fallback-voice"],
        },
      ],
      onError: (err) => {
        capturedError = err;
      },
    });

    await streamer.speak("測試語音", { voice: "initial-voice" });
    assert.equal(attempts, 2, "must attempt original plus exactly 1 retry");
    assert.ok(capturedError, "must surface error when fallback fails");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("CustomSelect renders out-of-scope items with theme danger token and note", () => {
  const customSelectSource = read("components/controls/CustomSelect.vue");

  // SelectOption interface has in_project_scope
  assert.match(customSelectSource, /in_project_scope\?:\s*boolean/);

  // Template marks out-of-scope option and includes specified note
  assert.match(customSelectSource, /'custom-select__option--out-of-scope':\s*option\.in_project_scope === false/);
  assert.match(customSelectSource, /class="custom-select__option-scope-note"/);
  assert.match(customSelectSource, /不在專案範圍內，一般使用者無法使用/);

  // Value shows out-of-scope class and note when selected
  assert.match(customSelectSource, /'custom-select__value--out-of-scope':\s*selected\?\.in_project_scope === false/);
  assert.match(customSelectSource, /class="custom-select__value-scope-note"/);

  // Styling uses theme danger token
  assert.match(customSelectSource, /\.custom-select__option--out-of-scope\s*\{[\s\S]*?color:\s*rgb\(var\(--ov-color-danger\)\);/);
  assert.match(customSelectSource, /\.custom-select__value--out-of-scope\s*\{[\s\S]*?color:\s*rgb\(var\(--ov-color-danger\)\);/);
  assert.match(customSelectSource, /\.custom-select__option-scope-note\s*\{[\s\S]*?color:\s*rgb\(var\(--ov-color-danger\)\);/);

  // No hardcoded colors or px in out-of-scope styles
  assert.doesNotMatch(customSelectSource, /#ff0000|#f00|red;|#[0-9a-fA-F]{6}/);
});

test("SettingsModal maps in_project_scope across Voice, ASR, Character, and Background menus via data mappers", async () => {
  const optionsSource = read("utils/settingsOptions.ts");
  const compiled = transpileModule(optionsSource).replace(
    /import\s*\{\s*ASR_ENGINE_LABELS\s*\}\s*from\s*['"]@shared\/speech['"];?/,
    "const ASR_ENGINE_LABELS = { 'gemini-live': 'Gemini Live', 'breeze': 'Breeze ASR' };",
  );
  const moduleUrl = `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`;
  const {
    buildCharacterOptions,
    buildTtsProviderOptions,
    buildAsrProviderOptions,
    buildTtsVoiceOptions,
    buildBackgroundOptions,
  } = await import(moduleUrl);

  // 1. Voice: provider 及 voice_items 各自繼承或覆寫 in_project_scope
  const voiceOptions = buildTtsVoiceOptions({
    id: "indextts",
    name: "IndexTTS",
    voices: ["voice-in", "voice-out"],
    voice_items: [
      { id: "voice-in", in_project_scope: true },
      { id: "voice-out", in_project_scope: false },
    ],
    in_project_scope: true,
  });
  assert.equal(voiceOptions.length, 2);
  assert.equal(voiceOptions.find((v) => v.value === "voice-in")?.in_project_scope, true);
  assert.equal(voiceOptions.find((v) => v.value === "voice-out")?.in_project_scope, false);

  // 2. ASR: 保留各引擎的 in_project_scope
  const asrOptions = buildAsrProviderOptions([
    { id: "gemini-live", label: "Gemini Live", in_project_scope: true },
    { id: "breeze", label: "Breeze ASR", in_project_scope: false },
  ]);
  assert.equal(asrOptions.find((a) => a.value === "gemini-live")?.in_project_scope, true);
  assert.equal(asrOptions.find((a) => a.value === "breeze")?.in_project_scope, false);

  // 3. Character: 2D 與 VRM 角色保留 in_project_scope
  const charOptions = buildCharacterOptions(
    [{ id: "char-1", name: "角色1", in_project_scope: false }],
    [{ id: "vrm-1", label: "VRM1", in_project_scope: true }],
  );
  assert.equal(charOptions.find((c) => c.value === "matesx:char-1")?.in_project_scope, false);
  assert.equal(charOptions.find((c) => c.value === "vrm:vrm-1")?.in_project_scope, true);

  // 4. Background: 內建與上傳背景正確保留 in_project_scope
  const bgOptions = buildBackgroundOptions(
    [{ id: "default", label: "預設背景", in_project_scope: true }],
    [{ background_id: "bg-custom", label: "自訂背景", url: "/bg.png", in_project_scope: false }],
  );
  assert.equal(bgOptions.find((b) => b.id === "default")?.in_project_scope, true);
  assert.equal(bgOptions.find((b) => b.id === "uploaded:bg-custom")?.in_project_scope, false);

  // 5. 確保元件模板有掛上提示文案
  const modalSource = read("components/controls/SettingsModal.vue");
  assert.match(modalSource, /不在專案範圍內，一般使用者無法使用/);
});

test("settings-modal.css styles background out-of-scope items with theme danger token", () => {
  const cssSource = read("styles/settings-modal.css");
  assert.match(cssSource, /\.background-option--out-of-scope \.background-option__label\s*\{[\s\S]*?color:\s*rgb\(var\(--ov-color-danger\)\);/);
  assert.match(cssSource, /\.background-option__scope-note\s*\{[\s\S]*?color:\s*rgb\(var\(--ov-color-danger\)\);/);
});

test("MascotSwitcher renders out-of-scope mascots with theme danger token and note", () => {
  const mascotSource = read("components/mascot/MascotSwitcher.vue");

  assert.match(mascotSource, /'mascot-switcher__option--out-of-scope':\s*mascot\.in_project_scope === false/);
  assert.match(mascotSource, /class="mascot-switcher__scope-note"/);
  assert.match(mascotSource, /不在專案範圍內，一般使用者無法使用/);
  assert.match(mascotSource, /'mascot-switcher__label--out-of-scope':\s*currentMascot\?\.in_project_scope === false/);

  assert.match(mascotSource, /\.mascot-switcher__option--out-of-scope \.mascot-switcher__option-text strong\s*\{[\s\S]*?color:\s*rgb\(var\(--ov-color-danger\)\);/);
  assert.match(mascotSource, /\.mascot-switcher__scope-note\s*\{[\s\S]*?color:\s*rgb\(var\(--ov-color-danger\)\);/);
  assert.match(mascotSource, /\.mascot-switcher__label--out-of-scope\s*\{[\s\S]*?color:\s*rgb\(var\(--ov-color-danger\)\);/);
});

test("useAvatarBootstrap passes project_id to fetchTtsProviders when project is set", () => {
  const bootSource = read("composables/useAvatarBootstrap.ts");
  assert.match(bootSource, /const res = projectId\s*\?\s*await apiFetch\(`\/api\/v1\/tts\/providers\?project_id=\${encodeURIComponent\(projectId\)}`\)\s*:\s*await apiFetch\("\/api\/v1\/tts\/providers"\)/);
});
