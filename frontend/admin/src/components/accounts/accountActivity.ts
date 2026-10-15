import type { Account } from "../../api/auth";

const RELATIVE = new Intl.RelativeTimeFormat("zh-TW", { numeric: "auto" });

const STEPS: Array<[Intl.RelativeTimeFormatUnit, number]> = [
  ["minute", 60],
  ["hour", 60 * 60],
  ["day", 24 * 60 * 60],
  ["month", 30 * 24 * 60 * 60],
  ["year", 365 * 24 * 60 * 60],
];

/** 「3 天前」「2 個月前」；清帳號時看的是量級，不需要精確到分鐘以下。 */
export function formatRelative(iso: string, now: Date = new Date()): string {
  const seconds = Math.round((new Date(iso).getTime() - now.getTime()) / 1000);
  const elapsed = Math.abs(seconds);
  if (elapsed < 60) return "剛剛";
  let unit: Intl.RelativeTimeFormatUnit = "minute";
  let size = 60;
  for (const [candidate, candidateSize] of STEPS) {
    if (elapsed < candidateSize) break;
    unit = candidate;
    size = candidateSize;
  }
  return RELATIVE.format(Math.round(seconds / size), unit);
}

export function formatFullTime(iso: string): string {
  return new Date(iso).toLocaleString("zh-TW");
}

/** 登入或 API key 使用，取較晚的那個；兩者都沒有就是 null。 */
export function lastActivityAt(account: Account): string | null {
  const times = [account.last_login_at, account.api_key_last_used_at]
    .filter((value): value is string => Boolean(value))
    .map((value) => new Date(value).getTime());
  if (times.length === 0) return null;
  return new Date(Math.max(...times)).toISOString();
}

/** 最久沒用的排前面；從沒用過的排最前，同時間再依帳號名稱。 */
export function sortByLeastRecentActivity(accounts: Account[]): Account[] {
  return [...accounts].sort((left, right) => {
    const leftAt = lastActivityAt(left);
    const rightAt = lastActivityAt(right);
    if (leftAt !== rightAt) {
      if (leftAt === null) return -1;
      if (rightAt === null) return 1;
      return new Date(leftAt).getTime() - new Date(rightAt).getTime();
    }
    return left.username.localeCompare(right.username, "zh-TW");
  });
}
