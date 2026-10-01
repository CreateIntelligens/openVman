import { computed, ref } from "vue";
import { ASR_ENGINE_LABELS } from "@shared/speech";
import { fetchMyAsrProvider, setMyAsrProvider } from "../api/asr";
export function useAsrPreferences(showMessage: (message: string) => void) {
  // 這個帳號選的引擎。空字串代表沿用全站設定，那一定是伺服器引擎——瀏覽器
  // 辨識只能由使用者自己選，後端跑不了它。
  const myAsrProvider = ref("");
  // 管理者在帳號頁授權了哪些引擎。空陣列代表這個帳號不能自選，設定裡不顯示。
  const asrEngines = ref<{ id: string; label: string }[]>([]);
  // 後端說實際在用的伺服器引擎（沒選過就是部署設定的 ASR_PROVIDER）。
  const myAsrEffective = ref("");
  // 設定視窗顯示的引擎：選過而且還有授權就是選的那個，否則是實際在用的。
  const asrProviderShown = computed(() =>
    asrEngines.value.some((engine) => engine.id === myAsrProvider.value)
      ? myAsrProvider.value
      : myAsrEffective.value,
  );

  function handleAsrProviderChange(provider: string): void {
    const previous = myAsrProvider.value;
    myAsrProvider.value = provider;
    void setMyAsrProvider(provider).then((profile) => {
      myAsrEffective.value = profile.effective;
    }).catch(() => {
      // 存不起來就退回原值，不要讓畫面顯示一個其實沒生效的選擇。
      myAsrProvider.value = previous;
      showMessage("語音辨識引擎沒有存成功，已還原。");
    });
  }
  void fetchMyAsrProvider()
    .then((profile) => {
      myAsrProvider.value = profile.value;
      myAsrEffective.value = profile.effective;
      asrEngines.value = profile.allowed.map(
        (id) => ({ id, label: ASR_ENGINE_LABELS[id] ?? id }),
      );
    })
    .catch(() => { /* 讀不到就沿用伺服器引擎，不該因此不能講話。 */ });

  return { myAsrProvider, myAsrEffective, asrEngines, asrProviderShown, handleAsrProviderChange };
}
