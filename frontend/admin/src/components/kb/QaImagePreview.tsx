import { useEffect, useState } from "react";

import { apiUrl, getActiveProjectId } from "../../api/common";

export default function QaImagePreview({
  imageId,
  alt,
  compact = false,
}: {
  imageId: string;
  alt: string;
  /** 列表裡的縮圖：點開才看大圖，不佔列表高度。 */
  compact?: boolean;
}) {
  const normalizedId = imageId.trim();
  const src = normalizedId
    ? apiUrl(`/knowledge/qa/images/${encodeURIComponent(normalizedId)}`, {
      project_id: getActiveProjectId(),
    })
    : "";
  const [visible, setVisible] = useState(Boolean(src));

  useEffect(() => setVisible(Boolean(src)), [src]);

  if (!src) return null;

  if (!visible) {
    // 編號打錯時要講出來，不然看起來只是沒有縮圖，存了才發現訪客看不到圖。
    return compact ? <span className="shrink-0 text-xs text-danger">找不到這張圖</span> : null;
  }

  // 白底是刻意的：去背的圖（QR code、型錄）放在深色底上會看不見。
  if (compact) {
    return (
      <a href={src} target="_blank" rel="noopener noreferrer" className="shrink-0" aria-label="開啟原圖">
        <img
          src={src}
          alt={alt}
          loading="lazy"
          decoding="async"
          onError={() => setVisible(false)}
          className="h-10 w-auto max-w-[5rem] rounded border border-border bg-white object-contain"
        />
      </a>
    );
  }

  return (
    <img
      src={src}
      alt={alt}
      loading="lazy"
      decoding="async"
      onError={() => setVisible(false)}
      className="max-h-48 w-auto max-w-full rounded-lg border border-border bg-white object-contain "
    />
  );
}
