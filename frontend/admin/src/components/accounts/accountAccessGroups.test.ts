import { describe, expect, it } from "vitest";

import {
  GLOBAL_SECTION_LABEL,
  ORPHAN_SECTION_LABEL,
  groupAccessOptions,
} from "./accountAccessGroups";

const projects = [
  { id: "esg-1", label: "ESG永續" },
  { id: "aws-1", label: "AWS-dev" },
];

describe("groupAccessOptions", () => {
  it("人物：全域最前、專案依名稱排序、孤兒最後，專案名稱取自專案清單", () => {
    const sections = groupAccessOptions(
      "avatar_characters",
      [
        { id: "1014", label: "AWS 初階", visibility: "project", owner_project_id: "aws-1" },
        { id: "old", label: "舊角色", visibility: "project", owner_project_id: null },
        { id: "0713", label: "雀斑", visibility: "project", owner_project_id: "esg-1" },
        { id: "000", label: "000", visibility: "global" },
        { id: "zzz", label: "不在清單的專案", visibility: "project", owner_project_id: "proj-x" },
      ],
      projects,
    );
    expect(sections.map((section) => section.label)).toEqual([
      GLOBAL_SECTION_LABEL,
      "專案專屬：AWS-dev",
      "專案專屬：ESG永續",
      "專案專屬：proj-x",
      ORPHAN_SECTION_LABEL,
    ]);
    expect(sections[1].options.map((option) => option.id)).toEqual(["1014"]);
    expect(sections[4].options.map((option) => option.id)).toEqual(["old"]);
  });

  it("聲音：依引擎分組並用顯示名稱排序", () => {
    const sections = groupAccessOptions("custom_voices", [
      { id: "hayley", label: "Hayley", provider: "indextts" },
      { id: "Fenrir", label: "Fenrir", provider: "gemini-tts" },
      { id: "young-female-02", label: "Hayley", provider: "cosyvoice" },
    ]);
    expect(sections.map((section) => section.label)).toEqual([
      "CosyVoice",
      "Gemini TTS",
      "IndexTTS",
    ]);
  });

  it("只有一個區段時不加標題；專案與辨識引擎一律單一區段", () => {
    expect(
      groupAccessOptions("custom_voices", [{ id: "a", label: "A", provider: "indextts" }]),
    ).toEqual([{ key: "indextts", label: "", options: [{ id: "a", label: "A", provider: "indextts" }] }]);
    const flat = groupAccessOptions("asr_engines", [
      { id: "breeze", label: "Breeze" },
      { id: "r2t2", label: "R2T2" },
    ]);
    expect(flat).toHaveLength(1);
    expect(flat[0].label).toBe("");
  });
});
