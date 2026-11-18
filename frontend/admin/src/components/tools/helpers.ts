export const SKILL_EDITOR_TABS = ["skill.yaml", "main.py"] as const;

export type SkillEditorTab = (typeof SKILL_EDITOR_TABS)[number];

export function filesChanged(currentFiles: Record<string, string>, originalFiles: Record<string, string>): boolean {
  const fileNames = new Set([
    ...Object.keys(originalFiles),
    ...Object.keys(currentFiles),
  ]);
  return [...fileNames].some((key) => currentFiles[key] !== originalFiles[key]);
}

/** Brain 不接受經由 API 改寫的檔案；main.py 會被載入 Brain 執行，只能在伺服器上改。 */
export function isLockedSkillFile(fileName: string): boolean {
  return fileName === "main.py";
}

export function changedFiles(
  currentFiles: Record<string, string>,
  originalFiles: Record<string, string>,
): Record<string, string> {
  return Object.fromEntries(
    Object.entries(currentFiles).filter(
      ([name, content]) => !isLockedSkillFile(name) && content !== originalFiles[name],
    ),
  );
}

export function getSkillIdFromToolName(toolName: string): string {
  const colonIndex = toolName.indexOf(":");
  return colonIndex > 0 ? toolName.slice(0, colonIndex) : "";
}

// 與 Brain／Backend 相同：技能 ID 會變成目錄與 Python 函式名稱。
const SKILL_ID_PATTERN = /^[A-Za-z_][A-Za-z0-9_]{0,63}$/;

export function isValidSkillId(skillId: string): boolean {
  return SKILL_ID_PATTERN.test(skillId);
}

export function nameToId(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
}
