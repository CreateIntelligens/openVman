<template>
  <Transition name="slide-up">
    <div
      v-if="open"
      class="quick-qa-panel"
      role="dialog"
      aria-labelledby="quick-qa-title"
    >
      <div class="panel-header">
        <div class="panel-header__left">
          <button v-if="currentPath.length > 0" type="button" class="back-btn" @click="goBack" title="返回上一層">
            <svg class="back-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <line x1="19" y1="12" x2="5" y2="12"/>
              <polyline points="12 19 5 12 12 5"/>
            </svg>
            <span>返回</span>
          </button>
          <span v-else class="header-label">快速問題</span>
        </div>

        <h4 id="quick-qa-title" class="panel-title">{{ currentTitle }}</h4>

        <button type="button" class="close-btn" @click="handleClose" aria-label="關閉" title="關閉">
          <svg class="close-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <line x1="18" y1="6" x2="6" y2="18"/>
            <line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
        </button>
      </div>

      <div class="panel-body">
        <div v-if="loading" class="state-container">
          <div class="spinner"></div>
          <p>正在載入問答分類...</p>
        </div>
        <div v-else-if="error" class="state-container error-state">
          <p>{{ error }}</p>
          <button type="button" class="retry-btn" @click="fetchNodes">重新整理</button>
        </div>
        <div v-else-if="currentSubNodes.length === 0 && currentQuestions.length === 0" class="state-container empty-state">
          <p>此分類尚無問答內容</p>
        </div>

        <div v-else class="qa-grid">
          <button
            v-for="node in currentSubNodes"
            :key="node.node_id"
            type="button"
            class="qa-btn qa-btn--folder"
            @click="enterNode(node)"
          >
            <span class="qa-btn-text">{{ node.label || node.node_id }}</span>
          </button>

          <button
            v-for="(qa, idx) in currentQuestions"
            :key="idx"
            type="button"
            class="qa-btn qa-btn--question"
            @click="selectQuestion(qa.question, qa.source_path)"
          >
            <span class="qa-btn-text">{{ qa.question }}</span>
          </button>
        </div>
      </div>
    </div>
  </Transition>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";

export interface QaEntry {
  question: string;
  source_path: string;
  hidden: boolean;
  image_id: string | null;
}

export interface QaNode {
  node_id: string;
  label: string;
  parent_ids: string[];
  child_ids: string[];
  order: number;
  hidden: boolean;
  qa_entries: QaEntry[];
  children?: QaNode[];
}

export interface MergedQaItem {
  index?: string;
  q: string;
  a: string;
  img?: string;
  url?: string;
  source_file: string;
  hidden?: boolean;
}

const props = defineProps<{
  open: boolean;
  projectId: string;
}>();

const emit = defineEmits<{
  close: [];
  "select-question": [question: string, sourcePath?: string, answerText?: string];
}>();

const loading = ref(false);
const error = ref<string | null>(null);
const nodes = ref<QaNode[]>([]);

const currentPath = ref<QaNode[]>([]);
const mergedQaCache = ref<Record<string, MergedQaItem>>({});

const currentNode = computed(() => {
  if (currentPath.value.length === 0) return null;
  return currentPath.value[currentPath.value.length - 1];
});

const currentSubNodes = computed(() => {
  if (!currentNode.value) return nodes.value;
  return currentNode.value.children ?? [];
});

const currentQuestions = computed(() => {
  if (!currentNode.value) return [];
  return (currentNode.value.qa_entries ?? []).filter(entry => !entry.hidden);
});

const currentTitle = computed(() => {
  if (!currentNode.value) return "分類選單";
  return currentNode.value.label || currentNode.value.node_id;
});

function enterNode(node: QaNode): void {
  currentPath.value.push(node);
}

function goBack(): void {
  currentPath.value.pop();
}

function resetNavigation(): void {
  currentPath.value = [];
}

function handleClose(): void {
  emit("close");
}

function selectQuestion(question: string, sourcePath?: string): void {
  const cached = mergedQaCache.value[question];
  const answerText = cached?.a || "";
  emit("select-question", question, sourcePath, answerText);
  emit("close");
}

function getErrorMessage(err: unknown): string {
  return err instanceof Error && err.message
    ? err.message
    : "載入問答分類失敗";
}

async function fetchNodes(): Promise<void> {
  if (!props.projectId) return;
  loading.value = true;
  error.value = null;
  try {
    const res = await fetch(`/api/knowledge/qa/nodes?project_id=${encodeURIComponent(props.projectId)}`);
    if (!res.ok) throw new Error("無法取得問答分類");
    const data = await res.json();
    nodes.value = data ?? [];
  } catch (err) {
    error.value = getErrorMessage(err);
    nodes.value = [];
  } finally {
    loading.value = false;
  }
}

watch(
  () => props.projectId,
  () => {
    resetNavigation();
    if (props.open) {
      void fetchNodes();
    }
  }
);

watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) {
      if (nodes.value.length === 0) {
        void fetchNodes();
      }
    } else {
      setTimeout(() => {
        resetNavigation();
      }, 300);
    }
  }
);

watch(currentNode, async (newNode) => {
  if (!newNode) return;
  try {
    const res = await fetch(`/api/knowledge/qa/nodes/${encodeURIComponent(newNode.node_id)}/merged?project_id=${encodeURIComponent(props.projectId)}`);
    if (res.ok) {
      const items = await res.json() as MergedQaItem[];
      for (const item of items) {
        mergedQaCache.value[item.q] = item;
      }
    }
  } catch (err) {
    console.warn("Failed to prefetch merged QA items:", err);
  }
}, { immediate: true });

onMounted(() => {
  if (props.open) {
    void fetchNodes();
  }
});
</script>

<style scoped>
.quick-qa-panel {
  position: absolute;
  left: 1.25rem;
  right: 1.25rem;
  bottom: 1.25rem;
  height: 62%;
  background: var(--bg-soft);
  backdrop-filter: blur(1.5rem);
  -webkit-backdrop-filter: blur(1.5rem);
  border: var(--hairline) solid var(--line);
  border-radius: 1.5rem;
  z-index: 100;
  display: flex;
  flex-direction: column;
  box-shadow: 0 0.625rem 1.875rem rgba(0, 0, 0, 0.08);
  overflow: hidden;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1.1rem 1.5rem;
  border-bottom: var(--hairline) solid var(--line);
  flex-shrink: 0;
}

.panel-header__left {
  display: flex;
  align-items: center;
  min-width: 5rem;
}

.back-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  background: var(--bg);
  border: var(--hairline) solid var(--line);
  color: var(--text-soft);
  padding: 0.35rem 0.75rem;
  border-radius: 0.5rem;
  font-size: 0.85rem;
  font-weight: 600;
  cursor: pointer;
  transition:
    background-color var(--ov-dur-micro) var(--ov-ease-out),
    border-color var(--ov-dur-micro) var(--ov-ease-out),
    color var(--ov-dur-micro) var(--ov-ease-out);
  min-height: 2.75rem;
}

.back-btn:hover {
  background: var(--bg-soft);
  border-color: var(--primary);
  color: var(--primary);
}

.back-icon {
  width: 1rem;
  height: 1rem;
}

.header-label {
  color: var(--text-soft);
  font-weight: 700;
  font-size: 0.95rem;
}

.panel-title {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 700;
  color: var(--text);
  text-align: center;
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  padding: 0 0.5rem;
}

.close-btn {
  background: transparent;
  border: none;
  color: var(--text-soft);
  opacity: 0.7;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0.35rem;
  border-radius: 0.5rem;
  transition:
    background-color var(--ov-dur-micro) var(--ov-ease-out),
    color var(--ov-dur-micro) var(--ov-ease-out),
    opacity var(--ov-dur-micro) var(--ov-ease-out);
  min-width: 2.75rem;
  min-height: 2.75rem;
}

.close-icon {
  width: 1.125rem;
  height: 1.125rem;
}

.close-btn:hover {
  background: var(--bg-soft);
  color: var(--text);
  opacity: 1;
}

.panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 1.25rem 1.5rem;
}

.state-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 4rem 1rem;
  text-align: center;
  color: var(--text-soft);
  gap: 0.75rem;
  font-weight: 500;
}

.spinner {
  width: 2rem;
  height: 2rem;
  border: 0.1875rem solid var(--line);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

.error-state {
  color: #ef4444;
}

.retry-btn {
  background: var(--primary);
  color: white;
  border: none;
  padding: 0.5rem 1.25rem;
  border-radius: 0.5rem;
  font-size: 0.85rem;
  font-weight: 600;
  cursor: pointer;
  margin-top: 0.5rem;
  min-height: 2.75rem;
  box-shadow: 0 0.125rem 0.375rem rgba(0, 0, 0, 0.05);
}

.empty-icon {
  opacity: 0.6;
}

.qa-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 18rem), 1fr));
  gap: 0.85rem;
}

.qa-btn {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 1rem 1.25rem;
  background: var(--bg);
  border: var(--hairline) solid var(--line);
  color: var(--text);
  font-size: 0.95rem;
  font-weight: 700;
  border-radius: 0.75rem;
  cursor: pointer;
  transition:
    background-color var(--ov-dur-short) var(--ov-ease-out),
    border-color var(--ov-dur-short) var(--ov-ease-out),
    color var(--ov-dur-short) var(--ov-ease-out);
  line-height: 1.4;
  gap: 0.75rem;
}

.qa-btn:hover {
  background: var(--bg-soft);
  border-color: var(--primary);
  color: var(--primary);
}

.qa-btn:active {
  transform: translateY(0);
}

.qa-btn--question {
  background: var(--bg);
  border-color: var(--line);
  color: var(--text);
}

.qa-btn--question:hover {
  background: var(--bg-soft);
  border-color: var(--primary);
  color: var(--primary);
  box-shadow: 0 0.25rem 0.75rem rgba(0, 0, 0, 0.05);
}
.slide-up-enter-active,
.slide-up-leave-active {
  transition: transform 0.35s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.3s ease;
}

.slide-up-enter-from,
.slide-up-leave-to {
  transform: translateY(105%);
  opacity: 0.9;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.app-shell.immersive .quick-qa-panel {
  background: rgba(15, 23, 42, 0.72);
  border-color: rgba(255, 255, 255, 0.12);
  box-shadow: 0 0.9375rem 2.5rem rgba(0, 0, 0, 0.4);
}

.app-shell.immersive .panel-header {
  border-bottom-color: rgba(255, 255, 255, 0.08);
}

.app-shell.immersive .panel-title {
  color: #fff;
}

.app-shell.immersive .header-label {
  color: rgba(255, 255, 255, 0.6);
}

.app-shell.immersive .back-btn {
  background: rgba(255, 255, 255, 0.05);
  border-color: rgba(255, 255, 255, 0.15);
  color: rgba(255, 255, 255, 0.85);
}

.app-shell.immersive .back-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  border-color: var(--primary);
  color: #fff;
}

.app-shell.immersive .close-btn {
  color: rgba(255, 255, 255, 0.7);
}

.app-shell.immersive .close-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  color: #fff;
}

.app-shell.immersive .qa-btn {
  background: rgba(255, 255, 255, 0.04);
  border-color: rgba(255, 255, 255, 0.10);
  color: rgba(255, 255, 255, 0.85);
}

.app-shell.immersive .qa-btn:hover {
  background: rgba(255, 255, 255, 0.08);
  border-color: var(--primary);
  color: #ffffff;
  box-shadow: 0 0.25rem 0.75rem rgba(0, 0, 0, 0.25);
}

.app-shell.immersive .qa-btn--question {
  background: rgba(255, 255, 255, 0.04);
  border-color: rgba(255, 255, 255, 0.15);
  color: rgba(255, 255, 255, 0.85);
}

.app-shell.immersive .qa-btn--question:hover {
  background: rgba(255, 255, 255, 0.08);
  border-color: var(--primary);
  color: #fff;
  box-shadow: 0 0.25rem 0.75rem rgba(0, 0, 0, 0.25);
}
</style>
