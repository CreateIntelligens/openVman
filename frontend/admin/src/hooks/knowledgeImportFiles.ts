import type { DragEvent } from "react";

import type { KnowledgeUploadEntry } from "../api";

async function collectFileSystemEntries(roots: FileSystemEntry[]): Promise<KnowledgeUploadEntry[]> {
  const out: KnowledgeUploadEntry[] = [];
  const walk = async (entry: FileSystemEntry, prefix: string): Promise<void> => {
    if (entry.isFile) {
      const fileEntry = entry as FileSystemFileEntry;
      const file: File = await new Promise((resolve, reject) => fileEntry.file(resolve, reject));
      out.push({ file, relativePath: prefix ? `${prefix}/${file.name}` : file.name });
      return;
    }
    if (entry.isDirectory) {
      const dirEntry = entry as FileSystemDirectoryEntry;
      const reader = dirEntry.createReader();
      const next = prefix ? `${prefix}/${entry.name}` : entry.name;
      // readEntries returns at most 100 per call; loop until empty.
      while (true) {
        const batch: FileSystemEntry[] = await new Promise((resolve, reject) =>
          reader.readEntries(resolve, reject),
        );
        if (!batch.length) break;
        for (const child of batch) {
          await walk(child, next);
        }
      }
    }
  };
  for (const root of roots) {
    await walk(root, "");
  }
  return out;
}

export function entriesFromFiles(files: Iterable<File>): KnowledgeUploadEntry[] {
  return Array.from(files, (file) => ({
    file,
    relativePath: file.webkitRelativePath || file.name,
  }));
}

/** dataTransfer 在事件結束後就失效，取項目的部分要在第一個 await 之前做完。 */
export function collectDroppedEntries(dataTransfer: DataTransfer): Promise<KnowledgeUploadEntry[]> {
  const items = dataTransfer.items;
  if (items && items.length && typeof items[0].webkitGetAsEntry === "function") {
    const roots = Array.from(items)
      .map((item) => item.webkitGetAsEntry())
      .filter((entry): entry is FileSystemEntry => entry !== null);
    return collectFileSystemEntries(roots);
  }
  return Promise.resolve(entriesFromFiles(dataTransfer.files));
}

export function isFileDragEvent(event: DragEvent): boolean {
  return event.dataTransfer?.types?.includes("Files") ?? false;
}
