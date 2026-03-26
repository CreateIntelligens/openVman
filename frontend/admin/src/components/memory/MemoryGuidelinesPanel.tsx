export default function MemoryGuidelinesPanel() {
  return (
    <div className="bg-slate-800/50 rounded-xl p-6 border border-slate-700">
      <h3 className="text-white font-bold mb-4 flex items-center gap-2">
        <span className="material-symbols-outlined text-primary">info</span>
        記憶指南
      </h3>
      <ul className="space-y-4 text-sm text-slate-400">
        <li className="flex gap-3">
          <span className="material-symbols-outlined text-xs text-primary mt-1">circle</span>
          <span>使用清晰、客觀的語句，避免模糊不清。</span>
        </li>
        <li className="flex gap-3">
          <span className="material-symbols-outlined text-xs text-primary mt-1">circle</span>
          <span>「來源」有助於在資訊衝突時判定優先順序。</span>
        </li>
        <li className="flex gap-3">
          <span className="material-symbols-outlined text-xs text-primary mt-1">circle</span>
          <span>較長的文字區塊會自動分段處理。</span>
        </li>
      </ul>
    </div>
  );
}
