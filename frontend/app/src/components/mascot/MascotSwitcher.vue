<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue"
import type { MascotOption } from "../../data/mascotCatalog"

const props = defineProps<{
  mascots: MascotOption[]
  currentMascotId: string
  disabled?: boolean
}>()

const emit = defineEmits<{
  mascotChange: [mascotId: string]
}>()

const open = ref(false)

const currentMascot = computed(() =>
  props.mascots.find((mascot) => mascot.id === props.currentMascotId)
    ?? props.mascots[0]
    ?? null
)

function toggle(): void {
  if (props.disabled) return
  open.value = !open.value
}

function selectMascot(mascotId: string): void {
  emit("mascotChange", mascotId)
  open.value = false
}

function handleKeydown(event: KeyboardEvent): void {
  if (event.key === "Escape") open.value = false
}

onMounted(() => window.addEventListener("keydown", handleKeydown))
onUnmounted(() => window.removeEventListener("keydown", handleKeydown))
</script>

<template>
  <div class="mascot-switcher" :class="{ 'mascot-switcher--open': open }">
    <button
      type="button"
      class="mascot-switcher__trigger"
      :disabled="disabled"
      :aria-expanded="open"
      aria-label="切換小助理"
      title="切換小助理"
      @click.stop="toggle"
    >
      <span
        class="mascot-switcher__mark"
        :class="`mascot-switcher__mark--${currentMascot?.engine ?? '2d'}`"
        aria-hidden="true"
      />
      <span class="mascot-switcher__label">{{ currentMascot?.label ?? "小助理" }}</span>
    </button>

    <Transition name="mascot-menu">
      <div
        v-if="open"
        class="mascot-switcher__menu"
        role="listbox"
        aria-label="小助理角色"
      >
        <button
          v-for="mascot in mascots"
          :key="mascot.id"
          type="button"
          class="mascot-switcher__option"
          :class="{ 'mascot-switcher__option--active': mascot.id === currentMascotId }"
          :aria-selected="mascot.id === currentMascotId"
          role="option"
          @click.stop="selectMascot(mascot.id)"
        >
          <span
            class="mascot-switcher__preview"
            :class="`mascot-switcher__preview--${mascot.engine}`"
            aria-hidden="true"
          />
          <span class="mascot-switcher__option-text">
            <strong>{{ mascot.label }}</strong>
            <small>{{ mascot.engine.toUpperCase() }}</small>
          </span>
        </button>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.mascot-switcher {
  position: absolute;
  top: 0.5rem;
  left: 0.5rem;
  z-index: 3;
  width: min(13rem, calc(100% - 1rem));
  pointer-events: auto;
}

.mascot-switcher__trigger {
  display: inline-flex;
  align-items: center;
  max-width: 100%;
  min-height: 2.25rem;
  gap: 0.5rem;
  padding: 0.35rem 0.65rem;
  border: var(--hairline) solid rgba(255, 255, 255, 0.3);
  border-radius: 0.5rem;
  background: rgba(15, 23, 42, 0.64);
  color: #fff;
  box-shadow: 0 0.5rem 1.5rem rgba(15, 23, 42, 0.22);
  backdrop-filter: blur(0.75rem);
  -webkit-backdrop-filter: blur(0.75rem);
  cursor: pointer;
}

.mascot-switcher__trigger:hover:not(:disabled),
.mascot-switcher--open .mascot-switcher__trigger {
  background: rgba(15, 23, 42, 0.78);
  border-color: rgba(255, 255, 255, 0.46);
}

.mascot-switcher__trigger:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.mascot-switcher__mark {
  width: 0.75rem;
  aspect-ratio: 1;
  flex: none;
  border-radius: 999rem;
  box-shadow: 0 0 0 0.1875rem rgba(255, 255, 255, 0.14);
}

.mascot-switcher__mark--2d {
  background: #38bdf8;
}

.mascot-switcher__mark--3d {
  background: #34d399;
}

.mascot-switcher__label {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.82rem;
  font-weight: 700;
}

.mascot-switcher__menu {
  margin-top: 0.5rem;
  display: grid;
  gap: 0.45rem;
  padding: 0.5rem;
  border: var(--hairline) solid rgba(255, 255, 255, 0.3);
  border-radius: 0.5rem;
  background: rgba(248, 250, 252, 0.94);
  box-shadow: 0 1rem 2rem rgba(15, 23, 42, 0.24);
  backdrop-filter: blur(0.75rem);
  -webkit-backdrop-filter: blur(0.75rem);
}

.mascot-switcher__option {
  display: grid;
  grid-template-columns: 2.25rem minmax(0, 1fr);
  align-items: center;
  gap: 0.6rem;
  min-width: 0;
  padding: 0.45rem;
  border: var(--hairline) solid transparent;
  border-radius: 0.5rem;
  background: transparent;
  color: #0f172a;
  cursor: pointer;
  text-align: left;
}

.mascot-switcher__option:hover,
.mascot-switcher__option--active {
  border-color: rgba(14, 165, 233, 0.34);
  background: rgba(14, 165, 233, 0.1);
}

.mascot-switcher__preview {
  aspect-ratio: 1;
  border-radius: 0.5rem;
  border: var(--hairline) solid rgba(15, 23, 42, 0.12);
}

.mascot-switcher__preview--2d {
  background:
    radial-gradient(circle at 50% 34%, #fef3c7 0 20%, transparent 21%),
    radial-gradient(circle at 50% 72%, #38bdf8 0 34%, transparent 35%),
    linear-gradient(160deg, #eff6ff, #dbeafe);
}

.mascot-switcher__preview--3d {
  background:
    radial-gradient(circle at 50% 35%, #ecfccb 0 20%, transparent 21%),
    conic-gradient(from 160deg, #34d399, #22c55e, #0f766e, #34d399);
}

.mascot-switcher__option-text {
  display: flex;
  min-width: 0;
  flex-direction: column;
  line-height: 1.15;
}

.mascot-switcher__option-text strong,
.mascot-switcher__option-text small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mascot-switcher__option-text strong {
  font-size: 0.86rem;
}

.mascot-switcher__option-text small {
  margin-top: 0.15rem;
  color: #64748b;
  font-size: 0.68rem;
  font-weight: 700;
}

.mascot-menu-enter-active,
.mascot-menu-leave-active {
  transition: opacity 0.14s ease, transform 0.14s ease;
}

.mascot-menu-enter-from,
.mascot-menu-leave-to {
  opacity: 0;
  transform: translateY(-0.25rem);
}
</style>
