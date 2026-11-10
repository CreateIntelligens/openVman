import { useState } from "react";

import PromptModal from "../../PromptModal";
import { parseRowPosition } from "./rowReorder";

interface QaMoveToModalProps {
  /** 目前是第幾題（從 1 算起）。 */
  rowNumber: number;
  total: number;
  onMove: (position: number) => void;
  onClose: () => void;
}

export default function QaMoveToModal({ rowNumber, total, onMove, onClose }: QaMoveToModalProps) {
  const [invalid, setInvalid] = useState(false);

  return (
    <PromptModal
      open
      title={`把第 ${rowNumber} 題移到…`}
      submitLabel="移動"
      fields={[{
        key: "position",
        label: "移到第幾題",
        placeholder: `1 到 ${total}`,
        required: true,
        hint: invalid
          ? `請輸入 1 到 ${total} 的數字。`
          : `目前是第 ${rowNumber} 題，共 ${total} 題。移動後記得按「儲存」。`,
      }]}
      onSubmit={(values) => {
        const position = parseRowPosition(values.position, total);
        if (position === null) {
          setInvalid(true);
          return;
        }
        onMove(position);
      }}
      onCancel={onClose}
    />
  );
}
