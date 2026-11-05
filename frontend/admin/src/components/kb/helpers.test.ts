import { describe, expect, it } from "vitest";

import {
  collectFolderPaths,
  countSearchResults,
  displayDocumentPath,
  filterTree,
  formatBatchSummary,
  runBatchSequentially,
  QUICK_QA_TREE_PATH,
  findNodeReferencingSource,
  findQaNode,
  getFileParentPaths,
  getQaNodeAncestors,
  getQaNodeParentId,
  isQaNodeDescendant,
  getSourceMeta,
  mergeQaNodesIntoTree,
  qaDropPositionAt,
  qaNodeExpandPaths,
  qaTreeNodePath,
  splitFileNameForDisplay,
  type TreeNode,
} from "./helpers";

describe("knowledge source modes", () => {
  it("still renders QA as a document source type", () => {
    expect(getSourceMeta("qa")).toMatchObject({
      icon: "quiz",
      label: "問答",
    });
  });

  it("names every source in plain words", () => {
    expect(getSourceMeta("upload").label).toBe("上傳");
    expect(getSourceMeta("web").label).toBe("貼網址");
    expect(getSourceMeta("manual").label).toBe("自己輸入");
    expect(getSourceMeta("qa").label).toBe("問答");
  });

  // 舊色票是 sky-300 這類淺色字，淺色模式底下幾乎看不到。
  it.each(["upload", "web", "manual", "qa"] as const)(
    "keeps the %s chip readable in light mode with theme tokens only",
    (sourceType) => {
      const { chipClass } = getSourceMeta(sourceType);
      expect(chipClass).toContain("text-content");
      expect(chipClass).not.toMatch(/\b(?:sky|fuchsia|amber|emerald)-\d/);
    },
  );
});

describe("displayDocumentPath", () => {
  it("drops the internal knowledge prefix", () => {
    expect(displayDocumentPath("knowledge/guides/faq.md")).toBe("guides/faq.md");
    expect(displayDocumentPath("knowledge")).toBe("");
  });

  it("only touches the prefix", () => {
    expect(displayDocumentPath("knowledge-base/faq.md")).toBe("knowledge-base/faq.md");
    expect(displayDocumentPath("guides/knowledge/faq.md")).toBe("guides/knowledge/faq.md");
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

  it("returns quick QA first and documents second, both on the first level", () => {
    const merged = mergeQaNodesIntoTree(documentTree, qaNodes);

    expect(merged.treeKind).toBe("sections");
    expect(merged.children.map((node) => node.path)).toEqual([QUICK_QA_TREE_PATH, "knowledge"]);

    const [qaRoot, documents] = merged.children;
    expect(qaRoot).toMatchObject({
      name: "快速問答",
      type: "folder",
      treeKind: "qa-root",
      virtual: true,
    });
    expect(qaRoot.children[0]).toMatchObject({
      name: "退換貨",
      path: qaTreeNodePath("returns"),
      treeKind: "qa-node",
      qaNodeId: "returns",
      virtual: true,
    });
    expect(qaRoot.children[0].children[0]).toMatchObject({
      name: "郵寄退貨",
      path: qaTreeNodePath("shipping"),
      qaNodeId: "shipping",
      qaHidden: true,
    });

    expect(documents.children.map((node) => node.path)).toEqual(["knowledge/guides"]);
  });

  it("names the documents section 文件 and keeps it a real folder that accepts drops", () => {
    const [, documents] = mergeQaNodesIntoTree(documentTree, qaNodes).children;

    expect(documents).toMatchObject({
      name: "文件",
      path: "knowledge",
      type: "folder",
      treeKind: "documents-root",
    });
    expect(documents.virtual).toBeFalsy();
  });

  it("counts only a category's own questions, and does not change while searching", () => {
    const nodes = [
      {
        node_id: "parent",
        label: "上層",
        qa_entries: [
          { question: "蘋果", source_path: "a.md", hidden: false, image_id: null },
          { question: "香蕉", source_path: "a.md", hidden: false, image_id: null },
        ],
        children: [
          {
            node_id: "child",
            label: "下層",
            qa_entries: [
              { question: "櫻桃", source_path: "b.md", hidden: false, image_id: null },
            ],
          },
        ],
      },
    ];

    const [qaRoot] = mergeQaNodesIntoTree(documentTree, nodes).children;
    expect(qaRoot.children[0].qaQuestionCount).toBe(2);
    expect(qaRoot.children[0].children[0].qaQuestionCount).toBe(1);

    const [searched] = mergeQaNodesIntoTree(documentTree, nodes, "蘋果").children;
    expect(searched.children[0].qaQuestionCount).toBe(2);
    expect(searched.children[0].children.map((row) => row.name)).toEqual(["蘋果"]);
  });

  describe("searching", () => {
    const filtered = (search: string) =>
      filterTree(documentTree, search) ?? { ...documentTree, children: [] };

    it("keeps only the sections with results", () => {
      const onlyQa = mergeQaNodesIntoTree(filtered("郵寄"), qaNodes, "郵寄");
      expect(onlyQa.children.map((node) => node.treeKind)).toEqual(["qa-root"]);

      const onlyDocuments = mergeQaNodesIntoTree(filtered("guides"), qaNodes, "guides");
      expect(onlyDocuments.children.map((node) => node.treeKind)).toEqual(["documents-root"]);
    });

    it("shows both sections when both have results", () => {
      const nodes = [{ node_id: "n", label: "guides 問答" }];
      const both = mergeQaNodesIntoTree(filtered("guides"), nodes, "guides");

      expect(both.children.map((node) => node.treeKind)).toEqual(["qa-root", "documents-root"]);
    });

    it("has no children at all when nothing matches, so the empty state can trust it", () => {
      const miss = mergeQaNodesIntoTree(filtered("not-found"), qaNodes, "not-found");

      expect(miss.children).toEqual([]);
    });

    it("does not treat the section names themselves as matches", () => {
      expect(mergeQaNodesIntoTree(filtered("快速問答"), qaNodes, "快速問答").children).toEqual([]);
      expect(mergeQaNodesIntoTree(filtered("文件"), qaNodes, "文件").children).toEqual([]);
    });

    it("does not match the hidden knowledge prefix or internal category ids", () => {
      expect(mergeQaNodesIntoTree(filtered("know"), qaNodes, "know").children).toEqual([]);
      expect(mergeQaNodesIntoTree(filtered("shipping"), qaNodes, "shipping").children).toEqual([]);
    });

    it("expands every matching folder through the sections wrapper", () => {
      const merged = mergeQaNodesIntoTree(filtered("郵寄"), qaNodes, "郵寄");

      expect(collectFolderPaths(merged)).toEqual(
        expect.arrayContaining([QUICK_QA_TREE_PATH, qaTreeNodePath("returns")]),
      );
    });

    it("counts rows with no further level as one result each", () => {
      const merged = mergeQaNodesIntoTree(filtered("郵寄"), qaNodes, "郵寄");
      expect(countSearchResults(merged)).toBe(1);

      const documents = mergeQaNodesIntoTree(filtered("intro"), qaNodes, "intro");
      expect(countSearchResults(documents)).toBe(1);

      expect(countSearchResults(mergeQaNodesIntoTree(filtered("nope"), qaNodes, "nope"))).toBe(0);
    });
  });
});

describe("splitFileNameForDisplay", () => {
  it("does not split a short name", () => {
    expect(splitFileNameForDisplay("a.md")).toEqual({ head: "a.md", tail: "" });
    expect(splitFileNameForDisplay("sixteen_chars.md")).toEqual({ head: "sixteen_chars.md", tail: "" });
  });

  it("keeps about the last twelve characters of a long name as the tail", () => {
    const name = "1-PRP自體高濃度血小板血漿注射療程說明_IMG_PRP_1.csv";
    const { head, tail } = splitFileNameForDisplay(name);

    expect(tail).toBe("MG_PRP_1.csv");
    expect(`${head}${tail}`).toBe(name);
  });

  it("counts a Chinese character as two columns, so names that only differ at the end can be told apart", () => {
    expect(splitFileNameForDisplay("展場常見問題_整理好第一版.md")).toEqual({
      head: "展場常見問題_整理",
      tail: "好第一版.md",
    });
    expect(splitFileNameForDisplay("展場常見問題_整理好第二版.md").tail).toBe("好第二版.md");
    expect(splitFileNameForDisplay("型錄說明.md")).toEqual({ head: "型錄說明.md", tail: "" });
  });

  it("never cuts a character in half", () => {
    const name = `${"報".repeat(10)}${"😀".repeat(12)}`;
    const { head, tail } = splitFileNameForDisplay(name);

    expect(head).toBe(`${"報".repeat(10)}${"😀".repeat(6)}`);
    expect(tail).toBe("😀".repeat(6));
  });
});

describe("qaDropPositionAt", () => {
  const rect = { top: 100, height: 40 };

  it.each([
    [100, "before"],
    [109, "before"],
    [110, "into"],
    [120, "into"],
    [130, "into"],
    [131, "after"],
    [140, "after"],
  ])("clientY %i is %s", (clientY, position) => {
    expect(qaDropPositionAt(clientY, rect)).toBe(position);
  });

  it("treats a row it cannot measure as moving in, so the order never changes by accident", () => {
    expect(qaDropPositionAt(100, { top: 0, height: 0 })).toBe("into");
    expect(qaDropPositionAt(Number.NaN, rect)).toBe("into");
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

  it("找得到分類實際掛的上層，最上層與不在樹上都回 null", () => {
    expect(getQaNodeParentId(nodes, "deep")).toBe("store");
    expect(getQaNodeParentId(nodes, "root")).toBeNull();
    expect(getQaNodeParentId(nodes, "missing")).toBeNull();
  });

  it("列出讓分類內容看得到要展開的路徑", () => {
    expect(qaNodeExpandPaths(nodes, "deep")).toEqual([
      QUICK_QA_TREE_PATH,
      qaTreeNodePath("root"),
      qaTreeNodePath("store"),
      qaTreeNodePath("deep"),
    ]);
    expect(qaNodeExpandPaths(nodes, null)).toEqual([QUICK_QA_TREE_PATH]);
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

describe("批次操作", () => {
  it("依序逐檔執行，遇到失敗繼續做完並記下原因", async () => {
    const order: string[] = [];
    const progress: Array<[number, number]> = [];
    const result = await runBatchSequentially(
      ["a.md", "b.md", "c.md"],
      async (path) => {
        order.push(path);
        if (path === "b.md") throw new Error("目標路徑已存在");
      },
      (done, total) => progress.push([done, total]),
    );

    expect(order).toEqual(["a.md", "b.md", "c.md"]);
    expect(result).toEqual({
      succeeded: ["a.md", "c.md"],
      failed: [{ path: "b.md", reason: "目標路徑已存在" }],
    });
    expect(progress).toEqual([[1, 3], [2, 3], [3, 3]]);
  });

  it("摘要列出失敗的檔名與原因，太多時只列前幾個", () => {
    expect(formatBatchSummary("移動", { succeeded: ["x", "y"], failed: [] })).toBe("移動完成 2 個");
    expect(
      formatBatchSummary("移動", {
        succeeded: ["knowledge/ok.md"],
        failed: [{ path: "knowledge/sub/a.md", reason: "目標路徑已存在" }],
      }, "1 個原本就在目標資料夾"),
    ).toBe("移動完成 1 個，1 個原本就在目標資料夾，1 個失敗：a.md（目標路徑已存在）");

    const failed = Array.from({ length: 7 }, (_, i) => ({ path: `f${i}.md`, reason: "錯誤" }));
    const summary = formatBatchSummary("刪除", { succeeded: [], failed });
    expect(summary.startsWith("刪除完成 0 個，7 個失敗：f0.md（錯誤）、")).toBe(true);
    expect(summary).not.toContain("f5.md");
    expect(summary.endsWith("，另有 2 個")).toBe(true);
  });
});
