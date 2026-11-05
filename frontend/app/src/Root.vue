<script setup lang="ts">
import { computed, onMounted, watch } from "vue"

import App from "./App.vue"
import LoginScreen from "./components/auth/LoginScreen.vue"
import { useAuth } from "./composables/useAuth"
import { useSessionLogout } from "./composables/useSessionLogout"
import { cleanupLoggedOutSession } from "./sessionCleanup"

const auth = useAuth()
const { loggingOut, handleLogout } = useSessionLogout()

const isTemporary = computed(() => {
  const account = auth.account.value
  return account?.kind === "temporary"
    || account?.account_type === "temporary"
    || Boolean(account?.expires_at)
})

watch(
  () => [auth.loading.value, auth.account.value] as const,
  ([loading, account]) => {
    cleanupLoggedOutSession(loading, account)
  },
)

onMounted(() => {
  void auth.bootstrap()
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
  <App v-else />
</template>

<style scoped>
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
</style>
