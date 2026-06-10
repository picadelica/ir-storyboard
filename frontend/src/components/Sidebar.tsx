import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import type { Client, Track } from "../types";

interface Props {
  clientId?: string;
  quarter: string;
  onQuarterChange: (q: string) => void;
  onRunCycle: (kind: "weekly" | "event" | "quarterly") => void;
}

const SLUG_RE = /^[a-z0-9-]+$/;

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

export default function Sidebar({ clientId, quarter, onQuarterChange, onRunCycle }: Props) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const { tab } = useParams();
  const [showNewClient, setShowNewClient] = useState(false);
  const [editingClient, setEditingClient] = useState<Client | null>(null);

  const clients = useQuery({ queryKey: ["clients"], queryFn: api.listClients });
  const tracks = useQuery({
    queryKey: ["tracks", clientId, quarter],
    queryFn: () => api.tracks(clientId!, quarter),
    enabled: !!clientId,
  });

  const seedAcc = useMutation({
    mutationFn: api.seedAccumulator,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["clients"] });
      nav("/clients/accumulator");
    },
  });

  return (
    <>
      <aside className="w-72 shrink-0 border-r border-ink-line bg-white flex flex-col">
        <div className="px-4 py-4 border-b border-ink-line">
          <div className="text-base font-semibold tracking-tight">IR Storyboard</div>
          <div className="text-xs text-ink-mute mt-0.5">narrative matrix · cycles · outputs</div>
        </div>

        {/* Clients */}
        <div className="px-3 py-3">
          <div className="flex items-center justify-between mb-1.5 px-1">
            <div className="text-xs font-semibold uppercase text-ink-mute tracking-wide">Clients</div>
            <button
              onClick={() => setShowNewClient(true)}
              className="text-xs text-blue-600 hover:text-blue-800 font-medium"
              title="Add new client"
            >+ New</button>
          </div>
          {clients.isLoading && <div className="text-xs text-ink-mute px-1 py-1">Loading…</div>}
          {clients.data && clients.data.length === 0 && (
            <button
              onClick={() => seedAcc.mutate()}
              className="w-full text-left text-xs px-2 py-1.5 rounded hover:bg-slate-100 text-blue-600"
            >+ Загрузить пилот (Accumulator)</button>
          )}
          <ul className="space-y-0.5">
            {clients.data?.map(c => (
              <li key={c.id} className="group relative">
                <Link
                  to={`/clients/${c.id}/${tab ?? "matrix"}`}
                  className={`flex items-center justify-between px-2 py-1.5 rounded text-sm
                    ${clientId === c.id ? "bg-slate-100 font-medium" : "hover:bg-slate-50"}`}
                >
                  <span>{c.name}</span>
                  <span className="text-[10px] text-ink-mute uppercase truncate ml-2 mr-5">{c.sector?.split("/")[0]}</span>
                </Link>
                <button
                  onClick={(e) => { e.preventDefault(); setEditingClient(c); }}
                  className="absolute right-1 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 transition px-1.5 text-ink-mute hover:text-ink rounded hover:bg-white"
                  title="Edit client"
                  aria-label={`Edit ${c.name}`}
                >✎</button>
              </li>
            ))}
          </ul>
        </div>

        {clientId && (
          <>
            <div className="px-4 py-3 border-t border-ink-line">
              <label className="text-xs font-semibold uppercase text-ink-mute tracking-wide">Quarter</label>
              <input
                value={quarter}
                onChange={e => onQuarterChange(e.target.value)}
                className="mt-1 w-full text-sm border border-ink-line rounded px-2 py-1 font-mono"
                placeholder="2026Q2"
              />
            </div>

            <div className="px-3 py-3 border-t border-ink-line">
              <div className="text-xs font-semibold uppercase text-ink-mute tracking-wide mb-1.5 px-1">
                Active narrative tracks
              </div>
              {tracks.isLoading && <div className="text-xs text-ink-mute px-1">Loading…</div>}
              {tracks.data && tracks.data.length === 0 && (
                <div className="text-xs text-ink-mute px-1">No tracks for {quarter}.</div>
              )}
              <ul className="space-y-1.5">
                {tracks.data?.map((t: Track) => (
                  <li key={t.id} className="px-2 py-1.5 bg-slate-50 rounded border border-ink-line/60">
                    <div className="flex items-center gap-1.5 mb-0.5">
                      <span className="inline-block text-[10px] font-mono px-1.5 py-0.5 bg-slate-200 rounded">P{t.priority}</span>
                      <span className="text-xs font-medium leading-snug">{t.name}</span>
                    </div>
                    {t.angle && <div className="text-[11px] text-ink-mute leading-snug">{t.angle}</div>}
                    <div className="text-[10px] text-ink-mute font-mono mt-1">L{t.target_layer_ids.join(",")}</div>
                  </li>
                ))}
              </ul>
            </div>

            <div className="px-3 py-3 border-t border-ink-line mt-auto bg-slate-50">
              <div className="text-xs font-semibold uppercase text-ink-mute tracking-wide mb-2 px-1">Run cycle</div>
              <div className="grid grid-cols-1 gap-1.5">
                <button
                  onClick={() => onRunCycle("weekly")}
                  className="text-xs px-3 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700"
                >Weekly бриф</button>
                <button
                  onClick={() => onRunCycle("event")}
                  className="text-xs px-3 py-1.5 bg-amber-600 text-white rounded hover:bg-amber-700"
                >Event-реакция</button>
                <button
                  onClick={() => onRunCycle("quarterly")}
                  className="text-xs px-3 py-1.5 bg-emerald-700 text-white rounded hover:bg-emerald-800"
                >Квартальный досье</button>
              </div>
            </div>
          </>
        )}
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
