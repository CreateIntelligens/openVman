<script lang="ts">
// 放模組層：訪客模式解鎖才掛載這個元件，沒有到期時間的臨時帳號仍要從進頁面起算。
const sessionStartedAt = Date.now();
</script>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useAuth } from "../../composables/useAuth";

const auth = useAuth();
const now = ref(Date.now());
let clock: number | undefined;

const isTemporary = computed(() => {
  const account = auth.account.value;
  return account?.kind === "temporary"
    || account?.account_type === "temporary"
    || Boolean(account?.expires_at);
});

const remainingSeconds = computed(() => {
  const account = auth.account.value;
  if (!account) return 0;
  if (account.expires_at) {
    const expiresAt = new Date(account.expires_at).getTime();
    return Number.isFinite(expiresAt)
      ? Math.max(0, Math.floor((expiresAt - now.value) / 1000))
      : Math.max(0, account.remaining_seconds ?? 0);
  }
  const elapsed = Math.floor((now.value - sessionStartedAt) / 1000);
  return Math.max(0, (account.remaining_seconds ?? 0) - elapsed);
});

const remainingLabel = computed(() => {
  const totalMinutes = Math.max(0, Math.ceil(remainingSeconds.value / 60));
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return hours > 0 ? `${hours} 小時 ${minutes} 分` : `${minutes} 分`;
});

const expiresLabel = computed(() => {
  const value = auth.account.value?.expires_at;
  if (!value) return "到期時間待同步";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "到期時間待同步"
    : new Intl.DateTimeFormat("zh-TW", {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(date);
});

onMounted(() => {
  clock = window.setInterval(() => {
    now.value = Date.now();
  }, 60_000);
});

onUnmounted(() => {
  if (clock !== undefined) window.clearInterval(clock);
});
</script>

<template>
  <span v-if="isTemporary" class="session-label session-label--temporary">
    <strong>臨時存取</strong>
    <span>剩餘 {{ remainingLabel }}</span>
    <span class="session-label__expiry">{{ expiresLabel }} 到期</span>
  </span>
  <span v-else class="session-label">{{ auth.account.value?.username }}</span>
</template>

<style scoped>
.session-label {
  overflow: hidden;
  min-width: 0;
  color: var(--text-soft);
  font-size: 0.75rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-label--temporary {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  font-variant-numeric: tabular-nums;
}

.session-label--temporary strong {
  color: var(--text);
  font-weight: 600;
}

/* 窄畫面只留剩餘時間：到期時間跟它講的是同一件事，放不下時先讓位。 */
@media (max-width: 42rem) {
  .session-label__expiry {
    display: none;
  }
}
</style>
