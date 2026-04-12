import { useCallback, useEffect, useState } from "react";
import { fetchTools, type SkillInfo } from "../api";

export function useSlashAutocomplete(input: string, setInput: (val: string) => void) {
       const [slashSkills, setSlashSkills] = useState<SkillInfo[]>([]);
       const [slashOpen, setSlashOpen] = useState(false);
       const [slashIndex, setSlashIndex] = useState(0);

       useEffect(() => {
              fetchTools()
                     .then((data) => setSlashSkills(data.skills.filter((skill) => skill.enabled)))
                     .catch((reason) => console.warn("Failed to load skills for autocomplete:", reason));
       }, []);

       const slashFilter = slashOpen ? input.slice(1).toLowerCase() : "";
       const slashMatches = slashOpen
              ? slashSkills.filter(
                     (skill) => skill.id.includes(slashFilter) || skill.name.toLowerCase().includes(slashFilter),
              )
              : [];
       const clampedSlashIndex = Math.min(slashIndex, Math.max(slashMatches.length - 1, 0));

       const handleInputChange = useCallback((value: string) => {
              setInput(value);
              setSlashOpen(value.startsWith("/") && !value.includes(" "));
              if (value === "/") setSlashIndex(0);
       }, [setInput]);

       const pickSlash = useCallback((skill: SkillInfo) => {
              setInput(`/${skill.id} `);
              setSlashOpen(false);
       }, [setInput]);

       return {
              slashOpen,
              slashIndex,
              setSlashIndex,
              setSlashOpen,
              slashMatches,
              clampedSlashIndex,
              handleInputChange,
              pickSlash,
       };
}
