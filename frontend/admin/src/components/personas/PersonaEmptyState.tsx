export default function PersonaEmptyState() {
  return (
    <div className="flex-1 flex items-center justify-center p-12">
      <div className="max-w-sm text-center">
        <div className="w-16 h-16 rounded-xl bg-slate-100 dark:bg-slate-900/50 border border-slate-200 dark:border-slate-700 flex items-center justify-center text-slate-500 mx-auto mb-6">
          <span className="material-symbols-outlined text-[32px]">groups</span>
        </div>
        <h3 className="text-xl font-semibold text-slate-800 dark:text-slate-200 mb-2">未選擇角色</h3>
        <p className="text-[13px] text-slate-500 leading-relaxed">
          從左側欄選擇要編輯的角色，或建立新角色進行實驗。
        </p>
      </div>
    </div>
  );
}
