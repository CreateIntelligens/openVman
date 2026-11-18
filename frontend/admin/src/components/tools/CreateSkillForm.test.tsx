import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import CreateSkillForm from "./CreateSkillForm";
import { createSkill } from "../../api";

vi.mock("../../context/ProjectContext", () => ({
  useProject: () => ({ projectId: "test-project" }),
}));

vi.mock("../../api", () => ({
  createSkill: vi.fn(async () => ({ status: "ok" })),
}));

function openForm() {
  render(<CreateSkillForm onCreated={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: /建立技能/ }));
}

const createButton = () => screen.getByRole("button", { name: /建立$/ }) as HTMLButtonElement;
const idInput = () => screen.queryByRole("textbox", { name: "技能 ID" }) as HTMLInputElement | null;

describe("CreateSkillForm skill id", () => {
  beforeEach(() => vi.clearAllMocks());

  it("keeps the id field open after the user clears a custom id", () => {
    openForm();
    fireEvent.change(screen.getByPlaceholderText("我的技能"), { target: { value: "My Skill" } });
    fireEvent.click(screen.getByRole("button", { name: "編輯" }));
    expect(idInput()?.value).toBe("my_skill");

    fireEvent.change(idInput()!, { target: { value: "" } });

    expect(idInput()).not.toBeNull();
    expect(createButton().disabled).toBe(true);

    fireEvent.change(idInput()!, { target: { value: "weekly_report" } });
    fireEvent.click(createButton());
    expect(createSkill).toHaveBeenCalledWith("weekly_report", "My Skill", "", "test-project");
  });

  it("uses the id derived from the name when the user does not edit it", () => {
    openForm();
    fireEvent.change(screen.getByPlaceholderText("我的技能"), { target: { value: "My Skill" } });
    expect(idInput()).toBeNull();
    fireEvent.click(createButton());
    expect(createSkill).toHaveBeenCalledWith("my_skill", "My Skill", "", "test-project");
  });

  it("asks for an id when the name cannot produce one", () => {
    openForm();
    fireEvent.change(screen.getByPlaceholderText("我的技能"), { target: { value: "測試技能" } });
    expect(idInput()).not.toBeNull();
    expect(createButton().disabled).toBe(true);
    fireEvent.change(idInput()!, { target: { value: "1bad" } });
    expect(createButton().disabled).toBe(true);
    fireEvent.change(idInput()!, { target: { value: "test_skill" } });
    expect(createButton().disabled).toBe(false);
  });
});
