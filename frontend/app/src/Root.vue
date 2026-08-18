<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue"

import App from "./App.vue"
import LoginScreen from "./components/auth/LoginScreen.vue"
import { useAuth } from "./composables/useAuth"
import {
  cleanupLoggedOutSession,
  leaveFullscreen,
  runLogout,
} from "./sessionCleanup"

const auth = useAuth()
const now = ref(Date.now())
const loggingOut = ref(false)
const sessionStartedAt = Date.now()
let clock: number | undefined

const isTemporary = computed(() => {
  const account = auth.account.value
  return account?.kind === "temporary"
    || account?.account_type === "temporary"
    || Boolean(account?.expires_at)
})

const remainingSeconds = computed(() => {
  const account = auth.account.value
  if (!account) return 0
  if (account.expires_at) {
    const expiresAt = new Date(account.expires_at).getTime()
    return Number.isFinite(expiresAt)
      ? Math.max(0, Math.floor((expiresAt - now.value) / 1000))
      : Math.max(0, account.remaining_seconds ?? 0)
  }
  const elapsed = Math.floor((now.value - sessionStartedAt) / 1000)
  return Math.max(0, (account.remaining_seconds ?? 0) - elapsed)
})

const remainingLabel = computed(() => {
  const totalMinutes = Math.max(0, Math.ceil(remainingSeconds.value / 60))
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60
  return hours > 0 ? `${hours} 小時 ${minutes} 分` : `${minutes} 分`
})

const expiresLabel = computed(() => {
  const value = auth.account.value?.expires_at
  if (!value) return "到期時間待同步"
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? "到期時間待同步"
    : new Intl.DateTimeFormat("zh-TW", {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(date)
})

async function handleLogout(): Promise<void> {
  await runLogout({
    isLoggingOut: () => loggingOut.value,
    setLoggingOut: (value) => {
      loggingOut.value = value
    },
    cleanup: leaveFullscreen,
    logout: auth.logout,
  })
}

watch(
  () => [auth.loading.value, auth.account.value] as const,
  ([loading, account]) => {
    cleanupLoggedOutSession(loading, account)
  },
)

onMounted(() => {
  void auth.bootstrap()
  clock = window.setInterval(() => {
    now.value = Date.now()
  }, 60_000)
})

onUnmounted(() => {
  if (clock !== undefined) window.clearInterval(clock)
})
</script>

<template>
  <main v-if="auth.loading.value" class="session-state" role="status">
    正在確認登入狀態…
  </main>
  <LoginScreen v-else-if="!auth.account.value" />
  <main v-else-if="auth.forbidden.value" class="session-state">
    <section class="forbidden-card">
      <p class="forbidden-symbol" aria-hidden="true">!</p>
      <h1>權限不足</h1>
      <p v-if="isTemporary">此臨時存取沒有存取這個功能的權限。</p>
      <p v-else>帳號「{{ auth.account.value.username }}」沒有存取這個功能的權限。</p>
      <div class="forbidden-actions">
        <button type="button" @click="auth.clearForbidden">返回</button>
        <button
          class="forbidden-logout"
          type="button"
          :disabled="loggingOut"
          @click="handleLogout"
        >
          {{ loggingOut ? "登出中…" : "登出" }}
        </button>
      </div>
    </section>
  </main>
  <div v-else class="authenticated-app">
    <App />
    <div class="session-toolbar">
      <span v-if="isTemporary" class="temporary-session">
        <strong>臨時存取</strong>
        <span>剩餘 {{ remainingLabel }}</span>
        <span>{{ expiresLabel }} 到期</span>
      </span>
      <span v-else>{{ auth.account.value.username }}</span>
      <button
        class="session-logout"
        type="button"
        :disabled="loggingOut"
        @click="handleLogout"
      >
        {{ loggingOut ? "登出中…" : "登出" }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.authenticated-app {
  min-height: 100dvh;
}

.session-toolbar {
  position: fixed;
  top: 1rem;
  right: 1rem;
  z-index: var(--ov-z-sticky);
  display: flex;
  align-items: center;
  gap: 0.65rem;
  max-width: 45%;
  padding: 0.45rem 0.65rem 0.45rem 0.85rem;
  border: var(--hairline) solid var(--line);
  border-radius: 999rem;
  background: var(--bg-soft);
  color: var(--text);
  font-family: var(--ov-font-ui);
  font-size: 0.75rem;
}

.session-toolbar span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.temporary-session {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  font-variant-numeric: tabular-nums;
}

.temporary-session span + span::before {
  content: "·";
  margin-right: 0.45rem;
  color: var(--text-soft);
}

.forbidden-actions button {
  min-height: var(--ov-touch-target);
  padding: 0.4rem 0.75rem;
  border: 0;
  border-radius: 999rem;
  background: var(--primary);
  color: var(--bg-soft);
  font: inherit;
  font-weight: 700;
  cursor: pointer;
  white-space: nowrap;
}

.forbidden-actions button:hover {
  background: var(--primary-hover);
}

.forbidden-actions button:focus-visible {
  outline: var(--focus-ring-size) solid var(--primary);
  outline-offset: var(--ov-focus-ring-offset);
}

.forbidden-actions button:active {
  filter: brightness(0.94);
}

.forbidden-actions button:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.session-logout {
  min-height: var(--ov-touch-target);
  padding: 0.4rem 0.2rem 0.4rem 0.7rem;
  border: 0;
  border-left: var(--hairline) solid var(--line);
  border-radius: 0;
  background: transparent;
  color: var(--text-soft);
  font: inherit;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  transition: opacity var(--ov-dur-micro) var(--ov-ease-out);
}

.session-logout:hover:not(:disabled) {
  color: var(--text);
  text-decoration: underline;
  text-underline-offset: 0.2em;
}

.session-logout:focus-visible {
  outline: var(--focus-ring-size) solid var(--primary);
  outline-offset: var(--ov-focus-ring-offset);
}

.session-logout:active:not(:disabled) {
  color: var(--primary-hover);
}

.session-logout:disabled {
  cursor: wait;
  opacity: 0.55;
}

.forbidden-actions .forbidden-logout {
  border: var(--hairline) solid var(--line);
  background: transparent;
  color: var(--text-soft);
}

.forbidden-actions .forbidden-logout:hover:not(:disabled) {
  border-color: var(--text-soft);
  background: var(--bg);
  color: var(--text);
}

.session-state {
  min-height: 100dvh;
  display: grid;
  place-items: center;
  padding: 6vw;
  background: var(--bg);
  color: var(--text);
  font-family: var(--ov-font-ui);
}

.forbidden-card {
  max-width: 30rem;
  text-align: center;
}

.forbidden-symbol {
  width: 3.5rem;
  aspect-ratio: 1;
  display: grid;
  place-items: center;
  margin: 0 auto 1rem;
  border-radius: 999rem;
  background: rgb(var(--ov-color-warn));
  color: var(--bg-soft);
  font-size: 2rem;
  font-weight: 900;
}

.forbidden-card h1 {
  margin: 0;
}

.forbidden-card p {
  color: var(--text-soft);
}

.forbidden-actions {
  display: flex;
  justify-content: center;
  gap: 0.75rem;
  margin-top: 1.5rem;
}

@media (max-width: 42rem) {
  .session-toolbar {
    top: auto;
    right: 0.75rem;
    bottom: 0.75rem;
    left: 0.75rem;
    max-width: none;
  }

  .temporary-session {
    flex: 1;
    flex-wrap: wrap;
  }
}
</style>
