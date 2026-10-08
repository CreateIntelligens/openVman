<template>
  <aside class="decision-debug" aria-label="決策判讀 Debug">
    <button class="debug-toggle" :aria-expanded="enabled" aria-controls="decision-debug-content"
      @click="$emit('toggle', !enabled)">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true">
        <path d="M8 4h8v4H8zM5 12h14v8H5zM12 8v4M3 15h2m14 0h2" />
      </svg>
      決策 Debug <span>{{ enabled ? '開' : '關' }}</span>
    </button>
    <div v-if="enabled" id="decision-debug-content" class="debug-content">
      <div class="debug-heading"><strong>這輪的機器判讀</strong><button @click="$emit('toggle', false)" aria-label="關閉決策 Debug">關閉</button></div>
      <p v-if="!report" class="debug-empty" role="status">{{ waiting ? '等待本輪決策結果…' : '送出一則訊息，就能查看供應商的判讀結果。' }}</p>
      <template v-else>
        <p class="debug-provider"><strong>{{ providerLabel }}</strong><span>{{ report.elapsed_ms.toFixed(0) }} ms</span></p>
        <p v-if="report.status !== 'available'" role="status" class="debug-notice">{{ report.status === 'fallback' ? '決策服務失效，本輪沿用原本對話規則。' : '本輪決策停用，沿用原本對話規則。' }}</p>
        <template v-else>
          <p class="debug-tone">情緒／語氣：<strong>{{ toneLabel }}</strong><span v-if="tone?.confidence != null">{{ percent(tone.confidence) }}</span></p>
          <p class="debug-caption">模型對這句話的判讀；低信心項目沿用原本規則。</p>
          <table><thead><tr><th>判讀項目</th><th>模型結果</th><th>門檻</th></tr></thead>
            <tbody><tr v-for="signal in report.signals" :key="signal.id">
              <th>{{ signalLabels[signal.id] }}</th>
              <td v-if="signal.type === 'noul'">{{ signal.resolved === true ? '是' : signal.resolved === false ? '否' : '未確定' }}<small>成立機率 {{ percent(signal.probability_true) }}</small></td>
              <td v-else>{{ labelValue(signal.value) }}<small>{{ signal.value ?? '—' }} · {{ percent(signal.confidence) }}</small></td>
              <td>{{ signal.accepted ? '是' : '棄權' }}</td>
            </tr></tbody>
          </table>
          <details><summary>實際套用的對話策略</summary><dl>
            <template v-for="item in appliedRows" :key="item.label"><dt>{{ item.label }}</dt><dd>{{ item.value }}</dd></template>
          </dl></details>
          <p v-if="report.scope === 'audio_retrieval_only'" class="debug-notice">Live 原始音訊：本輪判讀只影響後續檢索；已開始的回覆沿用 session 語言與語氣。</p>
          <p class="debug-caption">{{ report.model }} · {{ report.hop_id }}<br />只顯示最新一輪，關閉即清除。</p>
        </template>
      </template>
    </div>
  </aside>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import { labelValue, signalLabels, type DecisionDebug } from './decisionDebug'
const props = defineProps<{ enabled: boolean; report: DecisionDebug | null; waiting: boolean }>()
defineEmits<{ toggle: [enabled: boolean] }>()
const providerLabel = computed(() => ({ 'clef-primary': 'Clef 主端點', 'clef-backup': 'Clef 備援端點', jev: 'Jev', openai: 'OpenAI Decisions' }[props.report?.hop_id ?? ''] ?? props.report?.provider ?? '決策供應商'))
const tone = computed(() => props.report?.signals.find(signal => signal.id === 'tone'))
const toneLabel = computed(() => tone.value?.accepted ? labelValue(tone.value.value) : '未確定')
function percent(value: number | null | undefined) { return typeof value === 'number' && Number.isFinite(value) ? `${Math.round(value * 100)}%` : '—' }
const appliedRows = computed(() => {
  const policy = props.report?.policy ?? {}
  return [
    ['needs_knowledge', '專案知識'], ['needs_web', '網路資訊'], ['needs_memory', '記憶'],
    ['input_languages', '輸入語言'], ['retrieval_language', '檢索語言'], ['response_language', '回答語言'], ['tone', '套用語氣'],
  ].map(([key, label]) => ({ label, value: labelValue(policy[key!]) }))
})
</script>
<style scoped>
.decision-debug, .decision-debug * { box-sizing: border-box; }
.decision-debug { position: absolute; top: 1.5rem; right: 1.5rem; z-index: 15; max-width: calc(100% - 3rem); color: #f1f5f9; font-size: .8rem; }
.debug-toggle { display: flex; align-items: center; gap: .5rem; margin-left: auto; padding: .6rem .75rem; border: 1px solid #526075; border-radius: .6rem; background: #172131; color: inherit; cursor: pointer; }
.debug-toggle svg { width: 1rem; height: 1rem; }
.debug-toggle span { color: #a8d6ff; }
.debug-content { width: 360px; max-width: 100%; margin-top: .5rem; padding: 1rem; border-radius: .75rem; background: #111c2b; box-shadow: 0 8px 24px #0006; max-height: min(65vh, 480px); overflow-y: auto; }
.debug-heading, .debug-provider, .debug-tone { display: flex; justify-content: space-between; align-items: center; gap: .75rem; }
.debug-heading button { border: 0; background: transparent; color: #cbd5e1; cursor: pointer; }
.debug-provider { margin: 1rem 0 .65rem; color: #a8d6ff; }
.debug-tone { flex-wrap: wrap; margin: .65rem 0; }
.debug-caption, .debug-empty, .debug-notice { color: #cbd5e1; line-height: 1.5; }
.debug-notice { padding: .65rem; background: #263248; border-radius: .5rem; }
table { width: 100%; border-collapse: collapse; font-size: .75rem; }
th, td { text-align: left; padding: .55rem .3rem; border-bottom: 1px solid #344256; vertical-align: top; }
tbody th { font-weight: 400; } td:last-child { white-space: nowrap; } small { display: block; color: #a9bad0; margin-top: .25rem; }
summary { cursor: pointer; padding: .8rem 0; } dl { display: grid; grid-template-columns: 1fr 1fr; gap: .5rem; } dd { margin: 0; } dt { color: #cbd5e1; }
button:focus-visible, summary:focus-visible { outline: 2px solid #a8d6ff; outline-offset: 3px; }
.debug-content { scrollbar-color: #526075 #111c2b; }
@media (max-width: 640px) { .decision-debug { top: .7rem; right: .7rem; max-width: calc(100% - 1.4rem); } .debug-content { width: min(360px, calc(100vw - 3.5rem)); max-height: 45vh; } }
</style>
