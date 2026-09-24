<template>
  <div ref="rootRef" class="custom-select" :class="{ 'custom-select--open': open }">
    <button
      ref="triggerRef"
      type="button"
      class="custom-select__trigger"
      role="combobox"
      :aria-label="ariaLabel ?? placeholder ?? '選擇選項'"
      :aria-expanded="open"
      :aria-controls="listboxId"
      aria-haspopup="listbox"
      :aria-activedescendant="open && focusedIndex >= 0 ? optionId(focusedIndex) : undefined"
      :disabled="disabled"
      @click="open ? close() : openList()"
      @keydown="handleKeydown"
    >
      <span class="custom-select__value" :class="{ 'custom-select__value--placeholder': !selected }">
        {{ selected?.label ?? placeholder ?? '' }}
      </span>
      <svg
        class="custom-select__arrow"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
        aria-hidden="true"
      >
        <polyline points="6 9 12 15 18 9" />
      </svg>
    </button>

    <div
      v-if="open"
      :id="listboxId"
      ref="listRef"
      class="custom-select__list"
      role="listbox"
      :aria-label="ariaLabel ?? placeholder ?? '選擇選項'"
      :style="listStyle"
    >
      <div
        v-for="(option, index) in options"
        :id="optionId(index)"
        :key="option.value"
        class="custom-select__option"
        :class="{
          'custom-select__option--selected': option.value === modelValue,
          'custom-select__option--focused': index === focusedIndex,
        }"
        role="option"
        :aria-selected="option.value === modelValue"
        @mousedown.prevent="choose(option.value)"
        @mouseenter="focusedIndex = index"
      >
        {{ option.label }}
      </div>
      <div v-if="!options.length" class="custom-select__empty">沒有可選的項目</div>
    </div>
  </div>
</template>

<script setup lang="ts">
/*
 * 自己畫的下拉選單，外觀與操作對齊後台的 Select（frontend/admin/src/components/Select.tsx）。
 *
 * 原本是原生 <select>：收起來的框套得到樣式，但點開的選項清單由作業系統畫，CSS
 * 管不到，永遠是白底、系統字型、系統藍色選取條。這裡改成按鈕加 HTML 選項清單，
 * 清單才能跟著主題色與深淺色走。v-model 與 change 事件照舊，呼叫端不用改。
 *
 * 清單用 position: fixed 依按鈕位置擺放：設定視窗內容區會捲動（overflow: auto），
 * 絕對定位會被裁掉；也不能 Teleport 到 body，因為設定視窗是 top layer 的 <dialog>，
 * 放到 body 會被它蓋住。
 */
import { computed, nextTick, onBeforeUnmount, ref, useId, watch } from 'vue'

export interface SelectOption {
  value: string
  label: string
}

const props = defineProps<{
  modelValue: string
  options: SelectOption[]
  disabled?: boolean
  placeholder?: string
  ariaLabel?: string
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
  (e: 'change', value: string): void
}>()

// 清單的最大高度（12.5rem）加一點間距；按鈕下方放不下、上方比較寬時往上開。
const LIST_ROOM_REM = 13.5
const TYPEAHEAD_RESET_MS = 700

const open = ref(false)
const focusedIndex = ref(-1)
const listStyle = ref<Record<string, string>>({})
const rootRef = ref<HTMLElement | null>(null)
const triggerRef = ref<HTMLButtonElement | null>(null)
const listRef = ref<HTMLElement | null>(null)
const listboxId = `custom-select-${useId()}`
let typeahead = { value: '', time: 0 }

const selected = computed(() => props.options.find((o) => o.value === props.modelValue))

function optionId(index: number): string {
  return `${listboxId}-option-${index}`
}

function remToPx(rem: number): number {
  return rem * Number.parseFloat(getComputedStyle(document.documentElement).fontSize || '16')
}

function place(): void {
  const rect = triggerRef.value?.getBoundingClientRect()
  if (!rect) return
  const below = window.innerHeight - rect.bottom
  const dropUp = below < remToPx(LIST_ROOM_REM) && rect.top > below
  listStyle.value = {
    left: `${rect.left}px`,
    width: `${rect.width}px`,
    ...(dropUp
      ? { bottom: `${window.innerHeight - rect.top + 4}px` }
      : { top: `${rect.bottom + 4}px` }),
  }
}

function openList(): void {
  if (props.disabled) return
  const index = props.options.findIndex((o) => o.value === props.modelValue)
  focusedIndex.value = index >= 0 ? index : 0
  place()
  open.value = true
}

function close(): void {
  open.value = false
}

function choose(value: string): void {
  close()
  if (value === props.modelValue) return
  // 跟原生 <select> 一樣：值真的變了才送 change。
  emit('update:modelValue', value)
  emit('change', value)
}

function move(index: number): void {
  if (!props.options.length) return
  focusedIndex.value = Math.min(Math.max(index, 0), props.options.length - 1)
  if (!open.value) openList()
}

function handleKeydown(event: KeyboardEvent): void {
  if (props.disabled) return
  const { key } = event
  if (key === 'Enter' || key === ' ') {
    event.preventDefault()
    const option = props.options[focusedIndex.value]
    if (open.value && option) choose(option.value)
    else openList()
  } else if (key === 'ArrowDown') {
    event.preventDefault()
    if (open.value) move(focusedIndex.value + 1)
    else openList()
  } else if (key === 'ArrowUp') {
    event.preventDefault()
    if (open.value) move(focusedIndex.value - 1)
  } else if (key === 'Home' || key === 'End') {
    event.preventDefault()
    move(key === 'Home' ? 0 : props.options.length - 1)
  } else if (key === 'Escape') {
    if (open.value) {
      // 只關清單，不要連設定視窗一起關掉。
      event.preventDefault()
      event.stopPropagation()
      close()
    }
  } else if (key === 'Tab') {
    close()
  } else if (key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
    const now = Date.now()
    const prefix = now - typeahead.time > TYPEAHEAD_RESET_MS ? key : `${typeahead.value}${key}`
    typeahead = { value: prefix, time: now }
    const match = props.options.findIndex((o) =>
      o.label.toLocaleLowerCase().startsWith(prefix.toLocaleLowerCase()),
    )
    if (match >= 0) {
      event.preventDefault()
      move(match)
    }
  }
}

function handlePointerDown(event: MouseEvent): void {
  if (!rootRef.value?.contains(event.target as Node)) close()
}

function handleScroll(event: Event): void {
  // 清單自己捲動不算；外面捲動或視窗縮放時按鈕位置變了，直接收起來。
  if (listRef.value?.contains(event.target as Node)) return
  close()
}

/**
 * 只捲清單本身。scrollIntoView 會連外層（設定視窗的捲動區）一起捲，觸發上面的
 * 捲動監聽，清單一打開就被收掉。
 */
function revealFocused(): void {
  const list = listRef.value
  const option = list?.querySelector<HTMLElement>('.custom-select__option--focused')
  if (!list || !option) return
  const top = option.offsetTop
  const bottom = top + option.offsetHeight
  if (top < list.scrollTop) list.scrollTop = top
  else if (bottom > list.scrollTop + list.clientHeight) list.scrollTop = bottom - list.clientHeight
}

function stopListening(): void {
  document.removeEventListener('mousedown', handlePointerDown, true)
  window.removeEventListener('scroll', handleScroll, true)
  window.removeEventListener('resize', close)
}

watch(open, async (isOpen) => {
  if (!isOpen) {
    stopListening()
    return
  }
  document.addEventListener('mousedown', handlePointerDown, true)
  window.addEventListener('scroll', handleScroll, true)
  window.addEventListener('resize', close)
  await nextTick()
  revealFocused()
})

watch(focusedIndex, async () => {
  if (!open.value) return
  await nextTick()
  revealFocused()
})

watch(() => props.disabled, (disabled) => {
  if (disabled) close()
})

onBeforeUnmount(stopListening)
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
  gap: 0.5rem;
  width: 100%;
  min-height: 2.75rem;
  padding: 0 0.875rem;
  background-color: var(--bg-soft);
  border: 1px solid var(--line);
  border-radius: 0.5rem;
  color: var(--text);
  font: inherit;
  font-size: 0.95rem;
  font-weight: 500;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s, background-color 0.15s;
}

.custom-select__trigger:hover:not(:disabled),
.custom-select--open .custom-select__trigger {
  border-color: var(--primary);
}

.custom-select__trigger:focus-visible {
  outline: none;
  border-color: var(--primary);
  box-shadow: 0 0 0 0.1875rem color-mix(in srgb, var(--primary) 18%, transparent);
}

.custom-select__trigger:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.custom-select__value {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.custom-select__value--placeholder {
  color: var(--text-soft);
}

.custom-select__arrow {
  flex-shrink: 0;
  height: 1.1rem;
  width: auto;
  color: var(--text-soft);
  transition: transform var(--ov-dur-short, 220ms) var(--ov-ease-out, ease);
}

.custom-select--open .custom-select__arrow {
  transform: rotate(180deg);
}

.custom-select__list {
  position: fixed;
  z-index: var(--ov-z-dropdown, 100);
  max-height: 12.5rem;
  overflow-y: auto;
  padding: 0.25rem 0;
  background: var(--bg-soft);
  border: 1px solid var(--line);
  border-radius: 0.75rem;
  box-shadow:
    0 0.75rem 1.75rem color-mix(in srgb, var(--text) 14%, transparent),
    0 0.125rem 0.375rem color-mix(in srgb, var(--text) 8%, transparent);
}

.custom-select__option {
  padding: 0.5rem 0.875rem;
  color: var(--text-soft);
  font-size: 0.95rem;
  cursor: pointer;
  transition: background-color var(--ov-dur-micro, 120ms), color var(--ov-dur-micro, 120ms);
}

.custom-select__option--focused {
  background: rgb(var(--ov-color-surface-sunken));
  color: var(--text);
}

.custom-select__option--selected {
  background: color-mix(in srgb, var(--primary) 15%, transparent);
  color: var(--primary);
  font-weight: 600;
}

.custom-select__empty {
  padding: 0.5rem 0.875rem;
  color: var(--text-soft);
  font-size: 0.9rem;
}
</style>
