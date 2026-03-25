export type KBNodeStatus = "indexed" | "syncing" | "error";

export interface KBNode {
  id: string; // The full path or unique identifier
  name: string; // The display name
  type: "file" | "folder";
  status: KBNodeStatus;
  children?: KBNode[];
  size?: number;
  updatedAt?: string;
}
