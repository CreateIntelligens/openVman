import { ref, watch } from "vue";
import { apiFetch } from "../api/http";
import { suggestedQuestions, type SuggestedQuestion } from "../components/controls/quickQaText";

/** 專案快速問答的推薦題；讀不到就是空的，畫面不顯示那一排，不擋對話。 */
export function useSuggestedQuestions(projectId: () => string) {
  const suggestions = ref<SuggestedQuestion[]>([]);

  watch(projectId, async (id) => {
    suggestions.value = [];
    if (!id) return;
    try {
      const res = await apiFetch(`/api/v1/knowledge/qa/nodes?project_id=${encodeURIComponent(id)}`);
      if (!res.ok) return;
      const nodes = await res.json();
      // 讀的時候換了專案，舊專案的題目不能蓋上去。
      if (id !== projectId()) return;
      suggestions.value = suggestedQuestions(nodes);
    } catch {
      suggestions.value = [];
    }
  }, { immediate: true });

  return { suggestions };
}
