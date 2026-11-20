export interface AnswerDiffPart {
  text: string;
  changed: boolean;
}

const MAX_DIFF_CHARACTERS = 2000;

export function diffAnswers(oldAnswer: string, newAnswer: string): [AnswerDiffPart[], AnswerDiffPart[]] {
  const plain: [AnswerDiffPart[], AnswerDiffPart[]] = [
    [{ text: oldAnswer, changed: false }],
    [{ text: newAnswer, changed: false }],
  ];
  if (
    oldAnswer === newAnswer
    || oldAnswer.length > MAX_DIFF_CHARACTERS * 2
    || newAnswer.length > MAX_DIFF_CHARACTERS * 2
  ) return plain;

  const oldChars = Array.from(oldAnswer);
  const newChars = Array.from(newAnswer);
  if (oldChars.length > MAX_DIFF_CHARACTERS || newChars.length > MAX_DIFF_CHARACTERS) return plain;

  const columns = newChars.length + 1;
  // 每格保存兩段剩餘文字的最長共同子序列長度，再沿表走回共同字元。
  const lengths = new Uint16Array((oldChars.length + 1) * columns);
  for (let oldIndex = oldChars.length - 1; oldIndex >= 0; oldIndex -= 1) {
    for (let newIndex = newChars.length - 1; newIndex >= 0; newIndex -= 1) {
      const cell = oldIndex * columns + newIndex;
      lengths[cell] = oldChars[oldIndex] === newChars[newIndex]
        ? 1 + lengths[cell + columns + 1]
        : Math.max(lengths[cell + columns], lengths[cell + 1]);
    }
  }

  const oldParts: AnswerDiffPart[] = [];
  const newParts: AnswerDiffPart[] = [];
  const append = (parts: AnswerDiffPart[], text: string, changed: boolean) => {
    const last = parts[parts.length - 1];
    if (last?.changed === changed) last.text += text;
    else parts.push({ text, changed });
  };

  let oldIndex = 0;
  let newIndex = 0;
  while (oldIndex < oldChars.length && newIndex < newChars.length) {
    const cell = oldIndex * columns + newIndex;
    if (oldChars[oldIndex] === newChars[newIndex]) {
      append(oldParts, oldChars[oldIndex++], false);
      append(newParts, newChars[newIndex++], false);
    } else if (lengths[cell + columns] >= lengths[cell + 1]) {
      append(oldParts, oldChars[oldIndex++], true);
    } else {
      append(newParts, newChars[newIndex++], true);
    }
  }
  if (oldIndex < oldChars.length) append(oldParts, oldChars.slice(oldIndex).join(""), true);
  if (newIndex < newChars.length) append(newParts, newChars.slice(newIndex).join(""), true);
  return [oldParts, newParts];
}
