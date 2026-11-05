import { useEffect, useRef, useState, type ChangeEvent } from "react";

import { useQaNodes } from "../../../hooks/useQaNodes";
import { errorMessage } from "../../../utils/errorMessage";

interface UseQaImageUploadOptions {
  /** 上傳要一段時間，這期間列可能被移動或刪掉，所以用列的 id 找，不能用位置。 */
  onUploaded: (rowId: string, imageId: string) => void;
  onError: (message: string) => void;
}

/** 問答清單的「上傳圖片」：整張清單共用一個隱藏的檔案欄位。 */
export function useQaImageUpload({ onUploaded, onError }: UseQaImageUploadOptions) {
  const { uploadImage } = useQaNodes();
  const [uploadingRowId, setUploadingRowId] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const pendingRowIdRef = useRef<string | null>(null);
  const mountedRef = useRef(true);
  // 上傳完才呼叫，要拿最新的清單，不能用開始上傳那時候的 closure。
  const callbacksRef = useRef({ onUploaded, onError });
  callbacksRef.current = { onUploaded, onError };

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const pickImage = (rowId: string) => {
    pendingRowIdRef.current = rowId;
    inputRef.current?.click();
  };

  const handleFileChange = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    const rowId = pendingRowIdRef.current;
    // 清掉才選得了同一個檔案第二次。
    event.target.value = "";
    pendingRowIdRef.current = null;
    if (!file || rowId === null) return;

    setUploadingRowId(rowId);
    try {
      const { image_id: imageId } = await uploadImage(file);
      if (mountedRef.current) callbacksRef.current.onUploaded(rowId, imageId);
    } catch (error: unknown) {
      if (mountedRef.current) {
        callbacksRef.current.onError(errorMessage(error, "圖片上傳失敗，請換一張圖或稍後再試。"));
      }
    } finally {
      if (mountedRef.current) setUploadingRowId(null);
    }
  };

  return {
    uploadingRowId,
    pickImage,
    fileInputProps: {
      ref: inputRef,
      type: "file" as const,
      accept: "image/*",
      className: "hidden",
      onChange: handleFileChange,
    },
  };
}
