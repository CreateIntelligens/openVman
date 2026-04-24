import type { PiiWarningSummary } from "../../api";

export const PRIVACY_WARNING_VISIBLE_STORAGE_KEY = "chat.privacy_warning_visible";

export const PII_LABELS: Record<string, string> = {
  private_person: "姓名",
  private_address: "地址",
  private_email: "Email",
  private_phone: "電話",
  private_url: "網址/IP",
  private_date: "日期",
  account_number: "帳號",
  secret: "密碼/金鑰",
};

export function orderedPiiCounts(warning: PiiWarningSummary): Array<[string, number]> {
  const orderedCategories = warning.categories.length > 0
    ? warning.categories
    : Object.keys(warning.counts);

  return orderedCategories
    .map((category) => [category, warning.counts[category] ?? 0] as [string, number])
    .filter(([, count]) => count > 0);
}

export function formatPiiWarningSummary(warning: PiiWarningSummary): string {
  return orderedPiiCounts(warning)
    .map(([category, count]) => `${PII_LABELS[category] ?? category} ×${count}`)
    .join("、");
}

export function hasPiiWarning(warning?: PiiWarningSummary): warning is PiiWarningSummary {
  return Boolean(warning && Object.values(warning.counts).some((c) => c > 0));
}

export function readPrivacyWarningsVisible(): boolean {
  if (typeof window === "undefined") return true;
  const raw = window.localStorage.getItem(PRIVACY_WARNING_VISIBLE_STORAGE_KEY);
  return raw == null ? true : raw !== "false";
}

export function writePrivacyWarningsVisible(visible: boolean): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(PRIVACY_WARNING_VISIBLE_STORAGE_KEY, String(visible));
}
