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
  /* 沒有 appearance: none 的話，瀏覽器會在我們畫好的框上再畫一次自己的
     邊框與箭頭，看起來就是沒套到樣式。右側 padding 是留給下面那支箭頭的。 */
  appearance: none;
  -webkit-appearance: none;
  background-color: var(--bg-soft, #fff);
  /* 箭頭用 inline SVG 畫，不另外拉圖檔，也不必多一層 wrapper 元素。 */
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23706b63' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='6 9 12 15 18 9'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 0.875rem center;
  background-size: 1.1rem;
  border: 1px solid var(--line, #e7e4de);
  border-radius: 0.5rem;
  color: var(--text, #1c1a17);
  font-size: 0.95rem;
  font-weight: 500;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s, background-color 0.15s;
}

/* 展開的選項清單由作業系統畫，CSS 幾乎管不到——至少讓它跟著深淺色走，
   不要在深色介面上跳出一張白底清單。 */
.custom-select option {
  background: var(--bg-soft, #fff);
  color: var(--text, #1c1a17);
}

.custom-select:hover:not(:disabled) {
  border-color: var(--primary, #c96442);
  background-color: var(--bg-soft-hover, #f8fafc);
}

.custom-select:focus-visible {
  border-color: var(--primary, #c96442);
  box-shadow: 0 0 0 0.1875rem color-mix(in srgb, var(--primary) 18%, transparent);
}

.custom-select:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>
