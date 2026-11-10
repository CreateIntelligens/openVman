/**
 * 人物、背景、角色的代號會當資料夾名稱，只收英數字；工作人員多半只想取中文名，
 * 留空時由這裡產生，兩個同名素材也不會撞在一起。
 */
export function generateAssetId(prefix: string): string {
  const random = Math.random().toString(36).slice(2, 6);
  return `${prefix}-${Date.now().toString(36)}${random}`;
}
