<script setup lang="ts">
import { nextTick, ref, watch } from "vue";
import { verifyPassword } from "../../api/auth";

const props = defineProps<{
  open: boolean
  username: string
}>();

const emit = defineEmits<{
  (e: "close"): void
  (e: "unlocked"): void
}>();

const password = ref("");
const error = ref("");
const checking = ref(false);
const inputRef = ref<HTMLInputElement | null>(null);

watch(() => props.open, async (open) => {
  password.value = "";
  error.value = "";
  if (open) {
    await nextTick();
    inputRef.value?.focus();
  }
});

async function submit(): Promise<void> {
  if (!password.value || checking.value) return;
  checking.value = true;
  error.value = "";
  try {
    await verifyPassword(password.value);
    emit("unlocked");
    emit("close");
  } catch (reason) {
    error.value = reason instanceof Error && reason.message ? reason.message : "密碼不正確";
    password.value = "";
    inputRef.value?.focus();
  } finally {
    checking.value = false;
  }
}
</script>

<template>
  <div v-if="open" class="unlock-backdrop" @click.self="emit('close')">
    <form
      class="unlock-card"
      role="dialog"
      aria-modal="true"
      aria-labelledby="unlock-title"
      @submit.prevent="submit"
      @keydown.esc="emit('close')"
    >
      <h2 id="unlock-title">現場人員解鎖</h2>
      <p class="unlock-hint">輸入帳號 {{ username }} 的密碼，暫時顯示設定與登出；重新整理後會再藏起來。</p>
      <input
        ref="inputRef"
        v-model="password"
        class="unlock-input"
        type="password"
        autocomplete="current-password"
        aria-label="密碼"
        :disabled="checking"
      />
      <p v-if="error" class="unlock-error" role="alert">{{ error }}</p>
      <div class="unlock-actions">
        <button type="button" class="unlock-btn" @click="emit('close')">取消</button>
        <button type="submit" class="unlock-btn unlock-btn--primary" :disabled="!password || checking">
          {{ checking ? "確認中…" : "解鎖" }}
        </button>
      </div>
    </form>
  </div>
</template>

<style scoped>
.unlock-backdrop {
  position: fixed;
  inset: 0;
  z-index: var(--ov-z-modal);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1rem;
  background: rgba(0, 0, 0, 0.45);
}

.unlock-card {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  width: 100%;
  max-width: 24rem;
  padding: 1.5rem;
  border-radius: 1rem;
  border: var(--hairline) solid var(--line);
  background: var(--bg-soft);
  color: var(--text);
}

.unlock-card h2 {
  margin: 0;
  font-size: 1.1rem;
}

.unlock-hint {
  margin: 0;
  color: var(--text-soft);
  font-size: 0.85rem;
  line-height: 1.5;
}

.unlock-input {
  height: 2.75rem;
  padding: 0 0.75rem;
  border: var(--hairline) solid var(--line);
  border-radius: 0.5rem;
  background: var(--bg);
  color: var(--text);
  font: inherit;
}

.unlock-error {
  margin: 0;
  color: rgb(var(--ov-color-danger));
  font-size: 0.85rem;
}

.unlock-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
}

.unlock-btn {
  min-height: 2.75rem;
  padding: 0 1rem;
  border: var(--hairline) solid var(--line);
  border-radius: 0.5rem;
  background: var(--bg);
  color: var(--text);
  font: inherit;
  cursor: pointer;
}

.unlock-btn--primary {
  border-color: var(--primary);
  background: var(--primary);
  color: #fff;
}

.unlock-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
