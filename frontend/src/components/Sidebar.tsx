import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import type { Client } from "../types";

interface Props {
  clientId?: string;
}

const COLLAPSE_KEY = "ir-sidebar-collapsed";
const SCOPE_KEY = "ir-client-scope";

const SLUG_RE = /^[a-z0-9-]+$/;

function monogram(name: string): string {
  return name.split(/\s+/).map(w => w[0]).join("").slice(0, 2).toUpperCase();
}

interface ClientDrawerProps {
  mode: "create" | "edit";
  initial?: Client;
  onClose: () => void;
  onSaved: (id: string) => void;
}

function ClientDrawer({ mode, initial, onClose, onSaved }: ClientDrawerProps) {
  const qc = useQueryClient();
  const isEdit = mode === "edit";
  const [id, setId] = useState(initial?.id ?? "");
  const [name, setName] = useState(initial?.name ?? "");
  const [sector, setSector] = useState(initial?.sector ?? "");
  const [oneLiner, setOneLiner] = useState(initial?.one_liner ?? "");
  const [founderName, setFounderName] = useState(initial?.founder_name ?? "");
  const [founderHandle, setFounderHandle] = useState(initial?.founder_handle ?? "");
  const [aliases, setAliases] = useState((initial?.aliases ?? []).join(", "));
  const [notes, setNotes] = useState(initial?.notes ?? "");
  const [yamlContent, setYamlContent] = useState("");
  const [inputMode, setInputMode] = useState<"form" | "yaml">("form");
  const [error, setError] = useState("");

  // Danger zone: clear all client data.
  const [showClear, setShowClear] = useState(false);
  const [clearConfirm, setClearConfirm] = useState("");
  const [clearMsg, setClearMsg] = useState("");
  const clearValid =
    !!initial &&
    (clearConfirm.trim() === initial.name.trim() ||
      clearConfirm.trim().toUpperCase() === "ОЧИСТИТЬ");

  const clearMut = useMutation({
    mutationFn: () => api.clearClientData(initial!.id),
    onSuccess: (res) => {
      const d = res.deleted || {};
      const parts = Object.entries(d)
        .filter(([, v]) => (v as number) > 0)
        .map(([k, v]) => `${k}: ${v}`);
      setClearMsg(
        parts.length
          ? `Данные клиента очищены — ${parts.join(", ")}.`
          : "Данные клиента очищены (всё уже было пусто).",
      );
      setShowClear(false);
      setClearConfirm("");
      // Invalidate every view that depends on client data.
      qc.invalidateQueries({ queryKey: ["matrix", initial!.id] });
      qc.invalidateQueries({ queryKey: ["punch", initial!.id] });
      qc.invalidateQueries({ queryKey: ["scorecard", initial!.id] });
      qc.invalidateQueries({ queryKey: ["facts", initial!.id] });
      qc.invalidateQueries({ queryKey: ["work-items", initial!.id] });
      qc.invalidateQueries({ queryKey: ["backups", initial!.id] });
    },
    onError: (e: Error) => setError(e.message),
  });

  // Backups: list + restore (danger-zone recovery).
  const backupsQ = useQuery({
    queryKey: ["backups", initial?.id],
    queryFn: () => api.listBackups(initial!.id),
    enabled: isEdit && !!initial,
  });
  const [restoreConfirmId, setRestoreConfirmId] = useState<string | null>(null);
  const restoreMut = useMutation({
    mutationFn: (backupId: string) => api.restoreClient(initial!.id, backupId),
    onSuccess: (res) => {
      const r = res.restored || {};
      const parts = Object.entries(r)
        .filter(([, v]) => (v as number) > 0)
        .map(([k, v]) => `${k}: ${v}`);
      setClearMsg(
        parts.length
          ? `Данные восстановлены из бэкапа — ${parts.join(", ")}.`
          : "Бэкап восстановлен (был пустым).",
      );
      setRestoreConfirmId(null);
      qc.invalidateQueries({ queryKey: ["matrix", initial!.id] });
      qc.invalidateQueries({ queryKey: ["punch", initial!.id] });
      qc.invalidateQueries({ queryKey: ["scorecard", initial!.id] });
      qc.invalidateQueries({ queryKey: ["facts", initial!.id] });
      qc.invalidateQueries({ queryKey: ["work-items", initial!.id] });
    },
    onError: (e: Error) => setError(e.message),
  });

  const saveMut = useMutation({
    mutationFn: async () => {
      setError("");
      if (!isEdit && inputMode === "yaml") {
        const lines = yamlContent.split("\n");
        const idLine = lines.find(l => l.trim().startsWith("id:"));
        const parsedId = idLine ? idLine.split(":")[1].trim() : "";
        if (!parsedId) throw new Error("YAML must contain client.id");
        await api.upsertClient({ id: parsedId, name: parsedId });
        return api.importSeedYaml(parsedId, yamlContent);
      }

      const aliasList = aliases.split(",").map(a => a.trim()).filter(Boolean);
      const payload = {
        name,
        sector: sector || undefined,
        one_liner: oneLiner || undefined,
        founder_name: founderName || undefined,
        founder_handle: founderHandle || undefined,
        aliases: aliasList,
        notes: notes || undefined,
      };

      if (isEdit) {
        if (!name.trim()) throw new Error("Name is required");
        await api.patchClient(initial!.id, payload);
        return { client_id: initial!.id };
      }

      if (!SLUG_RE.test(id)) throw new Error("ID: only lowercase letters, digits, hyphens");
      if (!name.trim()) throw new Error("Name is required");
      await api.upsertClient({ id, ...payload });
      return { client_id: id };
    },
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ["clients"] });
      if (isEdit && initial) {
        qc.invalidateQueries({ queryKey: ["client", initial.id] });
      }
      onSaved((result as { client_id: string }).client_id);
    },
    onError: (e: Error) => setError(e.message),
  });

  return (
    <div className="fixed inset-0 z-50 flex">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
      <div className="relative ml-auto w-[420px] h-full bg-white shadow-xl flex flex-col">
        <div className="px-5 py-4 border-b border-ink-line flex items-center justify-between">
          <h2 className="text-sm font-semibold">{isEdit ? "Edit client" : "New client"}</h2>
          <button onClick={onClose} className="text-ink-mute hover:text-ink text-lg leading-none">×</button>
        </div>

        {isEdit && initial && (initial.created_at || initial.created_by) && (
          <div className="px-5 py-2 bg-slate-50 border-b border-ink-line text-xs text-ink-mute font-mono leading-snug">
            <div>Created: {(initial.created_at ?? "—").slice(0, 19).replace("T", " ")}</div>
            <div>Created by: {initial.created_by ?? "—"}</div>
          </div>
        )}

        {!isEdit && (
          <div className="flex border-b border-ink-line text-xs">
            <button
              onClick={() => setInputMode("form")}
              className={`px-4 py-2 border-b-2 transition ${inputMode === "form" ? "border-ink font-medium" : "border-transparent text-ink-mute"}`}
            >Manual</button>
            <button
              onClick={() => setInputMode("yaml")}
              className={`px-4 py-2 border-b-2 transition ${inputMode === "yaml" ? "border-ink font-medium" : "border-transparent text-ink-mute"}`}
            >Import YAML</button>
          </div>
        )}

        <div className="flex-1 overflow-y-auto p-5 space-y-3">
          {(isEdit || inputMode === "form") ? (
            <>
              <Field label="ID (slug)" required={!isEdit}>
                <input
                  value={id}
                  onChange={e => !isEdit && setId(e.target.value.toLowerCase())}
                  placeholder="acme-inc"
                  readOnly={isEdit}
                  title={isEdit ? "Slug cannot be changed — it is referenced by all related rows" : undefined}
                  className={`${input} ${isEdit ? "bg-slate-50 text-ink-mute cursor-not-allowed" : ""}`}
                />
              </Field>
              <Field label="Name" required>
                <input value={name} onChange={e => setName(e.target.value)}
                  placeholder="Acme Inc." className={input} />
              </Field>
              <Field label="Sector">
                <input value={sector} onChange={e => setSector(e.target.value)}
                  placeholder="fintech" className={input} />
              </Field>
              <Field label="One-liner">
                <input value={oneLiner} onChange={e => setOneLiner(e.target.value)}
                  placeholder="What they do in one sentence" className={input} />
              </Field>
              <Field label="Founder name">
                <input value={founderName} onChange={e => setFounderName(e.target.value)}
                  placeholder="Jane Smith" className={input} />
              </Field>
              <Field label="Founder handle">
                <input value={founderHandle} onChange={e => setFounderHandle(e.target.value)}
                  placeholder="@janesmith" className={input} />
              </Field>
              <Field label="Aliases (comma-separated)">
                <input value={aliases} onChange={e => setAliases(e.target.value)}
                  placeholder="Acme, ACM, Acme Corp" className={input} />
              </Field>
              <Field label="Notes">
                <textarea value={notes} onChange={e => setNotes(e.target.value)}
                  placeholder="Internal notes" rows={4}
                  className={`${input} resize-none`} />
              </Field>
            </>
          ) : (
            <Field label="Paste seed YAML">
              <textarea
                value={yamlContent}
                onChange={e => setYamlContent(e.target.value)}
                rows={18}
                className={`${input} font-mono text-xs resize-none`}
                placeholder={"client:\n  id: acme-inc\n  name: Acme Inc.\n  sector: saas\n..."}
              />
            </Field>
          )}

          {error && <div className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{error}</div>}

          {isEdit && initial && (
            <div className="mt-4 border border-red-200 rounded-lg bg-red-50/40 p-3 space-y-2">
              <div className="text-xs font-semibold uppercase tracking-wide text-red-700">
                Danger zone
              </div>
              {clearMsg && (
                <div className="text-xs text-emerald-700 bg-emerald-50 rounded px-2 py-1.5">
                  {clearMsg}
                </div>
              )}
              {!showClear ? (
                <>
                  <p className="text-xs text-ink-mute leading-snug">
                    Удалить все данные клиента: факты, источники, ingest-историю,
                    work-items, планы, артефакты и заметки. Матрица сбрасывается
                    в пустую. Сам клиент остаётся. Кэши транскриптов (общие между
                    клиентами) не трогаются.
                  </p>
                  <p className="text-xs text-emerald-700 leading-snug">
                    Будет создан автоматический бэкап — данные можно восстановить.
                  </p>
                  <button
                    type="button"
                    onClick={() => { setShowClear(true); setClearMsg(""); }}
                    className="text-xs px-3 py-1.5 border border-red-400 text-red-700 rounded hover:bg-red-100"
                  >
                    Очистить данные клиента…
                  </button>
                </>
              ) : (
                <div className="space-y-2">
                  <p className="text-xs text-ink-mute leading-snug">
                    Для подтверждения введите имя клиента
                    {" "}<span className="font-mono font-medium">{initial.name}</span>{" "}
                    или слово <span className="font-mono font-medium">ОЧИСТИТЬ</span>.
                  </p>
                  <input
                    value={clearConfirm}
                    onChange={e => setClearConfirm(e.target.value)}
                    placeholder={initial.name}
                    className={`${input} ${clearConfirm && !clearValid ? "border-red-400" : ""}`}
                    autoFocus
                  />
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => clearMut.mutate()}
                      disabled={!clearValid || clearMut.isPending}
                      className="text-xs px-3 py-1.5 bg-red-600 text-white rounded hover:bg-red-700 disabled:opacity-50"
                    >
                      {clearMut.isPending ? "Очищаю…" : "Удалить все данные"}
                    </button>
                    <button
                      type="button"
                      onClick={() => { setShowClear(false); setClearConfirm(""); }}
                      className="text-xs px-3 py-1.5 border border-ink-line rounded hover:bg-slate-50"
                    >
                      Отмена
                    </button>
                  </div>
                </div>
              )}

              {/* Backups: list + restore */}
              {backupsQ.data && backupsQ.data.length > 0 && (
                <div className="pt-2 mt-2 border-t border-red-200 space-y-1.5">
                  <div className="text-xs font-semibold uppercase tracking-wide text-ink-mute">
                    Бэкапы
                  </div>
                  <ul className="space-y-1.5">
                    {backupsQ.data.map((b) => {
                      const factCount = b.counts?.facts ?? 0;
                      const total = Object.values(b.counts || {}).reduce(
                        (a, v) => a + (v as number), 0,
                      );
                      const when = b.created_at
                        ? new Date(b.created_at).toLocaleString()
                        : b.id;
                      return (
                        <li
                          key={b.id}
                          className="flex items-center justify-between gap-2 text-xs bg-white border border-ink-line rounded px-2 py-1.5"
                        >
                          <div className="min-w-0">
                            <div className="font-mono text-[11px] truncate">{when}</div>
                            <div className="text-ink-mute">
                              {factCount} фактов · {total} строк всего
                            </div>
                          </div>
                          {restoreConfirmId === b.id ? (
                            <div className="flex gap-1 shrink-0">
                              <button
                                type="button"
                                onClick={() => restoreMut.mutate(b.id)}
                                disabled={restoreMut.isPending}
                                className="px-2 py-1 bg-amber-600 text-white rounded hover:bg-amber-700 disabled:opacity-50"
                              >
                                {restoreMut.isPending ? "Восстанавливаю…" : "Точно?"}
                              </button>
                              <button
                                type="button"
                                onClick={() => setRestoreConfirmId(null)}
                                className="px-2 py-1 border border-ink-line rounded hover:bg-slate-50"
                              >
                                Нет
                              </button>
                            </div>
                          ) : (
                            <button
                              type="button"
                              onClick={() => { setRestoreConfirmId(b.id); setClearMsg(""); }}
                              className="shrink-0 px-2 py-1 border border-amber-400 text-amber-700 rounded hover:bg-amber-50"
                            >
                              Восстановить
                            </button>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                  <p className="text-[11px] text-ink-mute leading-snug">
                    Восстановление сначала очистит текущие данные клиента, затем
                    зальёт снимок из выбранного бэкапа.
                  </p>
                </div>
              )}
            </div>
          )}
        </div>

        <div className="px-5 py-4 border-t border-ink-line flex gap-2 justify-end">
          <button onClick={onClose}
            className="text-xs px-3 py-1.5 border border-ink-line rounded hover:bg-slate-50">
            Cancel
          </button>
          <button
            onClick={() => saveMut.mutate()}
            disabled={saveMut.isPending}
            className="text-xs px-3 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
          >
            {saveMut.isPending
              ? (isEdit ? "Saving…" : "Creating…")
              : (isEdit ? "Save" : "Create client")}
          </button>
        </div>
      </div>
    </div>
  );
}

const input = "w-full text-sm border border-ink-line rounded px-2 py-1.5";

function Field({ label, required, children }: { label: string; required?: boolean; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-xs font-medium text-ink-mute mb-1">
        {label}{required && <span className="text-red-500 ml-0.5">*</span>}
      </label>
      {children}
    </div>
  );
}

export default function Sidebar({ clientId }: Props) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const { tab } = useParams();
  const [showNewClient, setShowNewClient] = useState(false);
  const [editingClient, setEditingClient] = useState<Client | null>(null);
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    try { return localStorage.getItem(COLLAPSE_KEY) === "1"; } catch { return false; }
  });

  useEffect(() => {
    try { localStorage.setItem(COLLAPSE_KEY, collapsed ? "1" : "0"); } catch { /* noop */ }
  }, [collapsed]);

  // Auto-hide the clients column when a company is selected — the name moves to
  // the top bar, the workspace gets the room. Re-expand stays one click away.
  useEffect(() => {
    if (clientId) setCollapsed(true);
  }, [clientId]);

  const clients = useQuery({ queryKey: ["clients"], queryFn: api.listClients });
  const portfolio = useQuery({ queryKey: ["portfolio"], queryFn: api.clientsPortfolio });
  const covMap = new Map((portfolio.data ?? []).map(p => [p.id, p]));
  const me = useQuery({ queryKey: ["me"], queryFn: api.authMe, retry: false });
  const [scope, setScope] = useState<"mine" | "all">(() => {
    try { return localStorage.getItem(SCOPE_KEY) === "mine" ? "mine" : "all"; } catch { return "all"; }
  });
  useEffect(() => { try { localStorage.setItem(SCOPE_KEY, scope); } catch { /* noop */ } }, [scope]);

  const mineMut = useMutation({
    mutationFn: ({ id, on }: { id: string; on: boolean }) => api.setClientMine(id, on),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["portfolio"] }),
  });

  const seedAcc = useMutation({
    mutationFn: api.seedAccumulator,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["clients"] });
      nav("/clients/accumulator");
    },
  });

  if (collapsed) {
    return (
      <aside className="w-10 shrink-0 border-r border-ink-line bg-white flex flex-col items-center py-2">
        <button
          onClick={() => setCollapsed(false)}
          className="w-8 h-8 flex items-center justify-center rounded hover:bg-slate-100 text-ink-mute hover:text-ink"
          title="Expand client list"
          aria-label="Expand client list"
        >»</button>
      </aside>
    );
  }

  return (
    <>
      <aside className="w-60 shrink-0 border-r border-ink-line bg-white flex flex-col">
        <div className="px-3 py-2 border-b border-ink-line flex items-center justify-between">
          <div className="text-xs font-semibold uppercase text-ink-mute tracking-wide">Clients</div>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setShowNewClient(true)}
              className="text-xs text-blue-600 hover:text-blue-800 font-medium px-1"
              title="Add new client"
            >+ New</button>
            <button
              onClick={() => setCollapsed(true)}
              className="text-ink-mute hover:text-ink px-1 rounded hover:bg-slate-100"
              title="Collapse sidebar"
              aria-label="Collapse sidebar"
            >«</button>
          </div>
        </div>

        {me.data?.auth && (clients.data?.length ?? 0) > 0 && (
          <div className="px-3 py-2 border-b border-ink-line">
            <div className="flex items-center rounded-lg border border-ink-line overflow-hidden text-[11px]">
              <button
                onClick={() => setScope("mine")}
                className={`flex-1 py-1 transition ${scope === "mine" ? "bg-ink text-white font-medium" : "text-ink-mute hover:text-ink"}`}
              >Мои</button>
              <button
                onClick={() => setScope("all")}
                className={`flex-1 py-1 transition ${scope === "all" ? "bg-ink text-white font-medium" : "text-ink-mute hover:text-ink"}`}
              >Все</button>
            </div>
          </div>
        )}

        <div className="flex-1 overflow-y-auto px-2 py-2">
          {clients.isLoading && <div className="text-xs text-ink-mute px-1 py-1">Loading…</div>}
          {clients.data && clients.data.length === 0 && (
            <button
              onClick={() => seedAcc.mutate()}
              className="w-full text-left text-xs px-2 py-1.5 rounded hover:bg-slate-100 text-blue-600"
            >+ Загрузить пилот (Accumulator)</button>
          )}
          {(() => {
            const list = (clients.data ?? []).filter(
              c => scope === "all" || !me.data?.auth || covMap.get(c.id)?.mine);
            if (me.data?.auth && scope === "mine" && list.length === 0 && (clients.data?.length ?? 0) > 0) {
              return <div className="text-xs text-ink-mute px-2 py-2 leading-snug">
                Пока нет «моих». Отметь компанию звёздочкой ★ (наведи на строку) или переключись на «Все».
              </div>;
            }
            return (
              <ul className="space-y-1">
                {list.map(c => {
                  const active = clientId === c.id;
                  const p = covMap.get(c.id);
                  const pct = p && p.total ? Math.round((p.covered / p.total) * 100) : 0;
                  const mine = !!p?.mine;
                  return (
                    <li key={c.id} className="group relative">
                      <Link
                        to={`/clients/${c.id}/${tab ?? "matrix"}`}
                        className={`flex items-center gap-2.5 px-2 py-2 pr-12 rounded-lg transition
                          ${active ? "bg-ink/[0.06]" : "hover:bg-ink/[0.03]"}`}
                        title={c.name}
                      >
                        <span className={`w-7 h-7 shrink-0 rounded-lg flex items-center justify-center text-[11px] font-semibold select-none
                          ${active ? "bg-ink text-white" : "bg-ink/[0.06] text-ink"}`}>
                          {monogram(c.name)}
                        </span>
                        <div className="min-w-0 flex-1">
                          <div className={`text-[13px] truncate text-ink ${active ? "font-medium" : ""}`}>{c.name}</div>
                          <div className="flex items-center gap-1.5 mt-1">
                            <div className="h-1 flex-1 rounded-full bg-ink/[0.07] overflow-hidden">
                              <div className="h-full rounded-full bg-flag-green" style={{ width: `${pct}%` }} />
                            </div>
                            <span className="text-[10px] text-ink-mute tabular-nums w-7 text-right">{pct}%</span>
                          </div>
                        </div>
                      </Link>
                      {me.data?.auth && (
                        <button
                          onClick={(e) => { e.preventDefault(); mineMut.mutate({ id: c.id, on: !mine }); }}
                          className={`absolute right-7 top-2 transition px-1 py-0.5 rounded hover:bg-white
                            ${mine ? "text-amber-500 opacity-100" : "text-ink-mute opacity-0 group-hover:opacity-100 hover:text-ink"}`}
                          title={mine ? "Убрать из моих" : "В мои компании"}
                          aria-label={mine ? "Unstar" : "Star"}
                        >{mine ? "★" : "☆"}</button>
                      )}
                      <button
                        onClick={(e) => { e.preventDefault(); setEditingClient(c); }}
                        className="absolute right-1 top-2 opacity-0 group-hover:opacity-100 transition px-1.5 py-0.5 text-ink-mute hover:text-ink rounded hover:bg-white"
                        title="Edit client"
                        aria-label={`Edit ${c.name}`}
                      >✎</button>
                    </li>
                  );
                })}
              </ul>
            );
          })()}
        </div>
      </aside>

      {showNewClient && (
        <ClientDrawer
          mode="create"
          onClose={() => setShowNewClient(false)}
          onSaved={(id) => {
            setShowNewClient(false);
            nav(`/clients/${id}/matrix`);
          }}
        />
      )}
      {editingClient && (
        <ClientDrawer
          mode="edit"
          initial={editingClient}
          onClose={() => setEditingClient(null)}
          onSaved={() => setEditingClient(null)}
        />
      )}
    </>
  );
}
