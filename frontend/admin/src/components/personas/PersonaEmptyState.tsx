export default function PersonaEmptyState() {
  return (
    <div className="flex-1 flex items-center justify-center p-12">
      <div className="max-w-sm text-center">
        <div className="w-16 h-16 rounded-xl bg-surface-sunken dark:bg-surface-sunken/50 border border-border flex items-center justify-center text-content-subtle mx-auto mb-6">
          <span className="material-symbols-outlined text-[2rem]">groups</span>
        </div>
        <h3 className="text-xl font-semibold text-content mb-2">未選擇角色</h3>
        <p className="text-[0.8125rem] text-content-subtle leading-relaxed">
          從左側欄選擇要編輯的角色，或建立新角色進行實驗。
        </p>
      </div>
    </div>
  );
}
