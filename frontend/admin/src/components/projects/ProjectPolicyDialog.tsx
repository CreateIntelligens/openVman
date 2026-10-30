import { useEffect, useState, type FormEvent } from "react";

import {
  fetchAccountAccessOptions,
  getCurrentAccount,
  type AccountAccessOption,
} from "../../api/auth";
import {
  assignProjectResource,
  fetchProjectPolicy,
  fetchProjectResources,
  saveProjectPolicy,
  unassignProjectResource,
  type ProjectPolicyInput,
  type ProjectResourcesResponse,
} from "../../api/projects";
import { errorMessage } from "../../utils/errorMessage";
import { groupAccessOptions, type GrantType } from "../accounts/accountAccessGroups";
import GroupedChecklist from "../accounts/GroupedChecklist";
import { useModalDismiss } from "../useModalDismiss";

// 跟後端 SERVER_ASR_PROVIDERS 一致：台語分流走批次辨識，只能選這些。
export const BATCH_ASR_ENGINES = new Set(["breeze", "r2t2", "r2t2-dev", "sensevoice", "openai"]);

const TTS_ENGINE_LABELS: Record<string, string> = {
  indextts: "IndexTTS",
  voxcpm: "VoxCPM",
  cosyvoice: "CosyVoice",
  "gemini-tts": "Gemini TTS",
  "gcp-tts": "GCP TTS",
  "aws-polly": "AWS Polly",
  "edge-tts": "Edge TTS",
};

const ASR_ENGINE_LABELS: Record<string, string> = {
  breeze: "Breeze",
  r2t2: "R2T2",
  "r2t2-dev": "R2T2 dev",
  sensevoice: "SenseVoice",
  openai: "OpenAI",
};

const EMPTY_POLICY: ProjectPolicyInput = {
  allowed_asr_engines: [],
  asr_engine_order: [],
  default_asr_engine: null,
  taiwanese_asr_engine: null,
  allowed_tts_voices: [],
  tts_engine_order: [],
  default_tts_voice: null,
  allowed_characters: [],
  default_character_id: null,
  allowed_backgrounds: [],
  default_background_id: null,
  allowed_mascots: [],
  default_mascot_id: null,
};

interface ProjectPolicyDialogProps {
  projectId: string;
  projectLabel: string;
  onClose: () => void;
  onSaved: (message: string) => void;
}

/** 清單裡有、但選項已經沒有的（引擎下架、聲音刪除）也要列出來，才能取消勾選。 */
function withMissing(options: AccountAccessOption[], selected: string[]): AccountAccessOption[] {
  const known = new Set(options.map((option) => option.id));
  return [
    ...options,
    ...selected
      .filter((id) => !known.has(id))
      .map((id) => ({ id, label: `${id}（已不存在）` })),
  ];
}

function toggled(list: string[], id: string): string[] {
  return list.includes(id) ? list.filter((item) => item !== id) : [...list, id];
}

/** 預設值必須落在清單內（或是專案資源／ROOT 指派）；清單變了就把落在外面的預設清掉，免得送出後才被擋。 */
function keepInside(value: string | null, list: string[], specialAllowed?: Set<string>): string | null {
  if (!value) return null;
  if (list.length === 0 || list.includes(value) || specialAllowed?.has(value)) {
    return value;
  }
  return null;
}

function summary(list: string[]): string {
  return list.length === 0 ? "不限制" : `${list.length} 項`;
}

export function mergeProjectResources(
  baseOptions: AccountAccessOption[],
  projectItems?: import("../../api/projects").ProjectResourceItem[],
): AccountAccessOption[] {
  const map = new Map<string, AccountAccessOption>();
  for (const opt of baseOptions) {
    map.set(opt.id, { ...opt });
  }
  if (projectItems) {
    for (const item of projectItems) {
      const existing = map.get(item.resource_id);
      if (existing) {
        map.set(item.resource_id, {
          ...existing,
          label: existing.label || item.label || item.resource_id,
          source: item.source,
          in_project_scope: item.in_project_scope,
        });
      } else {
        map.set(item.resource_id, {
          id: item.resource_id,
          label: item.label || item.resource_id,
          source: item.source,
          in_project_scope: item.in_project_scope,
        });
      }
    }
  }
  return Array.from(map.values());
}

interface ChecklistProps {
  legend: string;
  grantType: GrantType;
  options: AccountAccessOption[];
  selected: string[];
  disabled: boolean;
  onToggle: (id: string) => void;
  /** 整段勾選；沒給就只能逐項點。 */
  onSetMany?: (ids: string[], selected: boolean) => void;
}

function Checklist({ legend, grantType, options, selected, disabled, onToggle, onSetMany }: ChecklistProps) {
  return (
    <fieldset>
      <legend className="text-sm font-medium">
        {legend}
        <span className="ml-2 text-xs font-normal text-content-muted">
          {summary(selected)}
        </span>
      </legend>
      {selected.length === 0 && (
        <p className="mt-1 text-xs text-content-muted">
          不限制：沿用各帳號自己的授權。勾選後只能用勾選的項目。
        </p>
      )}
      <GroupedChecklist
        sections={groupAccessOptions(grantType, options)}
        isSelected={(option) => selected.includes(option.id)}
        onToggle={(option) => onToggle(option.id)}
        onSetAll={(targets, next) => {
          if (onSetMany) onSetMany(targets.map((option) => option.id), next);
          else targets.forEach((option) => { if (selected.includes(option.id) !== next) onToggle(option.id); });
        }}
        disabled={disabled}
        searchLabel={`搜尋${legend}`}
        rowClassName={(option) => option.in_project_scope === false ? "text-danger" : ""}
        titleSuffix={(option) => option.in_project_scope === false ? (
          <span className="ml-1 text-xs font-medium text-danger">（不在專案範圍內，一般使用者無法使用）</span>
        ) : null}
      />
    </fieldset>
  );
}

interface DefaultSelectProps {
  label: string;
  value: string | null;
  options: AccountAccessOption[];
  disabled: boolean;
  emptyLabel: string;
  onChange: (value: string | null) => void;
}

function DefaultSelect({ label, value, options, disabled, emptyLabel, onChange }: DefaultSelectProps) {
  const selectedOption = options.find((option) => option.id === value);
  const isOutOfScope = selectedOption?.in_project_scope === false;
  return (
    <label className={`block text-sm font-medium ${isOutOfScope ? "text-danger" : ""}`}>
      {label}
      <select
        className={`input mt-2 ${isOutOfScope ? "text-danger" : ""}`}
        value={value ?? ""}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value || null)}
      >
        <option value="">{emptyLabel}</option>
        {options.map((option) => (
          <option
            key={option.id}
            value={option.id}
            className={option.in_project_scope === false ? "text-danger" : ""}
          >
            {option.label}
            {option.in_project_scope === false ? "（不在專案範圍內，一般使用者無法使用）" : ""}
          </option>
        ))}
      </select>
      {isOutOfScope && (
        <span className="mt-1 block text-xs text-danger font-normal">
          不在專案範圍內，一般使用者無法使用
        </span>
      )}
    </label>
  );
}

interface EngineOrderEditorProps {
  label: string;
  help: string;
  labels: Record<string, string>;
  options: string[];
  order: string[];
  disabled: boolean;
  onChange: (order: string[]) => void;
}

function EngineOrderEditor({
  label, help, labels, options, order, disabled, onChange,
}: EngineOrderEditorProps) {
  const available = options.filter((id) => !order.includes(id));

  function move(index: number, offset: number) {
    const next = [...order];
    [next[index], next[index + offset]] = [next[index + offset], next[index]];
    onChange(next);
  }

  return (
    <fieldset disabled={disabled}>
      <legend className="text-sm font-medium">{label}</legend>
      <p className="mt-1 text-xs leading-5 text-content-muted">{help}</p>
      <select
        aria-label={`新增${label}`}
        className="input mt-2"
        value=""
        disabled={disabled || available.length === 0}
        onChange={(event) => {
          if (event.target.value) onChange([...order, event.target.value]);
        }}
      >
        <option value="">選擇要新增的引擎…</option>
        {available.map((id) => <option key={id} value={id}>{labels[id] ?? id}</option>)}
      </select>
      <ol aria-label={`${label}清單`} className="mt-2 space-y-2">
        {order.map((id, index) => (
          <li
            key={id}
            className="flex flex-wrap items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm"
          >
            <span className="min-w-0 break-words">{index + 1}. {labels[id] ?? id}</span>
            <div className="ml-auto flex shrink-0 gap-1 whitespace-nowrap">
              <button
                type="button"
                className="btn btn-ghost px-2 py-1 text-xs"
                aria-label={`${labels[id] ?? id}上移`}
                disabled={disabled || index === 0}
                onClick={() => move(index, -1)}
              >上移</button>
              <button
                type="button"
                className="btn btn-ghost px-2 py-1 text-xs"
                aria-label={`${labels[id] ?? id}下移`}
                disabled={disabled || index === order.length - 1}
                onClick={() => move(index, 1)}
              >下移</button>
              <button
                type="button"
                className="btn btn-ghost px-2 py-1 text-xs text-danger"
                aria-label={`${labels[id] ?? id}移除`}
                onClick={() => onChange(order.filter((item) => item !== id))}
              >移除</button>
            </div>
          </li>
        ))}
      </ol>
    </fieldset>
  );
}

/** 專案的資源與語音設定：限制可用人物、背景、小助理、辨識引擎與聲音。 */
export default function ProjectPolicyDialog({
  projectId,
  projectLabel,
  onClose,
  onSaved,
}: ProjectPolicyDialogProps) {
  const [policy, setPolicy] = useState<ProjectPolicyInput>(EMPTY_POLICY);
  const [engines, setEngines] = useState<AccountAccessOption[]>([]);
  const [voices, setVoices] = useState<AccountAccessOption[]>([]);
  const [characters, setCharacters] = useState<AccountAccessOption[]>([]);
  const [backgrounds, setBackgrounds] = useState<AccountAccessOption[]>([]);
  const [mascots, setMascots] = useState<AccountAccessOption[]>([]);
  const [isRoot, setIsRoot] = useState(false);
  const [assignedResources, setAssignedResources] = useState<ProjectResourcesResponse | null>(null);
  const [assignType, setAssignType] = useState<string>("avatar_character");
  const [assignId, setAssignId] = useState<string>("");
  const [assigning, setAssigning] = useState(false);
  const [loading, setLoading] = useState(true);
  // 讀到目前的設定才准儲存：讀失敗時表單裡是空清單，而空清單對後端代表
  // 「不限制」，一按儲存就把專案的限制整個解掉。
  const [loaded, setLoaded] = useState(false);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dismiss = useModalDismiss(() => {
    if (!saving) onClose();
  });

  useEffect(() => {
    let active = true;
    setLoading(true);
    setLoaded(false);
    setError(null);
    Promise.all([
      fetchProjectPolicy(projectId),
      fetchAccountAccessOptions(),
      getCurrentAccount().catch(() => null),
      fetchProjectResources(projectId).catch(() => null),
    ])
      .then(([loaded, options, currentAccount, res]) => {
        if (!active) return;
        setPolicy({
          allowed_asr_engines: loaded.allowed_asr_engines ?? [],
          asr_engine_order: loaded.asr_engine_order ?? [],
          default_asr_engine: loaded.default_asr_engine ?? null,
          taiwanese_asr_engine: loaded.taiwanese_asr_engine ?? null,
          allowed_tts_voices: loaded.allowed_tts_voices ?? [],
          tts_engine_order: loaded.tts_engine_order ?? [],
          default_tts_voice: loaded.default_tts_voice ?? null,
          allowed_characters: loaded.allowed_characters ?? [],
          default_character_id: loaded.default_character_id ?? null,
          allowed_backgrounds: loaded.allowed_backgrounds ?? [],
          default_background_id: loaded.default_background_id ?? null,
          allowed_mascots: loaded.allowed_mascots ?? [],
          default_mascot_id: loaded.default_mascot_id ?? null,
        });
        setEngines(mergeProjectResources(options.asr_engines ?? [], res?.asr_engine));
        setVoices(mergeProjectResources(options.custom_voices ?? [], res?.custom_voice));
        setCharacters(mergeProjectResources(options.avatar_characters ?? [], res?.avatar_character));
        setBackgrounds(mergeProjectResources(options.avatar_backgrounds ?? [], res?.avatar_background));
        setMascots(mergeProjectResources(options.avatar_mascots ?? [], res?.avatar_mascot));
        setIsRoot(currentAccount?.role === "root");
        if (res) {
          setAssignedResources(res);
        }
        setLoaded(true);
      })
      .catch((reason) => {
        if (active) setError(errorMessage(reason, "無法載入專案設定"));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [projectId, loadAttempt]);

  const engineOptions = withMissing(engines, policy.allowed_asr_engines);
  const voiceOptions = withMissing(voices, policy.allowed_tts_voices);
  const characterOptions = withMissing(characters, policy.allowed_characters ?? []);
  const backgroundOptions = withMissing(backgrounds, policy.allowed_backgrounds ?? []);
  const mascotOptions = withMissing(mascots, policy.allowed_mascots ?? []);

  const isSpecial = (opt: AccountAccessOption) => opt.source === "project" || opt.source === "assigned";

  const engineChoices = policy.allowed_asr_engines.length
    ? engineOptions.filter((option) => policy.allowed_asr_engines.includes(option.id) || isSpecial(option))
    : engines;
  const voiceChoices = policy.allowed_tts_voices.length
    ? voiceOptions.filter((option) => policy.allowed_tts_voices.includes(option.id) || isSpecial(option))
    : voices;
  const characterChoices = (policy.allowed_characters?.length ?? 0) > 0
    ? characterOptions.filter((option) => policy.allowed_characters?.includes(option.id) || isSpecial(option))
    : characters;
  const backgroundChoices = (policy.allowed_backgrounds?.length ?? 0) > 0
    ? backgroundOptions.filter((option) => policy.allowed_backgrounds?.includes(option.id) || isSpecial(option))
    : backgrounds;
  const mascotChoices = (policy.allowed_mascots?.length ?? 0) > 0
    ? mascotOptions.filter((option) => policy.allowed_mascots?.includes(option.id) || isSpecial(option))
    : mascots;
  const taiwaneseChoices = engineChoices.filter((option) => BATCH_ASR_ENGINES.has(option.id));
  const busy = loading || saving || assigning || !loaded;

  const specialEngines = new Set(engines.filter(isSpecial).map((o) => o.id));
  const specialVoices = new Set(voices.filter(isSpecial).map((o) => o.id));
  const specialCharacters = new Set(characters.filter(isSpecial).map((o) => o.id));
  const specialBackgrounds = new Set(backgrounds.filter(isSpecial).map((o) => o.id));
  const specialMascots = new Set(mascots.filter(isSpecial).map((o) => o.id));

  function toggleEngine(id: string) {
    setPolicy((current) => {
      const allowed = toggled(current.allowed_asr_engines, id);
      return {
        ...current,
        allowed_asr_engines: allowed,
        asr_engine_order: allowed.length
          ? current.asr_engine_order.filter((engine) => allowed.includes(engine))
          : current.asr_engine_order,
        default_asr_engine: keepInside(current.default_asr_engine, allowed, specialEngines),
        taiwanese_asr_engine: keepInside(current.taiwanese_asr_engine, allowed, specialEngines),
      };
    });
  }

  function toggleVoice(id: string) {
    setPolicy((current) => {
      const allowed = toggled(current.allowed_tts_voices, id);
      return {
        ...current,
        allowed_tts_voices: allowed,
        default_tts_voice: keepInside(current.default_tts_voice, allowed, specialVoices),
      };
    });
  }

  function toggleCharacter(id: string) {
    setPolicy((current) => {
      const allowed = toggled(current.allowed_characters ?? [], id);
      return {
        ...current,
        allowed_characters: allowed,
        default_character_id: keepInside(current.default_character_id ?? null, allowed, specialCharacters),
      };
    });
  }

  function toggleBackground(id: string) {
    setPolicy((current) => {
      const allowed = toggled(current.allowed_backgrounds ?? [], id);
      return {
        ...current,
        allowed_backgrounds: allowed,
        default_background_id: keepInside(current.default_background_id ?? null, allowed, specialBackgrounds),
      };
    });
  }

  function toggleMascot(id: string) {
    setPolicy((current) => {
      const allowed = toggled(current.allowed_mascots ?? [], id);
      return {
        ...current,
        allowed_mascots: allowed,
        default_mascot_id: keepInside(current.default_mascot_id ?? null, allowed, specialMascots),
      };
    });
  }

  async function handleAssign() {
    if (!assignId) return;
    setAssigning(true);
    setError(null);
    try {
      await assignProjectResource(projectId, assignType, assignId);
      const updated = await fetchProjectResources(projectId);
      setAssignedResources(updated);
      setCharacters((prev) => mergeProjectResources(prev, updated.avatar_character));
      setBackgrounds((prev) => mergeProjectResources(prev, updated.avatar_background));
      setMascots((prev) => mergeProjectResources(prev, updated.avatar_mascot));
      setVoices((prev) => mergeProjectResources(prev, updated.custom_voice));
      setEngines((prev) => mergeProjectResources(prev, updated.asr_engine));
      setAssignId("");
    } catch (reason) {
      setError(errorMessage(reason, "指派資源失敗"));
    } finally {
      setAssigning(false);
    }
  }

  async function handleUnassign(type: string, id: string) {
    setAssigning(true);
    setError(null);
    try {
      await unassignProjectResource(projectId, type, id);
      const updated = await fetchProjectResources(projectId);
      setAssignedResources(updated);
      setCharacters((prev) => mergeProjectResources(prev, updated.avatar_character));
      setBackgrounds((prev) => mergeProjectResources(prev, updated.avatar_background));
      setMascots((prev) => mergeProjectResources(prev, updated.avatar_mascot));
      setVoices((prev) => mergeProjectResources(prev, updated.custom_voice));
      setEngines((prev) => mergeProjectResources(prev, updated.asr_engine));
    } catch (reason) {
      setError(errorMessage(reason, "解除指派失敗"));
    } finally {
      setAssigning(false);
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await saveProjectPolicy(projectId, policy);
      onSaved(`專案「${projectLabel}」的設定已更新`);
    } catch (reason) {
      setError(errorMessage(reason, "儲存專案設定失敗"));
    } finally {
      setSaving(false);
    }
  }

  const assignedItems: Array<{ type: string; typeLabel: string; id: string; label: string }> = [];
  if (assignedResources) {
    (assignedResources.avatar_character ?? []).filter((c) => c.source === "assigned").forEach((c) => {
      assignedItems.push({ type: "avatar_character", typeLabel: "人物", id: c.resource_id, label: c.label || c.resource_id });
    });
    (assignedResources.avatar_background ?? []).filter((b) => b.source === "assigned").forEach((b) => {
      assignedItems.push({ type: "avatar_background", typeLabel: "背景", id: b.resource_id, label: b.label || b.resource_id });
    });
    (assignedResources.avatar_mascot ?? []).filter((m) => m.source === "assigned").forEach((m) => {
      assignedItems.push({ type: "avatar_mascot", typeLabel: "小助理", id: m.resource_id, label: m.label || m.resource_id });
    });
    (assignedResources.custom_voice ?? []).filter((v) => v.source === "assigned").forEach((v) => {
      assignedItems.push({ type: "custom_voice", typeLabel: "聲音", id: v.resource_id, label: v.label || v.resource_id });
    });
    (assignedResources.asr_engine ?? []).filter((a) => a.source === "assigned").forEach((a) => {
      assignedItems.push({ type: "asr_engine", typeLabel: "ASR", id: a.resource_id, label: a.label || a.resource_id });
    });
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      role="presentation"
      {...dismiss}
    >
      <section
        className="max-h-[90dvh] w-full max-w-3xl overflow-y-auto rounded-xl border border-border bg-surface-overlay shadow-2xl"
        role="dialog"
        aria-modal="true"
        aria-labelledby="project-policy-title"
      >
        <header className="border-b border-border px-6 py-5">
          <h2 id="project-policy-title" className="card-title">
            專案資源與語音設定：{projectLabel}
          </h2>
          <p className="mt-2 text-sm leading-6 text-content-muted">
            限制這個專案能用的人物、背景、小助理、語音辨識引擎與聲音。實際能用的是帳號授權與這裡的交集；
            清單留空代表不限制。專案專屬資源與 ROOT 指派資源不受帳號授權限制。
          </p>
        </header>

        <form onSubmit={submit}>
          {error && (
            <div
              className="mx-6 mt-5 flex flex-wrap items-center justify-between gap-2 rounded-md border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger"
              role="alert"
            >
              <span>{error}</span>
              {!loaded && (
                <button
                  className="btn btn-ghost px-2 py-1 text-xs"
                  type="button"
                  onClick={() => setLoadAttempt((attempt) => attempt + 1)}
                  disabled={loading}
                >
                  重新讀取
                </button>
              )}
            </div>
          )}

          {loading ? (
            <p className="px-6 py-5 text-sm text-content-muted">載入中…</p>
          ) : (
            <>
              {/* 人物設定 */}
              <div className="space-y-4 border-b border-border px-6 py-5">
                <Checklist
                  legend="允許的虛擬人物"
                  grantType="avatar_characters"
                  options={characterOptions}
                  selected={policy.allowed_characters ?? []}
                  disabled={busy}
                  onToggle={toggleCharacter}
                />
                <DefaultSelect
                  label="預設人物"
                  value={policy.default_character_id ?? null}
                  options={characterChoices}
                  disabled={busy}
                  emptyLabel="不指定（帳號預設人物）"
                  onChange={(value) => setPolicy((current) => ({
                    ...current, default_character_id: value,
                  }))}
                />
              </div>

              {/* 背景設定 */}
              <div className="space-y-4 border-b border-border px-6 py-5">
                <Checklist
                  legend="允許的舞台背景"
                  grantType="avatar_backgrounds"
                  options={backgroundOptions}
                  selected={policy.allowed_backgrounds ?? []}
                  disabled={busy}
                  onToggle={toggleBackground}
                />
                <DefaultSelect
                  label="預設背景"
                  value={policy.default_background_id ?? null}
                  options={backgroundChoices}
                  disabled={busy}
                  emptyLabel="不指定（帳號預設背景）"
                  onChange={(value) => setPolicy((current) => ({
                    ...current, default_background_id: value,
                  }))}
                />
              </div>

              {/* 小助理設定 */}
              <div className="space-y-4 border-b border-border px-6 py-5">
                <Checklist
                  legend="允許的小助理"
                  grantType="avatar_mascots"
                  options={mascotOptions}
                  selected={policy.allowed_mascots ?? []}
                  disabled={busy}
                  onToggle={toggleMascot}
                />
                <DefaultSelect
                  label="預設小助理"
                  value={policy.default_mascot_id ?? null}
                  options={mascotChoices}
                  disabled={busy}
                  emptyLabel="不指定（帳號預設小助理）"
                  onChange={(value) => setPolicy((current) => ({
                    ...current, default_mascot_id: value,
                  }))}
                />
              </div>

              {/* ASR 語音辨識 */}
              <div className="space-y-4 border-b border-border px-6 py-5">
                <Checklist
                  legend="允許的語音辨識引擎"
                  grantType="asr_engines"
                  options={engineOptions}
                  selected={policy.allowed_asr_engines}
                  disabled={busy}
                  onToggle={toggleEngine}
                />
                <div className="grid gap-4 sm:grid-cols-2">
                  <DefaultSelect
                    label="預設引擎"
                    value={policy.default_asr_engine}
                    options={engineChoices}
                    disabled={busy}
                    emptyLabel="不指定（帳號偏好或部署預設）"
                    onChange={(value) => setPolicy((current) => ({
                      ...current, default_asr_engine: value,
                    }))}
                  />
                  <DefaultSelect
                    label="台語分流引擎"
                    value={policy.taiwanese_asr_engine}
                    options={taiwaneseChoices}
                    disabled={busy}
                    emptyLabel="不指定（Breeze）"
                    onChange={(value) => setPolicy((current) => ({
                      ...current, taiwanese_asr_engine: value,
                    }))}
                  />
                </div>
                <EngineOrderEditor
                  label="批次 ASR 引擎順位"
                  help="指定引擎之後的備援順序；空白用部署順序"
                  labels={ASR_ENGINE_LABELS}
                  options={Object.keys(ASR_ENGINE_LABELS).filter((id) => (
                    policy.allowed_asr_engines.length === 0 || policy.allowed_asr_engines.includes(id)
                  ))}
                  order={policy.asr_engine_order}
                  disabled={busy}
                  onChange={(order) => setPolicy((current) => ({ ...current, asr_engine_order: order }))}
                />
              </div>

              {/* TTS 聲音 */}
              <div className="space-y-4 border-b border-border px-6 py-5">
                <Checklist
                  legend="允許的聲音"
                  grantType="custom_voices"
                  options={voiceOptions}
                  selected={policy.allowed_tts_voices}
                  disabled={busy}
                  onToggle={toggleVoice}
                />
                <DefaultSelect
                  label="預設聲音"
                  value={policy.default_tts_voice}
                  options={voiceChoices}
                  disabled={busy}
                  emptyLabel="不指定（帳號預設聲音）"
                  onChange={(value) => setPolicy((current) => ({
                    ...current, default_tts_voice: value,
                  }))}
                />
                <p className="text-xs leading-5 text-content-muted">
                  限制聲音時，合成失敗只會退回清單裡的 Edge 聲音；清單沒有 Edge 聲音就直接回錯誤，
                  不會默默換成別的引擎。
                </p>
                <EngineOrderEditor
                  label="TTS 引擎順位"
                  help="沒指定引擎與聲音時照這個順序試；空白用部署順序"
                  labels={TTS_ENGINE_LABELS}
                  options={Object.keys(TTS_ENGINE_LABELS)}
                  order={policy.tts_engine_order}
                  disabled={busy}
                  onChange={(order) => setPolicy((current) => ({ ...current, tts_engine_order: order }))}
                />
              </div>

              {/* 資源指派專區 */}
              <div className="space-y-4 bg-surface-sunken px-6 py-5">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-sm font-semibold text-content">
                      ROOT 資源指派（將全域資源指派給此專案）
                    </h3>
                    <p className="text-xs text-content-muted">
                      指派給專案的資源，任何可存取此專案的使用者均可使用，不受個人帳號授權限制。
                    </p>
                  </div>
                  {!isRoot && (
                    <span className="rounded bg-surface-overlay border border-border px-2 py-0.5 text-xs text-content-muted">
                      唯讀（僅 ROOT 可編輯）
                    </span>
                  )}
                </div>

                {assignedItems.length > 0 ? (
                  <ul className="space-y-2">
                    {assignedItems.map((item) => (
                      <li
                        key={`${item.type}-${item.id}`}
                        className="flex items-center justify-between rounded-lg border border-border bg-surface-overlay px-3 py-2 text-sm"
                      >
                        <div className="flex items-center gap-2">
                          <span className="rounded bg-primary/10 px-2 py-0.5 text-xs text-primary font-medium">
                            {item.typeLabel}
                          </span>
                          <span className="rounded bg-success/10 text-success px-1.5 py-0.5 text-xs font-medium">
                            ROOT 指派
                          </span>
                          <span className="font-medium">{item.label}</span>
                          <span className="text-xs text-content-subtle font-mono">{item.id}</span>
                        </div>
                        {isRoot && (
                          <button
                            type="button"
                            className="btn btn-ghost btn-sm text-danger hover:bg-danger/10"
                            disabled={busy}
                            onClick={() => handleUnassign(item.type, item.id)}
                          >
                            解除指派
                          </button>
                        )}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-xs text-content-muted italic">目前無指派資源</p>
                )}

                {isRoot && (
                  <div className="mt-4 flex flex-wrap items-center gap-2 pt-2 border-t border-border/50">
                    <select
                      aria-label="指派類型"
                      className="input text-xs"
                      value={assignType}
                      disabled={busy}
                      onChange={(e) => {
                        setAssignType(e.target.value);
                        setAssignId("");
                      }}
                    >
                      <option value="avatar_character">人物</option>
                      <option value="avatar_background">背景</option>
                      <option value="avatar_mascot">小助理</option>
                      <option value="custom_voice">聲音</option>
                      <option value="asr_engine">ASR</option>
                    </select>

                    <select
                      aria-label="指派資源"
                      className="input text-xs"
                      value={assignId}
                      disabled={busy}
                      onChange={(e) => setAssignId(e.target.value)}
                    >
                      <option value="">選擇要指派的資源…</option>
                      {assignType === "avatar_character" &&
                        characterOptions.map((c) => (
                          <option key={c.id} value={c.id}>{c.label}</option>
                        ))}
                      {assignType === "avatar_background" &&
                        backgroundOptions.map((b) => (
                          <option key={b.id} value={b.id}>{b.label}</option>
                        ))}
                      {assignType === "avatar_mascot" &&
                        mascotOptions.map((m) => (
                          <option key={m.id} value={m.id}>{m.label}</option>
                        ))}
                      {assignType === "custom_voice" &&
                        voiceOptions.map((v) => (
                          <option key={v.id} value={v.id}>{v.label}</option>
                        ))}
                      {assignType === "asr_engine" &&
                        engineOptions.map((e) => (
                          <option key={e.id} value={e.id}>{e.label}</option>
                        ))}
                    </select>

                    <button
                      type="button"
                      className="btn btn-primary btn-sm"
                      disabled={busy || !assignId}
                      onClick={handleAssign}
                    >
                      指派至專案
                    </button>
                  </div>
                )}
              </div>
            </>
          )}

          <div className="flex flex-wrap justify-end gap-3 border-t border-border bg-surface-sunken px-6 py-4">
            <button className="btn btn-ghost" type="button" onClick={onClose} disabled={saving}>
              取消
            </button>
            <button className="btn btn-primary" type="submit" disabled={busy}>
              {saving ? "儲存中…" : "儲存"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
