import { useEffect, useState } from "react";

import { apiUrl, getActiveProjectId } from "../../api/common";
import type { Citation } from "../../api/chat";

interface ChatMediaProps {
  citations?: Citation[];
  imageId?: string;
  url?: string;
}

function safeHttpUrl(value: string | undefined): string | null {
  if (!value) return null;

  try {
    const parsed = new URL(value);
    return parsed.protocol === "http:" || parsed.protocol === "https:"
      ? parsed.href
      : null;
  } catch {
    return null;
  }
}

export default function ChatMedia({
  citations,
  imageId,
  url,
}: ChatMediaProps) {
  const primaryCitation = citations?.[0];
  const citationImageId = primaryCitation?.image_id || primaryCitation?.image;
  const citationUrl = primaryCitation?.url || primaryCitation?.source_url;
  const resolvedImageId = (imageId || citationImageId || "").trim();
  const resolvedUrl = safeHttpUrl(url || citationUrl);

  const imageSrc = resolvedImageId
    ? apiUrl(`/knowledge/qa/images/${encodeURIComponent(resolvedImageId)}`, {
      project_id: getActiveProjectId(),
    })
    : null;
  const [showImage, setShowImage] = useState(Boolean(imageSrc));

  useEffect(() => {
    setShowImage(Boolean(imageSrc));
  }, [imageSrc]);

  if (!resolvedImageId && !resolvedUrl) return null;

  return (
    <section className="mt-4 space-y-3" aria-label="回覆參考媒體">
      {imageSrc && showImage && (
        <img
          src={imageSrc}
          alt={primaryCitation?.title || "回覆參考圖片"}
          className="max-h-[55dvh] w-auto max-w-full rounded-xl border border-slate-200 object-contain dark:border-slate-700"
          loading="lazy"
          decoding="async"
          onError={() => setShowImage(false)}
        />
      )}
      {resolvedUrl && (
        <a
          href={resolvedUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex max-w-full items-center rounded-lg border border-primary/20 bg-primary/5 px-3 py-2 text-sm font-medium text-primary transition-colors hover:bg-primary/10"
        >
          開啟相關連結
        </a>
      )}
    </section>
  );
}
