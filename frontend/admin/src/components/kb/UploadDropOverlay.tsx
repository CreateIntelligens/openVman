export default function UploadDropOverlay({ currentDir }: { currentDir: string }) {
  return (
    <div className="fixed inset-4 z-50 rounded-2xl border-2 border-dashed border-primary bg-primary/10 flex items-center justify-center backdrop-blur-sm">
      <div className="bg-surface-raised px-6 py-4 rounded-xl shadow-2xl flex items-center gap-3">
        <span className="material-symbols-outlined text-primary text-3xl">
          upload_file
        </span>
        <span className="text-xl font-bold text-content ">
          拖放檔案以上傳到 {currentDir}
        </span>
      </div>
    </div>
  );
}
