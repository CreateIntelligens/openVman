/**
 * 錯字率：以字為單位的編輯距離 ÷ 參考文字長度。
 *
 * 跟 scripts/voice_e2e/run.py 的 cer() 同一個算法，數字才能互相對照：NFKC、轉小寫、
 * 異體字視為同字、只留字母與數字。「DIVA」對「diva」、「汙水泵」對「污水泵」都不算錯。
 */
const VARIANTS: Record<string, string> = { 汙: "污", 臺: "台", 裏: "裡", 着: "著" };

function normalize(text: string): string[] {
  return Array.from(text.normalize("NFKC").toLowerCase())
    .map((char) => VARIANTS[char] ?? char)
    .filter((char) => /[\p{L}\p{N}]/u.test(char));
}

export function charErrorRate(reference: string, hypothesis: string): number {
  const ref = normalize(reference);
  const hyp = normalize(hypothesis);
  if (!ref.length) return hyp.length ? 1 : 0;
  let previous = Array.from({ length: hyp.length + 1 }, (_, index) => index);
  for (let i = 1; i <= ref.length; i++) {
    const current = [i];
    for (let j = 1; j <= hyp.length; j++) {
      current[j] = Math.min(
        previous[j] + 1,
        current[j - 1] + 1,
        previous[j - 1] + (ref[i - 1] === hyp[j - 1] ? 0 : 1),
      );
    }
    previous = current;
  }
  return previous[hyp.length] / ref.length;
}
