export const SKILL_EDITOR_TABS = ["skill.yaml", "main.py"] as const;

export type SkillEditorTab = (typeof SKILL_EDITOR_TABS)[number];

export function filesChanged(currentFiles: Record<string, string>, originalFiles: Record<string, string>): boolean {
  return Object.keys(originalFiles).some((key) => currentFiles[key] !== originalFiles[key]);
}

export function getSkillIdFromToolName(toolName: string): string {
  const colonIndex = toolName.indexOf(":");
  return colonIndex > 0 ? toolName.slice(0, colonIndex) : "";
}

export function nameToId(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
}
