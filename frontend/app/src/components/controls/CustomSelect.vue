<template>
  <select
      class="custom-select"
      :value="modelValue"
      :disabled="disabled"
      @change="handleChange"
    >
    <option v-if="placeholder" value="" disabled>{{ placeholder }}</option>
    <option
      v-for="option in options"
      :key="option.value"
      :value="option.value"
    >
      {{ option.label }}
    </option>
  </select>
</template>

<script setup lang="ts">
export interface SelectOption {
  value: string
  label: string
}

defineProps<{
  modelValue: string
  options: SelectOption[]
  disabled?: boolean
  placeholder?: string
}>()

const emit = defineEmits<{
  (e: "update:modelValue", value: string): void
  (e: "change", value: string): void
}>()

function handleChange(event: Event): void {
  const value = (event.target as HTMLSelectElement).value
  emit("update:modelValue", value)
  emit("change", value)
}
</script>

<style scoped>
.custom-select {
  width: 100%;
  min-height: 2.75rem;
  padding: 0 2.5rem 0 0.875rem;
  background: var(--bg-soft, #fff);
  border: 1px solid var(--line, #e2e8f0);
  border-radius: 0.5rem;
  color: var(--text, #0f172a);
  font-size: 0.95rem;
  font-weight: 500;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s, background-color 0.15s;
}

.custom-select:hover:not(:disabled) {
  border-color: var(--primary, #0ea5e9);
  background: var(--bg-soft-hover, #f8fafc);
}

.custom-select:focus-visible {
  border-color: var(--primary, #0ea5e9);
  box-shadow: 0 0 0 0.1875rem rgba(14, 165, 233, 0.15);
}

.custom-select:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>
