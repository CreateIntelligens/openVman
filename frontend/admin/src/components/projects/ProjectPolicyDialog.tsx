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
import { useModalDismiss } from "../useModalDismiss";

// 跟後端 SERVER_ASR_PROVIDERS 一致：台語分流走批次辨識，只能選這些。
export const BATCH_ASR_ENGINES = new Set(["breeze", "r2t2", "r2t2-dev", "sensevoice", "openai"]);

const EMPTY_POLICY: ProjectPolicyInput = {
  allowed_asr_engines: [],
  default_asr_engine: null,
  taiwanese_asr_engine: null,
  allowed_tts_voices: [],
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

/** 預設值必須落在清單內；清單變了就把落在外面的預設清掉，免得送出後才被擋。 */
function keepInside(value: string | null, list: string[]): string | null {
  return value && (list.length === 0 || list.includes(value)) ? value : null;
}

function summary(list: string[]): string {
  return list.length === 0 ? "不限制" : `${list.length} 項`;
}

interface ChecklistProps {
  legend: string;
  options: AccountAccessOption[];
  selected: string[];
  disabled: boolean;
  onToggle: (id: string) => void;
}

function Checklist({ legend, options, selected, disabled, onToggle }: ChecklistProps) {
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
      <ul className="mt-2 grid gap-2 sm:grid-cols-2">
        {options.map((option) => (
          <li key={option.id}>
            <label className="flex cursor-pointer items-start gap-2 text-sm">
              <input
                type="checkbox"
                className="mt-0.5 h-4 w-4 shrink-0 accent-primary"
                checked={selected.includes(option.id)}
                disabled={disabled}
                onChange={() => onToggle(option.id)}
              />
              <span className="min-w-0 break-words">
                {option.label}
                {option.provider && (
                  <span className="ml-1 text-xs text-content-subtle">{option.provider}</span>
                )}
              </span>
            </label>
          </li>
        ))}
      </ul>
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
  return (
    <label className="block text-sm font-medium">
      {label}
      <select
        className="input mt-2"
        value={value ?? ""}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value || null)}
      >
        <option value="">{emptyLabel}</option>
        {options.map((option) => (
          <option key={option.id} value={option.id}>{option.label}</option>
        ))}
      </select>
    </label>
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
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dismiss = useModalDismiss(() => {
    if (!saving) onClose();
  });

  useEffect(() => {
    let active = true;
    setLoading(true);
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
          default_asr_engine: loaded.default_asr_engine ?? null,
          taiwanese_asr_engine: loaded.taiwanese_asr_engine ?? null,
          allowed_tts_voices: loaded.allowed_tts_voices ?? [],
          default_tts_voice: loaded.default_tts_voice ?? null,
          allowed_characters: loaded.allowed_characters ?? [],
          default_character_id: loaded.default_character_id ?? null,
          allowed_backgrounds: loaded.allowed_backgrounds ?? [],
          default_background_id: loaded.default_background_id ?? null,
          allowed_mascots: loaded.allowed_mascots ?? [],
          default_mascot_id: loaded.default_mascot_id ?? null,
        });
        setEngines(options.asr_engines ?? []);
        setVoices(options.custom_voices ?? []);
        setCharacters(options.avatar_characters ?? []);
        setBackgrounds(options.avatar_backgrounds ?? []);
        setMascots(options.avatar_mascots ?? []);
        setIsRoot(currentAccount?.role === "root");
        if (res) {
          setAssignedResources(res);
        }
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
  }, [projectId]);

  const engineOptions = withMissing(engines, policy.allowed_asr_engines);
  const voiceOptions = withMissing(voices, policy.allowed_tts_voices);
  const characterOptions = withMissing(characters, policy.allowed_characters ?? []);
  const backgroundOptions = withMissing(backgrounds, policy.allowed_backgrounds ?? []);
  const mascotOptions = withMissing(mascots, policy.allowed_mascots ?? []);

  const engineChoices = policy.allowed_asr_engines.length
    ? engineOptions.filter((option) => policy.allowed_asr_engines.includes(option.id))
    : engines;
  const voiceChoices = policy.allowed_tts_voices.length
    ? voiceOptions.filter((option) => policy.allowed_tts_voices.includes(option.id))
    : voices;
  const characterChoices = (policy.allowed_characters?.length ?? 0) > 0
    ? characterOptions.filter((option) => policy.allowed_characters?.includes(option.id))
    : characters;
  const backgroundChoices = (policy.allowed_backgrounds?.length ?? 0) > 0
    ? backgroundOptions.filter((option) => policy.allowed_backgrounds?.includes(option.id))
    : backgrounds;
  const mascotChoices = (policy.allowed_mascots?.length ?? 0) > 0
    ? mascotOptions.filter((option) => policy.allowed_mascots?.includes(option.id))
    : mascots;
  const taiwaneseChoices = engineChoices.filter((option) => BATCH_ASR_ENGINES.has(option.id));
  const busy = loading || saving || assigning;

  function toggleEngine(id: string) {
    setPolicy((current) => {
      const allowed = toggled(current.allowed_asr_engines, id);
      return {
        ...current,
        allowed_asr_engines: allowed,
        default_asr_engine: keepInside(current.default_asr_engine, allowed),
        taiwanese_asr_engine: keepInside(current.taiwanese_asr_engine, allowed),
      };
    });
  }

  function toggleVoice(id: string) {
    setPolicy((current) => {
      const allowed = toggled(current.allowed_tts_voices, id);
      return {
        ...current,
        allowed_tts_voices: allowed,
        default_tts_voice: keepInside(current.default_tts_voice, allowed),
      };
    });
  }

  function toggleCharacter(id: string) {
    setPolicy((current) => {
      const allowed = toggled(current.allowed_characters ?? [], id);
      return {
        ...current,
        allowed_characters: allowed,
        default_character_id: keepInside(current.default_character_id ?? null, allowed),
      };
    });
  }

  function toggleBackground(id: string) {
    setPolicy((current) => {
      const allowed = toggled(current.allowed_backgrounds ?? [], id);
      return {
        ...current,
        allowed_backgrounds: allowed,
        default_background_id: keepInside(current.default_background_id ?? null, allowed),
      };
    });
  }

  function toggleMascot(id: string) {
    setPolicy((current) => {
      const allowed = toggled(current.allowed_mascots ?? [], id);
      return {
        ...current,
        allowed_mascots: allowed,
        default_mascot_id: keepInside(current.default_mascot_id ?? null, allowed),
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
              className="mx-6 mt-5 rounded-md border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger"
              role="alert"
            >
              {error}
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
                  legend="允許的小助理 (VRM / 影片)"
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
              </div>

              {/* TTS 聲音 */}
              <div className="space-y-4 border-b border-border px-6 py-5">
                <Checklist
                  legend="允許的聲音"
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
                          <span className="rounded bg-amber-500/10 text-amber-500 px-1.5 py-0.5 text-xs font-medium">
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
                      className="btn btn-secondary btn-sm"
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
