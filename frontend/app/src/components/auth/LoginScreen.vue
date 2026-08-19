<script setup lang="ts">
import { ref } from "vue"

import { useAuth } from "../../composables/useAuth"

const auth = useAuth()
const mode = ref<"formal" | "temporary">("formal")
const username = ref("")
const password = ref("")
const submitting = ref(false)
const error = ref("")

async function submit(): Promise<void> {
  if (!password.value || (mode.value === "formal" && !username.value.trim())) {
    error.value = mode.value === "formal" ? "請輸入帳號與密碼" : "請輸入臨時密碼"
    return
  }

  submitting.value = true
  error.value = ""
  try {
    if (mode.value === "temporary") {
      await auth.loginTemporary(password.value)
    } else {
      await auth.login(username.value.trim(), password.value)
    }
  } catch (reason) {
    const rawMsg = reason instanceof Error && reason.message ? reason.message : ""
    if (rawMsg === "Invalid credentials") {
      error.value = mode.value === "temporary"
        ? "密碼錯誤，或該批次已被撤銷"
        : "帳號或密碼錯誤"
    } else {
      error.value = rawMsg || "登入失敗，請稍後再試"
    }
  } finally {
    submitting.value = false
  }
}

function selectMode(nextMode: "formal" | "temporary"): void {
  mode.value = nextMode
  password.value = ""
  error.value = ""
}
</script>

<template>
  <main class="login-page">
    <section class="login-shell">
      <div class="login-context">
        <div class="brand-row">
          <span class="brand-mark" aria-hidden="true">OV</span>
          <span>openVman Avatar</span>
        </div>
        <div class="context-copy">
          <h1>回到你的虛擬人物工作區</h1>
          <p>帳號會分開保存可使用的知識庫、人物與自訂聲音。</p>
        </div>
        <dl class="resource-summary">
          <div>
            <dt>知識庫</dt>
            <dd>只列出目前帳號可使用的專案內容。</dd>
          </div>
          <div>
            <dt>人物與聲音</dt>
            <dd>人物設定與自訂聲音不會跨帳號共用。</dd>
          </div>
        </dl>
      </div>

      <div class="login-panel">
        <header>
          <h2>{{ mode === "formal" ? "帳號登入" : "臨時存取" }}</h2>
          <p>
            {{ mode === "formal"
              ? "使用管理員為你建立的正式帳號。"
              : "輸入一次性提供的臨時密碼，不需要帳號名稱。" }}
          </p>
        </header>
        <div class="login-modes" role="tablist" aria-label="登入方式">
          <button
            class="login-mode"
            :class="{ active: mode === 'formal' }"
            type="button"
            role="tab"
            :aria-selected="mode === 'formal'"
            :disabled="submitting"
            @click="selectMode('formal')"
          >
            正式帳號
          </button>
          <button
            class="login-mode"
            :class="{ active: mode === 'temporary' }"
            type="button"
            role="tab"
            :aria-selected="mode === 'temporary'"
            :disabled="submitting"
            @click="selectMode('temporary')"
          >
            臨時密碼
          </button>
        </div>
        <form class="login-form" @submit.prevent="submit">
          <p v-if="error" class="login-error" role="alert">{{ error }}</p>
          <label v-if="mode === 'formal'">
            <span>帳號</span>
            <input
              v-model="username"
              autocomplete="username"
              :disabled="submitting"
              autofocus
            />
          </label>
          <label>
            <span>{{ mode === "formal" ? "密碼" : "臨時密碼" }}</span>
            <input
              v-model="password"
              :type="mode === 'formal' ? 'password' : 'text'"
              :autocomplete="mode === 'formal' ? 'current-password' : 'one-time-code'"
              :disabled="submitting"
            />
          </label>
          <button class="submit-button" type="submit" :disabled="submitting">
            {{ submitting ? "登入中…" : mode === "formal" ? "登入工作區" : "使用臨時密碼登入" }}
          </button>
        </form>
      </div>
    </section>
  </main>
</template>

<style scoped>
/* Hallmark · pre-emit critique: P5 H5 E4 S5 R5 V4 · macrostructure: Workbench · genre: modern-minimal · theme: existing warm-neutral teal · slop: pass */
.login-page {
  min-height: 100dvh;
  display: grid;
  place-items: center;
  padding: clamp(1rem, 5vw, 4rem);
  background: var(--bg);
  color: var(--text);
  font-family: var(--ov-font-ui);
}

.login-shell {
  width: min(100%, 68rem);
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(19rem, 0.8fr);
  border: var(--hairline) solid var(--line);
  border-radius: 1rem;
  overflow: clip;
  background: var(--bg-soft);
}

.login-context,
.login-panel {
  min-width: 0;
  padding: clamp(2rem, 5vw, 4.5rem);
}

.login-context {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: clamp(3rem, 9vw, 7rem);
  background: var(--bg);
}

.brand-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  font-weight: 700;
}

.brand-mark {
  width: 2.75rem;
  aspect-ratio: 1;
  display: grid;
  place-items: center;
  border: var(--hairline) solid var(--primary);
  border-radius: 0.75rem;
  color: var(--primary-hover);
  font-weight: 800;
  letter-spacing: -0.05em;
}

.context-copy {
  max-width: 38rem;
}

h1 {
  margin: 0;
  font-size: clamp(2.25rem, 5vw, 4.25rem);
  line-height: 1.08;
  letter-spacing: -0.035em;
  overflow-wrap: anywhere;
}

.context-copy p,
.login-panel header p {
  margin: 1rem 0 0;
  color: var(--text-soft);
  line-height: 1.65;
}

.resource-summary {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1.5rem;
  margin: 0;
}

.resource-summary div {
  padding-top: 1rem;
  border-top: var(--hairline) solid var(--line);
}

.resource-summary dt {
  font-weight: 700;
}

.resource-summary dd {
  margin: 0.45rem 0 0;
  color: var(--text-soft);
  font-size: 0.875rem;
  line-height: 1.6;
}

.login-panel {
  display: flex;
  flex-direction: column;
  justify-content: center;
  border-left: var(--hairline) solid var(--line);
}

.login-panel h2 {
  margin: 0;
  font-size: 1.75rem;
  line-height: 1.2;
}

.login-form {
  display: grid;
  gap: 1rem;
  margin-top: 2rem;
}

.login-modes {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.25rem;
  margin-top: 2rem;
  padding: 0.25rem;
  border: var(--hairline) solid var(--line);
  border-radius: 0.75rem;
  background: var(--bg);
}

.login-mode {
  min-height: var(--ov-touch-target);
  padding: 0.65rem 0.75rem;
  border: 0;
  border-radius: 0.55rem;
  background: transparent;
  color: var(--text-soft);
  font: inherit;
  font-weight: 700;
  cursor: pointer;
  white-space: nowrap;
}

.login-mode.active {
  background: var(--primary);
  color: var(--bg-soft);
}

.login-mode:hover:not(:disabled):not(.active) {
  background: color-mix(in srgb, var(--primary) 8%, var(--bg));
  color: var(--text);
}

.login-mode:active:not(:disabled) {
  background: color-mix(in srgb, var(--primary) 14%, var(--bg));
}

.login-mode:focus-visible,
.submit-button:focus-visible {
  outline: var(--focus-ring-size) solid var(--primary);
  outline-offset: var(--ov-focus-ring-offset);
}

label {
  display: grid;
  gap: 0.5rem;
  color: var(--text);
  font-size: 0.875rem;
  font-weight: 600;
}

input {
  width: 100%;
  padding: 0.75rem 0.875rem;
  border: var(--hairline) solid var(--line);
  border-radius: 0.75rem;
  background: var(--bg);
  color: var(--text);
  font: inherit;
  outline: none;
}

input:focus-visible {
  border-color: var(--primary);
  box-shadow: 0 0 0 var(--focus-ring-size) color-mix(in srgb, var(--primary) 18%, transparent);
}

.submit-button {
  margin-top: 0.5rem;
  min-height: var(--ov-touch-target);
  padding: 0.8rem 1rem;
  border: 0;
  border-radius: 0.75rem;
  background: var(--primary);
  color: var(--bg-soft);
  font: inherit;
  font-weight: 800;
  cursor: pointer;
  white-space: nowrap;
  transition: transform var(--ov-dur-micro) var(--ov-ease-out);
}

.submit-button:hover:not(:disabled) {
  transform: translateY(-0.0625rem);
}

.submit-button:active:not(:disabled) {
  transform: none;
}

.submit-button:disabled,
.login-mode:disabled,
input:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.login-error {
  margin: 0;
  padding: 0.75rem;
  border: var(--hairline) solid rgb(var(--ov-color-danger));
  border-radius: 0.75rem;
  background: color-mix(in srgb, rgb(var(--ov-color-danger)) 8%, transparent);
  color: rgb(var(--ov-color-danger));
  font-size: 0.875rem;
}

@media (max-width: 48rem) {
  .login-page {
    place-items: start center;
  }

  .login-shell {
    grid-template-columns: minmax(0, 1fr);
  }

  .login-context {
    gap: 2.5rem;
  }

  .login-panel {
    border-top: var(--hairline) solid var(--line);
    border-left: 0;
  }
}

@media (max-width: 26rem) {
  .resource-summary {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
