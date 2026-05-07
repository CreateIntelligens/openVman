import { useEffect, useMemo, useState } from "react";
import {
  createEmbedKey,
  disableEmbedKey,
  enableEmbedKey,
  listEmbedKeys,
  updateEmbedKey,
  type EmbedKeyRecord,
} from "../api";
import StatusAlert from "../components/StatusAlert";

type Drafts = Record<string, { domains: string; note: string }>;
const KEY_GRID_CLASS = [
  "grid",
  "grid-cols-[minmax(13rem,1.1fr)_minmax(10rem,0.7fr)_minmax(14rem,1fr)_minmax(10rem,0.8fr)_auto]",
  "gap-3",
].join(" ");

function parseDomains(value: string): string[] {
  return value
    .split(/[,\n]/)
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean);
}

function domainsText(domains: string[]): string {
  return domains.join("\n");
}

function draftIsDirty(
  draft: { domains: string; note: string },
  record: EmbedKeyRecord,
): boolean {
  const draftDomains = [...parseDomains(draft.domains)].sort().join(",");
  const recordDomains = [...record.allowed_domains].sort().join(",");
  return draftDomains !== recordDomains || draft.note.trim() !== record.note;
}

export default function EmbedKeys() {
  const [keys, setKeys] = useState<EmbedKeyRecord[]>([]);
  const [drafts, setDrafts] = useState<Drafts>({});
  const [tenantId, setTenantId] = useState("default");
  const [domains, setDomains] = useState("");
  const [note, setNote] = useState("");
  const [oneTimeSecret, setOneTimeSecret] = useState<{ keyId: string; secret: string } | null>(null);
  const [loading, setLoading] = useState(false);
  const [rowStatus, setRowStatus] = useState<{ keyId: string; kind: "saving" | "saved" } | null>(null);
  const [error, setError] = useState("");

  const activeCount = useMemo(() => keys.filter((key) => key.enabled).length, [keys]);
  const createDomains = useMemo(() => parseDomains(domains), [domains]);
  const canCreate = tenantId.trim().length > 0 && createDomains.length > 0;

  async function load() {
    setError("");
    setLoading(true);
    try {
      const payload = await listEmbedKeys();
      setKeys(payload.keys);
      setDrafts(Object.fromEntries(
        payload.keys.map((key) => [
          key.key_id,
          { domains: domainsText(key.allowed_domains), note: key.note },
        ]),
      ));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load embed keys");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function handleCreate() {
    if (!canCreate) return;
    setError("");
    setLoading(true);
    try {
      const created = await createEmbedKey({
        tenant_id: tenantId.trim(),
        allowed_domains: createDomains,
        note: note.trim(),
      });
      setOneTimeSecret({ keyId: created.record.key_id, secret: created.secret });
      setTenantId("default");
      setDomains("");
      setNote("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create embed key");
    } finally {
      setLoading(false);
    }
  }

  async function handleSave(keyId: string) {
    const draft = drafts[keyId];
    if (!draft) return;
    setRowStatus({ keyId, kind: "saving" });
    setError("");
    try {
      const updated = await updateEmbedKey(keyId, {
        allowed_domains: parseDomains(draft.domains),
        note: draft.note.trim(),
      });
      setKeys((current) => current.map((key) => (key.key_id === keyId ? updated : key)));
      setDrafts((current) => ({
        ...current,
        [keyId]: { domains: domainsText(updated.allowed_domains), note: updated.note },
      }));
      setRowStatus({ keyId, kind: "saved" });
      window.setTimeout(() => {
        setRowStatus((current) => (current?.keyId === keyId && current.kind === "saved" ? null : current));
      }, 2500);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save embed key");
      setRowStatus(null);
    }
  }

  async function handleDisable(keyId: string) {
    setRowStatus({ keyId, kind: "saving" });
    setError("");
    try {
      const disabled = await disableEmbedKey(keyId);
      setKeys((current) => current.map((key) => (key.key_id === keyId ? disabled : key)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to disable embed key");
    } finally {
      setRowStatus(null);
    }
  }

  async function handleEnable(keyId: string) {
    setRowStatus({ keyId, kind: "saving" });
    setError("");
    try {
      const enabled = await enableEmbedKey(keyId);
      setKeys((current) => current.map((key) => (key.key_id === keyId ? enabled : key)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to enable embed key");
    } finally {
      setRowStatus(null);
    }
  }

  async function copySecret() {
    if (!oneTimeSecret) return;
    const text = oneTimeSecret.secret;
    if (navigator.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(text);
        return;
      } catch {
        // fall through to textarea fallback
      }
    }
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.appendChild(textarea);
    textarea.select();
    try {
      document.execCommand("copy");
    } finally {
      document.body.removeChild(textarea);
    }
  }

  return (
    <div className="page-scroll">
      <div className="p-8">
        <header className="page-header">
          <div>
            <h2 className="page-title">Embed Keys</h2>
            <p className="page-subtitle">Manage public iframe API keys and domain allowlists.</p>
          </div>
          <button className="btn btn-ghost" onClick={load} disabled={loading}>
            <span className="material-symbols-outlined text-[1rem]">refresh</span>
            Refresh
          </button>
        </header>

        {error && <StatusAlert type="error" message={error} />}

        {oneTimeSecret && (
          <section className="mb-6 rounded-lg border border-amber-300 bg-amber-50 p-4 text-amber-950 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-100">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div>
                <p className="text-sm font-semibold">One-time secret for {oneTimeSecret.keyId}</p>
                <p className="text-xs opacity-75">Store it now. It will not appear in the list again.</p>
              </div>
              <button className="btn btn-ghost" onClick={copySecret}>
                <span className="material-symbols-outlined text-[1rem]">content_copy</span>
                Copy
              </button>
            </div>
            <code className="block overflow-x-auto rounded-md bg-white/70 px-3 py-2 text-xs dark:bg-black/20">
              {oneTimeSecret.secret}
            </code>
          </section>
        )}

        <section className="mb-6 rounded-lg border border-border bg-surface-raised p-5">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h3 className="text-base font-semibold">Create Key</h3>
              <p className="text-sm text-content-muted">Allowed domains accept comma or newline separated hostnames.</p>
            </div>
            <span className="chip">{activeCount} active</span>
          </div>
          <div className="grid gap-3 lg:grid-cols-[minmax(10rem,14rem)_minmax(16rem,1fr)_minmax(12rem,18rem)_auto]">
            <input className="input" value={tenantId} onChange={(event) => setTenantId(event.target.value)} placeholder="tenant_id" />
            <textarea className="input min-h-20 resize-y" value={domains} onChange={(event) => setDomains(event.target.value)} placeholder="example.com&#10;docs.example.com" />
            <input className="input" value={note} onChange={(event) => setNote(event.target.value)} placeholder="note" />
            <button className="btn btn-primary self-start" onClick={handleCreate} disabled={loading || !canCreate}>
              <span className="material-symbols-outlined text-[1rem]">add</span>
              Create
            </button>
          </div>
        </section>

        <section className="overflow-hidden rounded-lg border border-border bg-surface-raised">
          <div className={`${KEY_GRID_CLASS} border-b border-border bg-surface-sunken px-4 py-3 text-xs font-semibold uppercase tracking-wide text-content-muted`}>
            <span>Key</span>
            <span>Tenant</span>
            <span>Allowed Domains</span>
            <span>Note</span>
            <span>Actions</span>
          </div>
          <div className="divide-y divide-border">
            {keys.map((key) => {
              const draft = drafts[key.key_id] ?? { domains: domainsText(key.allowed_domains), note: key.note };
              const dirty = draftIsDirty(draft, key);
              const isSaving = rowStatus?.keyId === key.key_id && rowStatus.kind === "saving";
              const justSaved = rowStatus?.keyId === key.key_id && rowStatus.kind === "saved";
              return (
                <div key={key.key_id} className={`${KEY_GRID_CLASS} px-4 py-3`}>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className={`h-2 w-2 rounded-full ${key.enabled ? "bg-success" : "bg-content-subtle"}`} />
                      <code className="truncate text-xs font-semibold">{key.key_id}</code>
                    </div>
                    <p className="mt-1 truncate text-xs text-content-subtle">{key.secret_hash}</p>
                  </div>
                  <span className="truncate text-sm">{key.tenant_id}</span>
                  <textarea
                    className="input min-h-20 resize-y"
                    value={draft.domains}
                    disabled={!key.enabled}
                    onChange={(event) => setDrafts((current) => ({
                      ...current,
                      [key.key_id]: { ...draft, domains: event.target.value },
                    }))}
                  />
                  <input
                    className="input"
                    value={draft.note}
                    disabled={!key.enabled}
                    onChange={(event) => setDrafts((current) => ({
                      ...current,
                      [key.key_id]: { ...draft, note: event.target.value },
                    }))}
                  />
                  <div className="flex items-start gap-2">
                    <button
                      className="btn btn-ghost"
                      disabled={!key.enabled || !dirty || isSaving}
                      onClick={() => void handleSave(key.key_id)}
                    >
                      <span className="material-symbols-outlined text-[1rem]">
                        {justSaved ? "check" : "save"}
                      </span>
                      {isSaving ? "Saving…" : justSaved ? "Saved" : "Save"}
                    </button>
                    {key.enabled ? (
                      <button className="btn btn-danger" disabled={isSaving} onClick={() => void handleDisable(key.key_id)}>
                        <span className="material-symbols-outlined text-[1rem]">block</span>
                        Disable
                      </button>
                    ) : (
                      <button className="btn btn-ghost" disabled={isSaving} onClick={() => void handleEnable(key.key_id)}>
                        <span className="material-symbols-outlined text-[1rem]">restart_alt</span>
                        Re-enable
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
            {keys.length === 0 && (
              <div className="px-4 py-10 text-center text-sm text-content-muted">
                No embed keys yet.
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
