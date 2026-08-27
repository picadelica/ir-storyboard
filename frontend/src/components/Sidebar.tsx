import { useEffect, useRef, useState, type ReactNode } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { HintTarget } from "./Hint";
import type { Client } from "../types";

interface Props {
  clientId?: string;
}

const COLLAPSE_KEY = "ir-sidebar-collapsed";
const SCOPE_KEY = "ir-client-scope";

const SLUG_RE = /^[a-z0-9-]+$/;

function monogram(name: string): string {
  return name
    .replace(/[^\p{L}\p{N}\s]/gu, " ")
    .split(/\s+/)
    .filter(Boolean)
    .map(w => w[0])
    .join("")
    .slice(0, 2)
    .toUpperCase() || "—";
}

function clientHintBody(client: Client): string {
  const sector = client.sector?.trim();
  const description = client.one_liner?.trim() || client.notes?.trim();
  if (sector && description) return `${sector} · ${description}`;
  if (description) return description;
  if (sector) return sector;
  return "";
}

function SidebarScrollArea({
  children,
  className = "",
  contentClassName = "",
}: {
  children: ReactNode;
  className?: string;
  contentClassName?: string;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [thumb, setThumb] = useState({ show: false, top: 0, height: 0 });

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const update = () => {
      const { scrollHeight, clientHeight, scrollTop } = el;
      const show = scrollHeight > clientHeight + 1;
      if (!show) {
        setThumb({ show: false, top: 0, height: 0 });
        return;
      }

      const height = Math.max(28, (clientHeight / scrollHeight) * clientHeight);
      const maxTop = clientHeight - height;
      const top = maxTop <= 0 ? 0 : (scrollTop / (scrollHeight - clientHeight)) * maxTop;
      setThumb({ show: true, top, height });
    };

    update();
    el.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    const ro = new ResizeObserver(update);
    ro.observe(el);
    if (el.firstElementChild) ro.observe(el.firstElementChild);

    return () => {
      el.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
      ro.disconnect();
    };
  }, [children]);

  return (
    <div className={`relative min-h-0 ${className}`}>
      <div ref={ref} className={`ir-native-scroll-hidden h-full overflow-y-auto ${contentClassName}`}>
        {children}
      </div>
      {thumb.show && (
        <div className="pointer-events-none absolute right-1 top-0 bottom-0 w-[3px]">
          <div
            className="ir-custom-scroll-thumb pointer-events-auto absolute right-0 w-[3px] rounded-full"
            style={{ top: thumb.top, height: thumb.height }}
          />
        </div>
      )}
    </div>
  );
}

function ClientMark({ client, active = false, compact = false }: { client: Client; active?: boolean; compact?: boolean }) {
  const logo = (client as Client & { logo?: string | null }).logo;
  const size = compact ? "w-10 h-10" : "w-9 h-9";

  if (logo) {
    return (
      <span
        className={`${size} shrink-0 rounded-full overflow-hidden bg-[#f0f1ea] ring-1 ring-white/10 flex items-center justify-center`}
      >
        <img src={logo} alt="" className="w-full h-full object-cover" />
      </span>
    );
  }

  return (
    <span
      className={`${size} shrink-0 rounded-full flex items-center justify-center text-[12px] font-black select-none transition
        ${active
          ? "bg-[#c9ff55] text-[#20221f]"
          : compact
            ? "bg-[#20221f] text-[#c9ff55] border border-[#c9ff55]/70"
            : "bg-[#f0f1ea] text-ink"}`}
    >
      {monogram(client.name)}
    </span>
  );
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

  // Владелец данных: селект из известных юзеров (наполняется при входе из телеги).
  const usersQ = useQuery({ queryKey: ["users"], queryFn: api.users, enabled: isEdit });
  const ownerMut = useMutation({
    mutationFn: (tid: number | null) => api.setClientOwner(initial!.id, tid),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["clients"] });
      qc.invalidateQueries({ queryKey: ["client", initial!.id] });
      onSaved(initial!.id);
    },
    onError: (e: Error) => setError(e.message),
  });

  // Скрытие компании вместо удаления (данные сохраняются).
  const hideMut = useMutation({
    mutationFn: (hidden: boolean) => api.setClientHidden(initial!.id, hidden),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["clients"] });
      qc.invalidateQueries({ queryKey: ["portfolio"] });
      onSaved(initial!.id);
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
          <h2 className="text-sm font-semibold">{isEdit ? "Редактировать клиента" : "Новый клиент"}</h2>
          <button onClick={onClose} className="text-ink-mute hover:text-ink text-lg leading-none">×</button>
        </div>

        {isEdit && initial && (initial.created_at || initial.created_by) && (
          <div className="px-5 py-2 bg-slate-50 border-b border-ink-line text-xs text-ink-mute font-mono leading-snug">
            <div>Создано: {(initial.created_at ?? "—").slice(0, 19).replace("T", " ")}</div>
            <div>Создал: {initial.created_by ?? "—"}</div>
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
              {isEdit && initial && (
                <Field label="Владелец данных (финализирует правки)">
                  <select
                    value={initial.owner_tid ?? ""}
                    onChange={e => ownerMut.mutate(e.target.value ? Number(e.target.value) : null)}
                    disabled={ownerMut.isPending}
                    className={input}
                  >
                    <option value="">— не назначен —</option>
                    {/* владелец, ещё не заходивший после релиза, отсутствует в users — показываем tid */}
                    {initial.owner_tid != null && !(usersQ.data ?? []).some(u => u.tid === initial.owner_tid) && (
                      <option value={initial.owner_tid}>tid {initial.owner_tid} (ещё не заходил)</option>
                    )}
                    {(usersQ.data ?? []).map(u => (
                      <option key={u.tid} value={u.tid}>{u.name}{u.username ? ` (@${u.username})` : ""}</option>
                    ))}
                  </select>
                  <div className="mt-1 text-[11px] text-ink-mute leading-snug">
                    Список наполняется автоматически: эксперт появляется здесь после первого
                    захода в тул. Менять владельца может текущий владелец или админ.
                  </div>
                </Field>
              )}
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
            <div className="mt-4 border border-ink-line rounded-lg p-3 space-y-2">
              <div className="text-xs font-semibold uppercase tracking-wide text-ink-mute">Видимость</div>
              <p className="text-xs text-ink-mute leading-snug">
                Скрытая компания уходит из списков и портфеля, но все данные сохраняются —
                мягкая альтернатива удалению.
              </p>
              <button type="button" onClick={() => hideMut.mutate(!initial.hidden)} disabled={hideMut.isPending}
                className="text-xs px-3 py-1.5 border border-ink-line rounded hover:bg-ink/[0.04]">
                {initial.hidden ? "Вернуть из скрытых" : "Скрыть компанию"}
              </button>
            </div>
          )}

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
  const [renderCompact, setRenderCompact] = useState(collapsed);

  const collapseSidebar = () => setCollapsed(true);
  const expandSidebar = () => {
    setRenderCompact(false);
    setCollapsed(false);
  };

  useEffect(() => {
    try { localStorage.setItem(COLLAPSE_KEY, collapsed ? "1" : "0"); } catch { /* noop */ }
  }, [collapsed]);

  useEffect(() => {
    if (!collapsed) {
      setRenderCompact(false);
      return;
    }
    const timer = window.setTimeout(() => setRenderCompact(true), 260);
    return () => window.clearTimeout(timer);
  }, [collapsed]);

  const [showHidden, setShowHidden] = useState(false);   // админ: показать скрытые компании
  const clients = useQuery({ queryKey: ["clients", showHidden], queryFn: () => api.listClients(showHidden) });
  const portfolio = useQuery({ queryKey: ["portfolio"], queryFn: api.clientsPortfolio });
  const covMap = new Map((portfolio.data ?? []).map(p => [p.id, p]));
  const me = useQuery({ queryKey: ["me"], queryFn: api.authMe, retry: false });
  const isAdmin = !me.data?.auth || !!me.data?.is_admin;
  const canManage = (c: Client) => isAdmin || (c.owner_tid != null && me.data?.tid === c.owner_tid);
  const hideMut = useMutation({
    mutationFn: ({ id, hidden }: { id: string; hidden: boolean }) => api.setClientHidden(id, hidden),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["clients"] }); qc.invalidateQueries({ queryKey: ["portfolio"] }); },
  });
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

  if (renderCompact) {
    const compactClients = (clients.data ?? []).filter(
      c => scope === "all" || !me.data?.auth || covMap.get(c.id)?.mine);
    return (
      <>
        <aside className="ir-sidebar-scroll-scope w-16 h-full min-h-0 shrink-0 overflow-hidden border-r border-[#1c1e1b] bg-[#292c28] flex flex-col items-center py-3 transition-[width] duration-300 ease-out">
          <div className="w-16 min-h-0 flex-1 flex flex-col items-center animate-[ir-sidebar-content-in_160ms_ease-out]">
            <button
              onClick={expandSidebar}
              className="w-10 h-10 flex items-center justify-center rounded-[14px] overflow-hidden hover:brightness-110"
              aria-label="Раскрыть список компаний"
            >
              <img src="/favicon.svg" alt="" className="w-10 h-10 block" />
            </button>

            <div className="my-3 h-px w-8 bg-white/10" />

            <SidebarScrollArea className="flex-1 w-full" contentClassName="px-2 space-y-2">
              {clients.isLoading && (
                <div className="mx-auto w-10 h-10 rounded-full border border-white/15 animate-pulse" />
              )}
              {compactClients.map(c => {
                const active = clientId === c.id;
                return (
                  <HintTarget
                    key={c.id}
                    title={c.name}
                    body={clientHintBody(c)}
                  >
                    <Link
                      to={`/clients/${c.id}/${tab ?? "matrix"}`}
                      className={`relative flex items-center justify-center rounded-2xl py-1 transition
                        ${active ? "" : "hover:bg-white/5"}`}
                    >
                      <ClientMark client={c} active={active} compact />
                    </Link>
                  </HintTarget>
                );
              })}
            </SidebarScrollArea>

            <button
              onClick={() => setShowNewClient(true)}
              className="mt-3 w-10 h-10 rounded-full border border-white/15 text-white/70 hover:text-[#c9ff55] hover:border-[#c9ff55]/50 font-bold"
              aria-label="Добавить компанию"
            >+</button>
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

  return (
    <>
      <aside className={`ir-sidebar-scroll-scope ${collapsed ? "w-16" : "w-72"} h-full min-h-0 shrink-0 overflow-hidden border-r border-[#1c1e1b] bg-[#292c28] flex flex-col transition-[width] duration-300 ease-out`}>
        <div className="w-72 min-h-0 flex-1 flex flex-col animate-[ir-sidebar-content-in_160ms_ease-out]">
          <div className="px-3 py-3 border-b border-white/10 flex items-center justify-between bg-[#292c28]">
            <div className="min-w-0 flex items-center gap-3">
              <button
                onClick={collapseSidebar}
                className="w-10 h-10 shrink-0 flex items-center justify-center rounded-[14px] overflow-hidden hover:brightness-110"
                aria-label="Свернуть список компаний"
              >
                <img src="/favicon.svg" alt="" className="w-10 h-10 block" />
              </button>
              <div className="min-w-0">
                <div className="text-[17px] font-bold text-white leading-tight">IR Storyboard</div>
                <div className="text-xs text-white/55 leading-tight">Клиенты и матрицы</div>
              </div>
            </div>
            <div className="flex items-center gap-1.5">
              <button
                onClick={() => setShowNewClient(true)}
                className="w-8 h-8 rounded-full border border-white/15 bg-white/5 text-white hover:text-[#c9ff55] hover:border-[#c9ff55]/50 font-bold"
                aria-label="Добавить компанию"
              >+</button>
              <button
                onClick={collapseSidebar}
                className="w-8 h-8 rounded-full text-white/50 hover:text-white hover:bg-white/5"
                aria-label="Свернуть панель"
              >«</button>
            </div>
          </div>

          {me.data?.auth && (clients.data?.length ?? 0) > 0 && (
            <div className="px-4 py-3 border-b border-white/10 bg-[#292c28]">
              <div className="flex items-center rounded-xl border border-white/10 overflow-hidden text-[12px] bg-black/15">
                <button
                  onClick={() => setScope("mine")}
                  className={`flex-1 py-2 transition ${scope === "mine" ? "bg-[#c9ff55] text-[#20221f] font-semibold" : "text-white/55 hover:text-white hover:bg-white/5"}`}
                >Мои</button>
                <button
                  onClick={() => setScope("all")}
                  className={`flex-1 py-2 transition ${scope === "all" ? "bg-[#c9ff55] text-[#20221f] font-semibold" : "text-white/55 hover:text-white hover:bg-white/5"}`}
                >Все</button>
              </div>
            </div>
          )}

          <SidebarScrollArea className="flex-1 bg-[#fbfbf7]" contentClassName="px-3 py-3">
            {clients.isLoading && <div className="text-xs text-ink-mute px-2 py-2">Загрузка…</div>}
            {clients.data && clients.data.length === 0 && (
              <button
                onClick={() => seedAcc.mutate()}
                className="w-full text-left text-xs px-3 py-2 rounded-xl border border-ink-line bg-white hover:bg-[#f6f6f1] text-[#40551f] font-semibold"
              >+ Загрузить пилот (Accumulator)</button>
            )}
            {(() => {
              const list = (clients.data ?? []).filter(
                c => scope === "all" || !me.data?.auth || covMap.get(c.id)?.mine);
              if (me.data?.auth && scope === "mine" && list.length === 0 && (clients.data?.length ?? 0) > 0) {
                return <div className="text-xs text-ink-mute px-3 py-3 leading-snug bg-white border border-ink-line rounded-xl">
                  Пока нет «моих». Отметь компанию звёздочкой ★ (наведи на строку) или переключись на «Все».
                </div>;
              }
              return (
                <ul className="space-y-1.5">
                  {list.map(c => {
                    const active = clientId === c.id;
                    const p = covMap.get(c.id);
                    const pct = p && p.total ? Math.round((p.covered / p.total) * 100) : 0;
                    const mine = !!p?.mine;
                    return (
                      <li key={c.id} className="group relative">
                        <Link
                          to={`/clients/${c.id}/${tab ?? "matrix"}`}
                          className={`flex items-center gap-3 px-3 py-2.5 pr-14 rounded-xl transition border
                            ${active ? "bg-white border-[#cbd8a2] shadow-sm" : "border-transparent hover:bg-white hover:border-ink-line"}`}
                        >
                          <ClientMark client={c} active={active} />
                          <div className="min-w-0 flex-1">
                            <div className={`text-[14px] truncate flex items-center gap-1 ${c.hidden ? "text-ink-mute line-through" : "text-ink"} ${active ? "font-bold" : "font-semibold"}`}>
                              <span className="truncate">{c.name}</span>
                              {c.owner_tid != null && me.data?.tid === c.owner_tid && (
                                <span title="вы — владелец данных" className="shrink-0 text-[10px]">👑</span>)}
                              {c.hidden && <span className="shrink-0 text-[9px] uppercase tracking-wide text-ink-mute/70">скрыта</span>}
                            </div>
                            <div className="flex items-center gap-1.5 mt-1.5">
                              <div className="h-1.5 flex-1 rounded-full bg-ink/[0.07] overflow-hidden">
                                <div className="h-full rounded-full bg-[#98c61b]" style={{ width: `${pct}%` }} />
                              </div>
                              <span className="text-[10px] text-ink-mute tabular-nums w-7 text-right">{pct}%</span>
                            </div>
                          </div>
                        </Link>
                        {me.data?.auth && (
                          <button
                            onClick={(e) => { e.preventDefault(); mineMut.mutate({ id: c.id, on: !mine }); }}
                            className={`absolute right-8 top-3 transition px-1 py-0.5 rounded-lg hover:bg-white
                              ${mine ? "text-amber-500 opacity-100" : "text-ink-mute opacity-0 group-hover:opacity-100 hover:text-ink"}`}
                            title={mine ? "Убрать из моих" : "В мои компании"}
                            aria-label={mine ? "Unstar" : "Star"}
                          >{mine ? "★" : "☆"}</button>
                        )}
                        <button
                          onClick={(e) => { e.preventDefault(); setEditingClient(c); }}
                          className="absolute right-2 top-3 opacity-0 group-hover:opacity-100 transition px-1.5 py-0.5 text-ink-mute hover:text-ink rounded-lg hover:bg-white"
                          title="Edit client"
                          aria-label={`Edit ${c.name}`}
                        >✎</button>
                      </li>
                    );
                  })}
                </ul>
              );
            })()}
            {isAdmin && (
              <button onClick={() => setShowHidden(v => !v)}
                className="mt-3 w-full text-left px-3 py-2 text-[11px] text-ink-mute hover:text-ink hover:bg-white rounded-xl transition">
                {showHidden ? "спрятать скрытые" : "показать скрытые"}
              </button>
            )}
          </SidebarScrollArea>
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
