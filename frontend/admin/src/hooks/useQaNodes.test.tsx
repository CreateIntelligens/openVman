import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { fetchJsonMock } = vi.hoisted(() => ({
  fetchJsonMock: vi.fn(),
}));

vi.mock("../api/common", () => ({
  apiUrl: (path: string, params: { project_id: string }) => (
    `${path}?project_id=${params.project_id}`
  ),
  fetchJson: (...args: unknown[]) => fetchJsonMock(...args),
  getActiveProjectId: () => "default",
}));

import { type QaNode, useQaNodes } from "./useQaNodes";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => {
    resolve = next;
  });
  return { promise, resolve };
}

function node(nodeId: string, label: string): QaNode {
  return {
    node_id: nodeId,
    label,
    parent_ids: [],
    child_ids: [],
    order: 1,
    hidden: false,
    qa_entries: [],
  };
}

describe("useQaNodes project scope", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("ignores a previous project's response after switching projects", async () => {
    const fishing = deferred<QaNode[]>();
    const esg = deferred<QaNode[]>();
    fetchJsonMock.mockImplementation((url: string) => (
      url.includes("project_id=fishing") ? fishing.promise : esg.promise
    ));

    const { result, rerender } = renderHook(
      ({ projectId }) => useQaNodes(projectId),
      { initialProps: { projectId: "fishing" } },
    );

    let fishingRequest!: Promise<QaNode[]>;
    await act(async () => {
      fishingRequest = result.current.fetchTree();
      await Promise.resolve();
    });

    rerender({ projectId: "esg" });
    expect(result.current.nodesTree).toEqual([]);
    let esgRequest!: Promise<QaNode[]>;
    await act(async () => {
      esgRequest = result.current.fetchTree();
      await Promise.resolve();
    });

    esg.resolve([node("esg", "三立 ESG")]);
    await act(async () => {
      await esgRequest;
    });
    expect(result.current.nodesTree.map((item) => item.node_id)).toEqual([
      "esg",
    ]);

    fishing.resolve([node("prp", "PRP")]);
    await act(async () => {
      await fishingRequest;
    });
    expect(result.current.nodesTree.map((item) => item.node_id)).toEqual([
      "esg",
    ]);
  });
});
