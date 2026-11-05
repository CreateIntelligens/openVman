export default function UploadDropOverlay({ targetLabel }: { targetLabel: string }) {
  return (
    <div className="fixed inset-4 z-50 flex items-center justify-center rounded-2xl border-2 border-dashed border-primary bg-primary/10 backdrop-blur-sm">
      <div className="flex items-center gap-3 rounded-xl bg-surface-raised px-6 py-4 shadow-2xl">
        <span aria-hidden="true" className="material-symbols-outlined text-3xl text-primary">
          upload_file
        </span>
        <div className="min-w-0">
          <p className="text-xl font-bold text-content">放開就開始匯入</p>
          <p className="text-sm text-content-muted">文件會放到：{targetLabel}</p>
        </div>
      </div>
    </div>
  );
}
