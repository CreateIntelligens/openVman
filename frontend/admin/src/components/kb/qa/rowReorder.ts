import { useState, type DragEvent } from "react";

/** 把 ``from`` 那列移到 ``insertAt`` 這個插入位置（0 是最前面，length 是最後面）。 */
export function moveToInsertion<T>(list: T[], from: number, insertAt: number): T[] {
  const next = [...list];
  const [moved] = next.splice(from, 1);
  next.splice(insertAt > from ? insertAt - 1 : insertAt, 0, moved);
  return next;
}

/** ``moveToInsertion`` 要的插入位置：讓第 ``from`` 列（從 0 算）最後落在第 ``position`` 題（從 1 算）。 */
export function insertionForPosition(from: number, position: number): number {
  return position - 1 > from ? position : position - 1;
}

/** 使用者輸入的題號；中文輸入法常打出全形數字，一併接受。範圍外或不是整數回 null。 */
export function parseRowPosition(raw: string, total: number): number | null {
  const text = raw.normalize("NFKC").trim();
  if (!/^\d+$/.test(text)) return null;
  const position = Number(text);
  return position >= 1 && position <= total ? position : null;
}

function pointerInsertion(event: DragEvent<HTMLElement>, index: number): number {
  const rect = event.currentTarget.getBoundingClientRect();
  return event.clientY > rect.top + rect.height / 2 ? index + 1 : index;
}

/**
 * 列表拖曳排序。把手用 ``handleProps``、整列用 ``rowProps``：編輯器的列裡有輸入框，
 * 整列可拖會搶走選字，所以只有把手能拖。事件不往外傳，免得碰到頁面的上傳拖放。
 */
export function useRowReorder(rowCount: number, onMove: (from: number, insertAt: number) => void) {
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [insertAt, setInsertAt] = useState<number | null>(null);

  const reset = () => {
    setDragIndex(null);
    setInsertAt(null);
  };

  const handleProps = (index: number) => ({
    draggable: true,
    onDragStart: (event: DragEvent<HTMLElement>) => {
      event.stopPropagation();
      event.dataTransfer.effectAllowed = "move";
      // Firefox 沒有資料就不會開始拖曳。
      event.dataTransfer.setData("application/x-openvman-row", String(index));
      const row = event.currentTarget.closest<HTMLElement>("[data-reorder-row]");
      if (row && event.dataTransfer.setDragImage) event.dataTransfer.setDragImage(row, 16, 16);
      setDragIndex(index);
    },
    onDragEnd: reset,
  });

  const rowProps = (index: number) => ({
    "data-reorder-row": true,
    onDragOver: (event: DragEvent<HTMLElement>) => {
      if (dragIndex === null) return;
      event.preventDefault();
      event.stopPropagation();
      event.dataTransfer.dropEffect = "move";
      setInsertAt(pointerInsertion(event, index));
    },
    onDrop: (event: DragEvent<HTMLElement>) => {
      if (dragIndex === null) return;
      event.preventDefault();
      event.stopPropagation();
      const target = pointerInsertion(event, index);
      if (target !== dragIndex && target !== dragIndex + 1) onMove(dragIndex, target);
      reset();
    },
  });

  // 放回原位時不畫線：看起來會動，放下去卻沒變，反而讓人以為壞了。
  const isNoop = dragIndex === null || insertAt === null
    || insertAt === dragIndex || insertAt === dragIndex + 1;

  const dropLine = (index: number): "before" | "after" | null => {
    if (isNoop) return null;
    if (insertAt === index) return "before";
    return insertAt === rowCount && index === rowCount - 1 ? "after" : null;
  };

  return { handleProps, rowProps, dropLine, isDragging: (index: number) => dragIndex === index };
}
