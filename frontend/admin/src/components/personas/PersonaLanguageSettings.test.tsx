import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import PersonaLanguageSettings from "./PersonaLanguageSettings";
import { NavigationGuardProvider, useNavigationGuard } from "../../context/NavigationGuardContext";
import {
  fetchPersonaLanguageSettings,
  savePersonaLanguageSettings,
  setPersonaLabel,
} from "../../api";

vi.mock("../../api", () => ({
  fetchPersonaLanguageSettings: vi.fn(),
  savePersonaLanguageSettings: vi.fn(),
  setPersonaLabel: vi.fn(),
}));

const PERSONA = { persona_id: "default", label: "預設角色", is_default: true };
let guardDirty = false;
function Probe() {
  guardDirty = useNavigationGuard().hasUnsavedChanges;
  return null;
}

function renderSettings(onSaved = vi.fn()) {
  render(
    <NavigationGuardProvider>
      <Probe />
      <PersonaLanguageSettings persona={PERSONA} projectId="proj" onSaved={onSaved} />
    </NavigationGuardProvider>,
  );
  const details = document.querySelector("details") as HTMLDetailsElement;
  details.open = true;
  fireEvent(details, new Event("toggle"));
  return onSaved;
}

describe("PersonaLanguageSettings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchPersonaLanguageSettings).mockResolvedValue({
      persona_id: "default", greetings: { en: "Hello" }, voices: { en: "v-en" },
    });
  });

  it("loads only when opened, shows what is stored and writes the whole set back", async () => {
    vi.mocked(savePersonaLanguageSettings).mockImplementation(async (_id, greetings, voices) => ({
      persona_id: "default", greetings, voices,
    }));
    const onSaved = renderSettings();
    const english = (await screen.findByLabelText("English 開場白")) as HTMLTextAreaElement;
    await waitFor(() => expect(english.value).toBe("Hello"));
    expect((screen.getByLabelText("English 聲音代號") as HTMLInputElement).value).toBe("v-en");
    expect(fetchPersonaLanguageSettings).toHaveBeenCalledWith("default", "proj");

    fireEvent.change(screen.getByLabelText("Español 開場白"), { target: { value: "  Hola  " } });
    fireEvent.change(english, { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "儲存開場白與聲音" }));

    await waitFor(() => expect(savePersonaLanguageSettings).toHaveBeenCalled());
    // 清空的語言不送（等於清掉），空白會被修剪。
    expect(savePersonaLanguageSettings).toHaveBeenCalledWith("default", { es: "Hola" }, { en: "v-en" }, "proj");
    await screen.findByText("已儲存各語言開場白與聲音");
    expect(onSaved).toHaveBeenCalled();
  });

  it("limits a greeting to 500 characters and shows the backend message when saving fails", async () => {
    vi.mocked(savePersonaLanguageSettings).mockRejectedValue(new Error("聲音代號只能用英數字與 . _ : - 這幾個符號。"));
    renderSettings();
    const zh = (await screen.findByLabelText("中文 開場白")) as HTMLTextAreaElement;
    expect(zh.maxLength).toBe(500);
    fireEvent.change(await screen.findByLabelText("中文 聲音代號"), { target: { value: "壞 代號" } });
    fireEvent.change(zh, { target: { value: "你好" } });
    fireEvent.click(screen.getByRole("button", { name: "儲存開場白與聲音" }));
    expect((await screen.findByRole("alert")).textContent).toContain("聲音代號只能用英數字");
  });

  it("flags unsaved edits so leaving the page asks first, and clears the flag after saving", async () => {
    vi.mocked(savePersonaLanguageSettings).mockResolvedValue({ persona_id: "default", greetings: { ja: "こんにちは" }, voices: {} });
    renderSettings();
    await waitFor(() => expect((screen.getByLabelText("English 開場白") as HTMLTextAreaElement).value).toBe("Hello"));
    expect(guardDirty).toBe(false);
    fireEvent.change(screen.getByLabelText("日本語 開場白"), { target: { value: "こんにちは" } });
    await waitFor(() => expect(guardDirty).toBe(true));
    fireEvent.click(screen.getByRole("button", { name: "儲存開場白與聲音" }));
    await waitFor(() => expect(guardDirty).toBe(false));
  });

  it("keeps unsaved edits when the section is collapsed and opened again", async () => {
    renderSettings();
    await waitFor(() => expect((screen.getByLabelText("English 開場白") as HTMLTextAreaElement).value).toBe("Hello"));
    fireEvent.change(screen.getByLabelText("Español 開場白"), { target: { value: "Hola" } });

    const details = document.querySelector("details") as HTMLDetailsElement;
    details.open = false;
    fireEvent(details, new Event("toggle"));
    details.open = true;
    fireEvent(details, new Event("toggle"));

    // 不重讀伺服器，草稿與未存檔提示都留著。
    await waitFor(() => expect(guardDirty).toBe(true));
    expect(fetchPersonaLanguageSettings).toHaveBeenCalledTimes(1);
    expect((screen.getByLabelText("Español 開場白") as HTMLTextAreaElement).value).toBe("Hola");
  });

  it("renames the persona, the default one included", async () => {
    vi.mocked(setPersonaLabel).mockResolvedValue({ persona_id: "default", label: "Mr. Walter" });
    const onSaved = renderSettings();
    const name = (await screen.findByLabelText("顯示名稱")) as HTMLInputElement;
    expect(name.value).toBe("預設角色");
    expect((screen.getByRole("button", { name: "儲存名稱" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(name, { target: { value: "  Mr. Walter " } });
    fireEvent.click(screen.getByRole("button", { name: "儲存名稱" }));
    await waitFor(() => expect(setPersonaLabel).toHaveBeenCalledWith("default", "Mr. Walter", "proj"));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect((screen.getByLabelText("顯示名稱") as HTMLInputElement).value).toBe("Mr. Walter");
  });

  it("shows the backend message when the name is refused", async () => {
    vi.mocked(setPersonaLabel).mockRejectedValue(new Error("名稱必須是 1 到 40 個字。"));
    renderSettings();
    fireEvent.change(await screen.findByLabelText("顯示名稱"), { target: { value: "新名字" } });
    fireEvent.click(screen.getByRole("button", { name: "儲存名稱" }));
    expect((await screen.findByRole("alert")).textContent).toContain("名稱必須是 1 到 40 個字");
  });
});
