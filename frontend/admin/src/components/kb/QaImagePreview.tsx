import { useEffect, useState } from "react";

import { apiUrl, getActiveProjectId } from "../../api/common";

export default function QaImagePreview({
  imageId,
  alt,
}: {
  imageId: string;
  alt: string;
}) {
  const normalizedId = imageId.trim();
  const src = normalizedId
    ? apiUrl(`/knowledge/qa/images/${encodeURIComponent(normalizedId)}`, {
      project_id: getActiveProjectId(),
    })
    : "";
  const [visible, setVisible] = useState(Boolean(src));

  useEffect(() => setVisible(Boolean(src)), [src]);

  if (!src || !visible) return null;

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
