<template>
  <div ref="containerRef" class="custom-select" :class="{ 'custom-select--disabled': disabled }">
    <button
      type="button"
      class="custom-select__trigger"
      :class="{ 'custom-select__trigger--open': open }"
      :disabled="disabled"
      @click="toggleDropdown"
    >
      <span class="custom-select__label">{{ displayLabel }}</span>
      <svg class="custom-select__arrow" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="6 9 12 15 18 9"></polyline>
      </svg>
    </button>

    <Transition name="slide">
      <div v-if="open" class="custom-select__dropdown" :class="{ 'custom-select__dropdown--dropup': dropUp }">
        <ul role="listbox" class="custom-select__options">
          <li
            v-for="option in options"
            :key="option.value"
            role="option"
            :aria-selected="option.value === modelValue"
            class="custom-select__option"
            :class="{ 'custom-select__option--selected': option.value === modelValue }"
            @click="selectOption(option.value)"
          >
            {{ option.label }}
          </li>
        </ul>
      </div>
    </Transition>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from "vue"

export interface SelectOption {
  value: string
  label: string
}

const props = defineProps<{
  modelValue: string
  options: SelectOption[]
  disabled?: boolean
  placeholder?: string
}>()

const emit = defineEmits<{
  (e: "update:modelValue", value: string): void
  (e: "change", value: string): void
}>()

const open = ref(false)
const dropUp = ref(false)
const containerRef = ref<HTMLDivElement | null>(null)

const selectedOption = computed(() => props.options.find(o => o.value === props.modelValue))
const displayLabel = computed(() => selectedOption.value?.label || props.placeholder || "")

function toggleDropdown(): void {
  if (props.disabled) return
  if (!open.value) {
    checkDropdownDirection()
  }
  open.value = !open.value
}

function checkDropdownDirection(): void {
  if (!containerRef.value) return
  const rect = containerRef.value.getBoundingClientRect()
  const spaceBelow = window.innerHeight - rect.bottom
  // If less than 200px below and enough space above, drop up
  dropUp.value = spaceBelow < 200 && rect.top > spaceBelow
}

function selectOption(value: string): void {
  emit("update:modelValue", value)
  emit("change", value)
  open.value = false
}

function handleClickOutside(event: MouseEvent): void {
  if (containerRef.value && !containerRef.value.contains(event.target as Node)) {
    open.value = false
  }
}

onMounted(() => {
  document.addEventListener("click", handleClickOutside)
})

onUnmounted(() => {
  document.removeEventListener("click", handleClickOutside)
})
</script>

<style scoped>
.custom-select {
  position: relative;
  width: 100%;
}

.custom-select__trigger {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  height: 2.5rem;
  padding: 0 0.875rem;
  background: var(--bg-soft, #fff);
  border: 1px solid var(--line, #e2e8f0);
  border-radius: 0.5rem;
  color: var(--text, #0f172a);
  font-size: 0.95rem;
  font-weight: 500;
  text-align: left;
  cursor: pointer;
  outline: none;
  transition: border-color 0.15s, box-shadow 0.15s, background-color 0.15s;
}

.custom-select__trigger:hover:not(:disabled) {
  border-color: var(--primary, #0ea5e9);
  background: var(--bg-soft-hover, #f8fafc);
}

.custom-select__trigger:focus {
  border-color: var(--primary, #0ea5e9);
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.15);
}

.custom-select__trigger--open {
  border-color: var(--primary, #0ea5e9);
}

.custom-select__label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin-right: 0.5rem;
}

.custom-select__arrow {
  color: var(--text-soft, #64748b);
  transition: transform 0.2s;
  flex-shrink: 0;
}

.custom-select__trigger--open .custom-select__arrow {
  transform: rotate(180deg);
}

.custom-select__dropdown {
  position: absolute;
  z-index: 999;
  width: 100%;
  background: var(--bg-soft, #fff);
  border: 1px solid var(--line, #e2e8f0);
  border-radius: 0.625rem;
  box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.1), 0 8px 10px -6px rgba(0, 0, 0, 0.1);
  overflow: hidden;
}

.custom-select__dropdown:not(.custom-select__dropdown--dropup) {
  top: calc(100% + 0.25rem);
}

.custom-select__dropdown--dropup {
  bottom: calc(100% + 0.25rem);
}

.custom-select__options {
  list-style: none;
  margin: 0;
  padding: 0.25rem;
  max-height: 12.5rem;
  overflow-y: auto;
  scrollbar-width: thin;
}

.custom-select__option {
  padding: 0.625rem 0.75rem;
  font-size: 0.9rem;
  color: var(--text, #334155);
  border-radius: 0.375rem;
  cursor: pointer;
  transition: background-color 0.12s, color 0.12s;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.custom-select__option:hover {
  background: var(--line, #f1f5f9);
  color: var(--text-strong, #0f172a);
}

.custom-select__option--selected {
  background: rgba(14, 165, 233, 0.1);
  color: var(--primary, #0ea5e9);
  font-weight: 600;
}

.custom-select__option--selected:hover {
  background: rgba(14, 165, 233, 0.15);
  color: var(--primary, #0ea5e9);
}

.custom-select--disabled {
  opacity: 0.6;
}

.custom-select--disabled .custom-select__trigger {
  cursor: not-allowed;
}

/* Slide Transition */
.slide-enter-active,
.slide-leave-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}

.slide-enter-from,
.slide-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

.custom-select__dropdown--dropup.slide-enter-from,
.custom-select__dropdown--dropup.slide-leave-to {
  transform: translateY(4px);
}
</style>
