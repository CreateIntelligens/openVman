interface WorkspaceActionsProps {
  uploading: boolean;
  syncing: boolean;
  onUpload: () => void;
  onSync: () => void;
  onCreate: () => void;
}

const ACTION_CLASS = "btn btn-ghost gap-1 px-2 py-1 text-xs";

export default function WorkspaceActions({
  uploading,
  syncing,
  onUpload,
  onSync,
  onCreate,
}: WorkspaceActionsProps) {
  return (
    <div className="flex flex-wrap items-center gap-1">
      <button type="button" onClick={onCreate} className={ACTION_CLASS}>
        <span aria-hidden="true" className="material-symbols-outlined text-[1rem]">add</span>
        新文件
      </button>
      <button type="button" onClick={onUpload} disabled={uploading} className={ACTION_CLASS}>
        <span aria-hidden="true" className="material-symbols-outlined text-[1rem]">upload_file</span>
        {uploading ? "上傳中…" : "上傳檔案"}
      </button>
      <button type="button" onClick={onSync} disabled={syncing} className={ACTION_CLASS}>
        <span aria-hidden="true" className={`material-symbols-outlined text-[1rem] ${syncing ? "animate-spin" : ""}`}>sync</span>
        {syncing ? "重建中…" : "重建搜尋資料"}
      </button>
    </div>
  );
}
