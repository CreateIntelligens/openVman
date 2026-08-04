import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import Select from "./Select";

const options = [
  { value: "alpha", label: "Alpha" },
  { value: "beta", label: "Beta" },
  { value: "gamma", label: "Gamma" },
];

describe("Select", () => {
  it("exposes combobox state and supports keyboard selection", () => {
    const onChange = vi.fn();
    render(
      <Select
        ariaLabel="測試選單"
        value="alpha"
        options={options}
        onChange={onChange}
      />,
    );

    const trigger = screen.getByRole("combobox", { name: "測試選單" });
    expect(trigger.getAttribute("aria-expanded")).toBe("false");

    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    fireEvent.keyDown(trigger, { key: "End" });
    fireEvent.keyDown(trigger, { key: "Enter" });

    expect(onChange).toHaveBeenCalledWith("gamma");
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
  });

  it("supports typeahead and closes on Tab", () => {
    const onChange = vi.fn();
    render(
      <Select value="" options={options} onChange={onChange} placeholder="選擇" />,
    );

    const trigger = screen.getByRole("combobox", { name: "選擇" });
    fireEvent.keyDown(trigger, { key: "b" });
    expect(trigger.getAttribute("aria-activedescendant")).toContain("option-1");
    fireEvent.keyDown(trigger, { key: "Tab" });
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
  });
});
