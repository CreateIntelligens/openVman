import { useEffect, useState } from "react";

import { DEFAULT_UPLOAD_LIMITS, fetchUploadLimits, type UploadLimits } from "../api/uploadLimits";

/** Upload limits for hint text; falls back to the backend defaults until loaded. */
export function useUploadLimits(): UploadLimits {
  const [limits, setLimits] = useState<UploadLimits>(DEFAULT_UPLOAD_LIMITS);
  useEffect(() => {
    let alive = true;
    fetchUploadLimits()
      .then((loaded) => {
        if (alive) setLimits(loaded);
      })
      .catch(() => {
        // 提示文字用預設值即可；真正的檢查在送出時與伺服器端。
      });
    return () => {
      alive = false;
    };
  }, []);
  return limits;
}
