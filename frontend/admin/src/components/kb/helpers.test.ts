import { describe, expect, it } from "vitest";

import {
  QUICK_QA_TREE_PATH,
  findNodeReferencingSource,
  findQaNode,
  getFileParentPaths,
  getQaNodeAncestors,
  isQaNodeDescendant,
  SOURCE_MODES,
  SOURCE_MODE_COPY,
  getSourceMeta,
  mergeQaNodesIntoTree,
  qaTreeNodePath,
  type TreeNode,
} from "./helpers";

describe("knowledge source modes", () => {
  it("keeps document source modes separate from QA authoring", () => {
    expect(SOURCE_MODES).toEqual(["upload", "web", "manual"]);
    expect(SOURCE_MODE_COPY.upload).not.toContain("題庫");
    expect(SOURCE_MODE_COPY.manual).not.toContain("Q&A");
  });

  it("still renders QA as a document source type", () => {
    expect(getSourceMeta("qa")).toMatchObject({
      icon: "quiz",
      label: "QA",
    });
  });
});

describe("QA tree merge", () => {
  const documentTree: TreeNode = {
    name: "knowledge",
    path: "knowledge",
    type: "folder",
    children: [
      {
        name: "guides",
        path: "knowledge/guides",
        type: "folder",
        children: [
          {
            name: "intro.md",
            path: "knowledge/guides/intro.md",
            type: "file",
            children: [],
          },
        ],
      },
    ],
  };

  const qaNodes = [
    {
      node_id: "returns",
      label: "退換貨",
      hidden: false,
      children: [
        {
          node_id: "shipping",
          label: "郵寄退貨",
          hidden: true,
          children: [],
        },
      ],
    },
  ];

  it("adds quick QA nodes as a virtual directory under knowledge without removing documents", () => {
    const merged = mergeQaNodesIntoTree(documentTree, qaNodes);

    expect(merged.children.map((node) => node.path)).toContain("knowledge/guides");
    expect(merged.children.map((node) => node.path)).toContain(QUICK_QA_TREE_PATH);

    const qaRoot = merged.children.find((node) => node.path === QUICK_QA_TREE_PATH);
    expect(qaRoot).toMatchObject({
      name: "快速問答",
      type: "folder",
      treeKind: "qa-root",
      virtual: true,
    });
    expect(qaRoot?.children[0]).toMatchObject({
      name: "退換貨",
      path: qaTreeNodePath("returns"),
      treeKind: "qa-node",
      qaNodeId: "returns",
      virtual: true,
    });
    expect(qaRoot?.children[0].children[0]).toMatchObject({
      name: "郵寄退貨",
      path: qaTreeNodePath("shipping"),
      qaNodeId: "shipping",
      qaHidden: true,
    });
  });

  it("filters the virtual quick QA directory by node label or id", () => {
    const match = mergeQaNodesIntoTree(
      { ...documentTree, children: [] },
      qaNodes,
      "shipping",
    );
    const qaRoot = match.children.find((node) => node.path === QUICK_QA_TREE_PATH);

    expect(qaRoot?.children[0].children[0].name).toBe("郵寄退貨");

    const miss = mergeQaNodesIntoTree(
      { ...documentTree, children: [] },
      qaNodes,
      "not-found",
    );
    expect(miss.children).toEqual([]);
  });
});

describe("QA 節點樹的走訪", () => {
  const nodes = [
    {
      node_id: "root", label: "退貨",
      qa_entries: [{ source_path: "returns.csv" }],
      children: [
        { node_id: "mail", label: "郵寄退貨", children: [] },
        { node_id: "store", label: "門市退貨", children: [
          { node_id: "deep", label: "當日退貨", children: [] },
        ] },
      ],
    },
  ] as never[];

  it("依 id 找節點，會走到最深層", () => {
    expect(findQaNode(nodes, "deep")?.label).toBe("當日退貨");
    expect(findQaNode(nodes, "missing")).toBeUndefined();
  });

  it("找得到引用某個來源檔的節點", () => {
    expect(findNodeReferencingSource(nodes, "returns.csv")?.node_id).toBe("root");
    expect(findNodeReferencingSource(nodes, "other.csv")).toBeUndefined();
  });

  it("祖先鏈不含節點自己", () => {
    expect(getQaNodeAncestors(nodes, "deep")).toEqual(["root", "store"]);
    // 根節點沒有祖先，但「找得到」與「找不到」不同：後者回 null。
    expect(getQaNodeAncestors(nodes, "root")).toEqual([]);
    expect(getQaNodeAncestors(nodes, "missing")).toBeNull();
  });

  it("自己不算自己的後代", () => {
    expect(isQaNodeDescendant(nodes[0], "deep")).toBe(true);
    expect(isQaNodeDescendant(nodes[0], "root")).toBe(false);
  });

  it("逐層列出檔案的上層目錄", () => {
    expect(getFileParentPaths("a/b/c.md")).toEqual(["a", "a/b"]);
    expect(getFileParentPaths("top.md")).toEqual([]);
  });
});
