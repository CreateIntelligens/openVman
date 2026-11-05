import { act, renderHook } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it } from "vitest";

import {
  buildTree,
  collectFolderPaths,
  mergeQaNodesIntoTree,
  QUICK_QA_TREE_PATH,
  qaTreeNodePath,
} from "../components/kb/helpers";
import { removeScoped, writeScoped } from "../utils/scopedStorage";
import type { QaNode } from "./useQaNodes";
import { useQaNodeSelection } from "./useQaNodeSelection";

const PROJECT_ID = "project-under-test";
const SELECTED_KEY = `kb-selected-qa-node-id:${PROJECT_ID}`;

function category(nodeId: string, children: QaNode[] = []): QaNode {
  return {
    node_id: nodeId,
    label: nodeId,
    parent_ids: [],
    child_ids: children.map((child) => child.node_id),
    order: 1,
    hidden: false,
    qa_entries: [],
    children,
  };
}

const NODES = [category("top", [category("middle", [category("leaf")])]), category("other")];

function renderSelection(nodesTree: QaNode[] = NODES) {
  return renderHook(() => {
    const [expanded, setExpandedDirs] = useState(new Set<string>());
    const selection = useQaNodeSelection({
      projectId: PROJECT_ID,
      nodesTree,
      qaTreeLoading: false,
      selectedPath: "knowledge",
      setExpandedDirs,
    });
    return { expanded, ...selection };
  });
}

describe("useQaNodeSelection", () => {
  afterEach(() => {
    removeScoped(SELECTED_KEY);
  });

  // 實測：路徑用的是舊的 quick_qa_tree_root，對不到任何列，巢狀分類選了也看不到。
  it("expands the rows above a restored nested category, using paths the tree really has", () => {
    writeScoped(SELECTED_KEY, "leaf");

    const { result } = renderSelection();

    expect([...result.current.expanded].sort()).toEqual(
      [QUICK_QA_TREE_PATH, qaTreeNodePath("top"), qaTreeNodePath("middle")].sort(),
    );
    const treePaths = collectFolderPaths(mergeQaNodesIntoTree(buildTree([], []), NODES));
    for (const path of result.current.expanded) {
      expect(treePaths).toContain(path);
    }
  });

  it("does not expand the selected category itself", () => {
    const { result } = renderSelection();

    act(() => result.current.setSelectedQaNodeId("middle"));

    expect(result.current.expanded.has(qaTreeNodePath("top"))).toBe(true);
    expect(result.current.expanded.has(qaTreeNodePath("middle"))).toBe(false);
  });

  it("only opens the section for a first-level category", () => {
    const { result } = renderSelection();

    act(() => result.current.setSelectedQaNodeId("other"));

    expect([...result.current.expanded]).toEqual([QUICK_QA_TREE_PATH]);
  });
});
