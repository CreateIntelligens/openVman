import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import {
  createTemporaryBatch,
  fetchAccountAccessOptions,
  listTemporaryBatches,
  revokeTemporaryBatch,
  type AccountAccessOption,
  type TemporaryBatchAudit,
  type TemporaryBatchResult,
} from "../../api/auth";

const PREFERRED_PROJECT = "proj-b85afb8bb6";
const PREFERRED_CHARACTER = "0713";
const PREFERRED_VOICE = "hayley";

interface VoiceOption {
  provider: string;
  voice: string;
}

function messageFrom(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

function preferredId(ids: string[], preferred: string): string {
  return ids.includes(preferred) ? preferred : ids[0] ?? "";
}

function batchStateLabel(batch: TemporaryBatchAudit): string {
  if (batch.revoked_at || batch.state === "revoked") return "已撤銷";
  if (batch.state === "expired") return "已到期";
  if (batch.first_used_at || batch.state === "active") return "使用中";
  return "尚未啟用";
}

function stateLabel(state: string): string {
  if (state === "active") return "使用中";
  if (state === "expired") return "已到期";
  if (state === "revoked") return "已撤銷";
  return "尚未啟用";
}

function dateLabel(value?: string | null): string {
  return value ? new Date(value).toLocaleString("zh-TW") : "—";
}

function remainingLabel(seconds: number | null): string {
  if (seconds === null) return "尚未計時";
  const minutes = Math.max(0, Math.ceil(seconds / 60));
  const hours = Math.floor(minutes / 60);
  return hours > 0 ? `剩餘 ${hours} 小時 ${minutes % 60} 分` : `剩餘 ${minutes} 分`;
}

export default function TemporaryBatchPanel() {
  const [projects, setProjects] = useState<AccountAccessOption[]>([]);
  const [characters, setCharacters] = useState<AccountAccessOption[]>([]);
  const [voiceOptions, setVoiceOptions] = useState<VoiceOption[]>([]);
  const [selectedProjects, setSelectedProjects] = useState<string[]>([]);
  const [selectedCharacters, setSelectedCharacters] = useState<string[]>([]);
  const [selectedVoices, setSelectedVoices] = useState<string[]>([]);
  const [defaultProject, setDefaultProject] = useState("");
  const [defaultCharacter, setDefaultCharacter] = useState("");
  const [defaultVoiceKey, setDefaultVoiceKey] = useState("");
  const [batches, setBatches] = useState<TemporaryBatchAudit[]>([]);
  const [result, setResult] = useState<TemporaryBatchResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [revoking, setRevoking] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  const voiceByKey = useMemo(
    () => new Map(voiceOptions.map((option) => [`${option.provider}:${option.voice}`, option])),
    [voiceOptions],
  );

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setProjects([]);
    setCharacters([]);
    setVoiceOptions([]);
    setSelectedProjects([]);
    setSelectedCharacters([]);
    setSelectedVoices([]);
    setDefaultProject("");
    setDefaultCharacter("");
    setDefaultVoiceKey("");
    setBatches([]);
    const [optionsResult, batchesResult] = await Promise.allSettled([
      fetchAccountAccessOptions(),
      listTemporaryBatches(),
    ]);

    if (optionsResult.status === "fulfilled") {
      const projectItems = optionsResult.value.projects;
      const first = preferredId(
        projectItems.map((item) => item.id),
        PREFERRED_PROJECT,
      );
      setProjects(projectItems);
      setSelectedProjects(first ? [first] : []);
      setDefaultProject(first);

      const characterItems = optionsResult.value.avatar_characters;
      const firstCharacter = preferredId(
        characterItems.map((item) => item.id),
        PREFERRED_CHARACTER,
      );
      setCharacters(characterItems);
      setSelectedCharacters(firstCharacter ? [firstCharacter] : []);
      setDefaultCharacter(firstCharacter);

      const items = optionsResult.value.custom_voices.map((item) => ({
        provider: item.provider ?? "indextts",
        voice: item.id,
      }));
      const preferred = items.find((item) => item.voice === PREFERRED_VOICE)
        ?? items[0];
      const firstKey = preferred ? `${preferred.provider}:${preferred.voice}` : "";
      setVoiceOptions(items);
      setSelectedVoices(preferred ? [preferred.voice] : []);
      setDefaultVoiceKey(firstKey);
    }
    if (batchesResult.status === "fulfilled") setBatches(batchesResult.value);

    const failures = [optionsResult, batchesResult]
      .filter((item) => item.status === "rejected");
    if (failures.length > 0) {
      setError("部分授權資源或批次紀錄無法載入，請重新整理後再試。");
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  function toggle(
    id: string,
    selected: string[],
    setSelected: (next: string[]) => void,
    currentDefault: string,
    setDefault: (next: string) => void,
  ) {
    const next = selected.includes(id)
      ? selected.filter((item) => item !== id)
      : [...selected, id];
    setSelected(next);
    if (!next.includes(currentDefault)) setDefault(next[0] ?? "");
  }

  function toggleVoice(option: VoiceOption) {
    const key = `${option.provider}:${option.voice}`;
    const next = selectedVoices.includes(option.voice)
      ? selectedVoices.filter((voice) => voice !== option.voice)
      : [...selectedVoices, option.voice];
    setSelectedVoices(next);
    if (!next.includes(voiceByKey.get(defaultVoiceKey)?.voice ?? "")) {
      const fallback = voiceOptions.find((item) => next.includes(item.voice));
      setDefaultVoiceKey(fallback ? `${fallback.provider}:${fallback.voice}` : "");
    } else if (!defaultVoiceKey) {
      setDefaultVoiceKey(key);
    }
  }

  async function generateBatch() {
    const defaultVoice = voiceByKey.get(defaultVoiceKey);
    if (
      selectedProjects.length === 0
      || selectedCharacters.length === 0
      || selectedVoices.length === 0
      || !defaultProject
      || !defaultCharacter
      || !defaultVoice
    ) {
      setError("每一類至少選擇一項授權資源，並指定登入後預設值。");
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      const created = await createTemporaryBatch({
        grants: {
          projects: selectedProjects,
          avatar_characters: selectedCharacters,
          custom_voices: selectedVoices,
        },
        defaults: {
          project_id: defaultProject,
          character_id: defaultCharacter,
          voice_provider: defaultVoice.provider,
          voice_id: defaultVoice.voice,
        },
      });
      setResult(created);
      try {
        setBatches(await listTemporaryBatches());
      } catch {
        setError("帳號已成功產生，但批次紀錄暫時無法更新。請先保存下方密碼。");
      }
    } catch (reason) {
      setError(messageFrom(reason, "無法產生臨時帳號"));
    } finally {
      setSubmitting(false);
    }
  }

  async function copy(value: string, key: string) {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(key);
      window.setTimeout(() => setCopied((current) => current === key ? null : current), 2500);
    } catch {
      setError("無法寫入剪貼簿，請手動複製密碼。");
    }
  }

  async function revoke(batchId: string) {
    setRevoking(batchId);
    setError(null);
    try {
      const updated = await revokeTemporaryBatch(batchId);
      setBatches((current) => current.map(
        (batch) => batch.batch_id === batchId ? updated : batch,
      ));
    } catch (reason) {
      setError(messageFrom(reason, "撤銷批次失敗"));
    } finally {
      setRevoking(null);
    }
  }

  return (
    <section className="card mb-6 overflow-hidden">
      <header className="flex flex-col gap-3 border-b border-border px-5 py-4 md:flex-row md:items-start md:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-base font-semibold">臨時帳號批次</h2>
            <span className="chip">每批固定 5 組</span>
          </div>
          <p className="mt-1 text-sm text-content-muted">
            密碼在首次登入後啟動 72 小時效期；請先選擇這批帳號可使用的資源。
          </p>
        </div>
        <button className="btn btn-ghost self-start" type="button" onClick={() => void load()} disabled={loading}>
          重新整理資源
        </button>
      </header>

      {error && (
        <div className="mx-5 mt-5 rounded-md border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger" role="alert">
          {error}
        </div>
      )}

      <div className="grid gap-0 lg:grid-cols-[1.15fr_1fr_0.85fr]">
        <ResourceGroup
          title="知識庫專案"
          description="選取這批帳號可查詢的專案。"
          loading={loading}
          empty={projects.length === 0}
          footer={(
            <DefaultSelect
              label="登入後預設專案"
              value={defaultProject}
              onChange={setDefaultProject}
              options={projects
                .filter((item) => selectedProjects.includes(item.id))
                .map((item) => ({ value: item.id, label: item.label }))}
            />
          )}
        >
          {projects.map((project) => (
            <Choice
              key={project.id}
              checked={selectedProjects.includes(project.id)}
              label={project.label}
              detail={project.id}
              onChange={() => toggle(
                project.id,
                selectedProjects,
                setSelectedProjects,
                defaultProject,
                setDefaultProject,
              )}
            />
          ))}
        </ResourceGroup>

        <ResourceGroup
          title="虛擬人物"
          description="僅顯示素材完整、可以播放的人物。"
          loading={loading}
          empty={characters.length === 0}
          footer={(
            <DefaultSelect
              label="登入後預設人物"
              value={defaultCharacter}
              onChange={setDefaultCharacter}
              options={characters
                .filter((item) => selectedCharacters.includes(item.id))
                .map((item) => ({ value: item.id, label: item.label }))}
            />
          )}
        >
          {characters.map((character) => (
            <Choice
              key={character.id}
              checked={selectedCharacters.includes(character.id)}
              label={character.label}
              detail={character.id}
              onChange={() => toggle(
                character.id,
                selectedCharacters,
                setSelectedCharacters,
                defaultCharacter,
                setDefaultCharacter,
              )}
            />
          ))}
        </ResourceGroup>

        <ResourceGroup
          title="自訂聲音"
          description="授權可使用的 provider 與 voice。"
          loading={loading}
          empty={voiceOptions.length === 0}
          last
          footer={(
            <DefaultSelect
              label="登入後預設聲音"
              value={defaultVoiceKey}
              onChange={setDefaultVoiceKey}
              options={voiceOptions
                .filter((item) => selectedVoices.includes(item.voice))
                .map((item) => ({
                  value: `${item.provider}:${item.voice}`,
                  label: `${item.voice} · ${item.provider}`,
                }))}
            />
          )}
        >
          {voiceOptions.map((option) => (
            <Choice
              key={`${option.provider}:${option.voice}`}
              checked={selectedVoices.includes(option.voice)}
              label={option.voice}
              detail={option.provider}
              onChange={() => toggleVoice(option)}
            />
          ))}
        </ResourceGroup>
      </div>

      <div className="flex flex-col gap-3 border-t border-border bg-surface-sunken px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-xs text-content-muted">偏好值不可用時，已自動改用目前授權清單的第一項。</p>
        <button className="btn btn-primary" type="button" onClick={() => void generateBatch()} disabled={loading || submitting}>
          {submitting ? "產生中…" : "產生 5 組帳號"}
        </button>
      </div>

      {result && (
        <section className="border-t border-border px-5 py-5" aria-labelledby="temporary-result-title">
          <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
            <div>
              <h3 id="temporary-result-title" className="font-semibold">本次臨時密碼</h3>
              <p className="mt-1 text-sm font-medium text-warn">
                明碼只顯示這一次，離開或重新整理後無法再次查詢。
              </p>
            </div>
            <button
              className="btn btn-ghost self-start"
              type="button"
              onClick={() => void copy(
                result.credentials.map((item) => item.password).join("\n"),
                "all",
              )}
            >
              {copied === "all" ? "已複製全部" : "複製全部"}
            </button>
          </div>
          <div className="mt-4 divide-y divide-border border-y border-border">
            {result.credentials.map((credential, index) => (
              <div key={credential.user_id} className="grid gap-2 py-3 sm:grid-cols-[auto_1fr_auto] sm:items-center">
                <span className="text-xs text-content-subtle">{String(index + 1).padStart(2, "0")}</span>
                <code className="break-all font-mono text-sm">{credential.password}</code>
                <button
                  className="btn btn-ghost justify-self-start sm:justify-self-end"
                  type="button"
                  onClick={() => void copy(credential.password, credential.user_id)}
                >
                  {copied === credential.user_id ? "已複製" : "複製密碼"}
                </button>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="border-t border-border" aria-labelledby="temporary-history-title">
        <div className="px-5 py-4">
          <h3 id="temporary-history-title" className="font-semibold">批次紀錄</h3>
          <p className="mt-1 text-xs text-content-muted">歷史紀錄只保留狀態與到期資訊，不保存也不回傳密碼明碼。</p>
        </div>
        <div className="divide-y divide-border border-t border-border">
          {batches.map((batch) => {
            const revoked = Boolean(batch.revoked_at || batch.state === "revoked");
            return (
              <article key={batch.batch_id} className="px-5 py-4">
                <div className="flex flex-col gap-3 md:flex-row md:items-center">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <code className="truncate font-mono text-sm">{batch.batch_id}</code>
                      <span className="chip">{batchStateLabel(batch)}</span>
                      <span className="text-xs text-content-subtle">{batch.account_count ?? 5} 組</span>
                    </div>
                    <p className="mt-1 text-xs text-content-muted">
                      建立 {dateLabel(batch.created_at)} · 到期 {dateLabel(batch.expires_at)}
                    </p>
                  </div>
                  <button
                    className="btn btn-danger self-start md:self-auto"
                    type="button"
                    disabled={revoked || revoking === batch.batch_id}
                    onClick={() => {
                      if (!window.confirm("確定撤銷這一批臨時帳號的剩餘存取權？")) return;
                      void revoke(batch.batch_id);
                    }}
                  >
                    {revoking === batch.batch_id ? "撤銷中…" : revoked ? "已撤銷" : "撤銷整批"}
                  </button>
                </div>
                {batch.accounts && batch.accounts.length > 0 && (
                  <div className="mt-3 grid gap-x-5 gap-y-2 border-t border-border pt-3 sm:grid-cols-2 xl:grid-cols-3">
                    {batch.accounts.map((account) => (
                      <div key={account.user_id} className="flex min-w-0 items-center justify-between gap-3 text-xs">
                        <span className="min-w-0">
                          <span className="block truncate text-content-muted">{account.username}</span>
                          <span className="block text-content-subtle">{remainingLabel(account.remaining_seconds)}</span>
                        </span>
                        <span className="chip shrink-0">{stateLabel(account.state)}</span>
                      </div>
                    ))}
                  </div>
                )}
              </article>
            );
          })}
          {!loading && batches.length === 0 && (
            <p className="px-5 py-6 text-center text-sm text-content-muted">尚無臨時帳號批次</p>
          )}
        </div>
      </section>
    </section>
  );
}

function ResourceGroup({
  title,
  description,
  loading,
  empty,
  footer,
  last = false,
  children,
}: {
  title: string;
  description: string;
  loading: boolean;
  empty: boolean;
  footer: ReactNode;
  last?: boolean;
  children: ReactNode;
}) {
  return (
    <fieldset className={`min-w-0 px-5 py-5 ${last ? "" : "border-b border-border lg:border-b-0 lg:border-r"}`}>
      <legend className="font-semibold">{title}</legend>
      <p className="mt-1 text-xs text-content-muted">{description}</p>
      <div className="mt-4 max-h-56 space-y-2 overflow-y-auto pr-1">
        {children}
        {loading && <p className="text-sm text-content-muted" role="status">載入中…</p>}
        {!loading && empty && <p className="text-sm text-content-muted">目前沒有可授權項目</p>}
      </div>
      {footer}
    </fieldset>
  );
}

function Choice({
  checked,
  label,
  detail,
  onChange,
}: {
  checked: boolean;
  label: string;
  detail: string;
  onChange: () => void;
}) {
  return (
    <label className="flex min-h-11 cursor-pointer items-center gap-3 border-b border-border px-2 py-2 last:border-b-0 hover:bg-surface-sunken">
      <input className="h-4 w-4 accent-primary" type="checkbox" checked={checked} onChange={onChange} />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium">{label}</span>
        <span className="block truncate text-xs text-content-subtle">{detail}</span>
      </span>
    </label>
  );
}

function DefaultSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: Array<{ value: string; label: string }>;
}) {
  return (
    <label className="mt-4 block border-t border-border pt-4 text-xs font-medium text-content-muted">
      {label}
      <select className="input mt-2" value={value} onChange={(event) => onChange(event.target.value)} disabled={options.length === 0}>
        {options.length === 0 && <option value="">尚未選擇授權</option>}
        {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
      </select>
    </label>
  );
}
