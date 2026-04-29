import type { PersonaSummary } from "../../api";
import PersonaCard from "./PersonaCard";

interface PersonaListProps {
  personas: PersonaSummary[];
  selectedPersonaId?: string;
  deletingPersonaId: string;
  onSelect: (persona: PersonaSummary) => void;
  onDelete: (persona: PersonaSummary) => void;
}

export default function PersonaList({
  personas,
  selectedPersonaId,
  deletingPersonaId,
  onSelect,
  onDelete,
}: PersonaListProps) {
  return (
    <div>
      <div className="flex items-center justify-between mb-3 px-1 text-[0.6875rem] font-medium text-slate-500 uppercase tracking-wider">
        <span>角色庫（{personas.length}）</span>
      </div>
      <div className="grid gap-1">
        {personas.map((persona) => (
          <PersonaCard
            key={persona.persona_id}
            persona={persona}
            selected={selectedPersonaId === persona.persona_id}
            deleting={deletingPersonaId === persona.persona_id}
            onSelect={onSelect}
            onDelete={onDelete}
          />
        ))}
      </div>
    </div>
  );
}
