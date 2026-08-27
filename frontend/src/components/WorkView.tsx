import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { displayWorkBody, displayWorkTitle } from "../lib/workItemDisplay";
import type { WorkItem, WorkItemStatus, WorkItemType } from "../types";

interface Props {
  clientId: string;
  onJumpToCell: (sid: string) => void;
}

const STATUS_COLS: { key: WorkItemStatus | "_done14"; label: string }[] = [
  { key: "queued",       label: "В очереди" },
  { key: "in_progress",  label: "В работе" },
  { key: "needs_review", label: "На проверке" },
  { key: "_done14",      label: "Готово (14 дней)" },
];

const TYPE_LABELS: Record<WorkItemType, string> = {
  fill_gap: "закрыть пробел",
  discover: "найти",
  verify: "проверить",
  deepen: "углубить",
  interview: "интервью",
  adjacent: "смежное",
  cross_ref: "связь",
};

const TYPE_COLORS: Record<WorkItemType, string> = {
  fill_gap:  "bg-blue-100 text-blue-800",
  discover:  "bg-purple-100 text-purple-800",
  verify:    "bg-yellow-100 text-yellow-800",
  deepen:    "bg-indigo-100 text-indigo-800",
  interview: "bg-pink-100 text-pink-800",
  adjacent:  "bg-teal-100 text-teal-800",
  cross_ref: "bg-orange-100 text-orange-800",
};

function ageLabel(dateStr: string) {
  const d = new Date(dateStr);
  const days = Math.floor((Date.now() - d.getTime()) / 86400000);
  if (days === 0) return "сегодня";
  if (days === 1) return "1 д";
  if (days < 7) return `${days} д`;
  return `${Math.floor(days / 7)} нед`;
}

function PriorityDot({ p }: { p: number }) {
  const color = p === 1 ? "bg-red-500" : p === 2 ? "bg-amber-400" : "bg-slate-300";
  return <span className={`inline-block w-2 h-2 rounded-full ${color} shrink-0`} title={`P${p}`} />;
}

function TypeBadge({ type }: { type: WorkItemType }) {
  return (
    <span className={`text-[9px] font-mono uppercase px-1.5 py-0.5 rounded ${TYPE_COLORS[type] ?? "bg-slate-100"}`}>
      {TYPE_LABELS[type] ?? type.replace("_", " ")}
    </span>
  );
}

function WorkItemCard({ item, onClick }: { item: WorkItem; onClick: () => void }) {
  return (
    <div
      className="bg-white border border-ink-line rounded p-2.5 cursor-pointer hover:shadow-sm transition space-y-1.5"
      onClick={onClick}
    >
      <div className="flex items-center gap-1.5 flex-wrap">
        <PriorityDot p={item.priority} />
        <TypeBadge type={item.type} />
        {item.subsection_id && (
          <span className="text-[10px] font-mono text-ink-mute">{item.subsection_id}</span>
        )}
      </div>
      <div className="text-xs leading-snug font-medium">{displayWorkTitle(item.title)}</div>
      <div className="flex items-center justify-between text-[10px] text-ink-mute">
        <span>{item.assignee || "Не назначено"}</span>
        <span>{ageLabel(item.created_at)}</span>
      </div>
    </div>
  );
}

const DONE_STATUSES: WorkItemStatus[] = ["done", "blocked", "cancelled"];
const ACTIVE_STATUSES: WorkItemStatus[] = ["queued", "in_progress", "needs_review"];

function WorkItemDrawer({
  item, onClose, onJumpToCell, clientId,
}: { item: WorkItem; onClose: () => void; onJumpToCell: (sid: string) => void; clientId: string }) {
  const qc = useQueryClient();
  const [notes, setNotes] = useState(item.notes || "");
  const [relatedFactId, setRelatedFactId] = useState<string>(
    item.related_fact_id ? String(item.related_fact_id) : ""
  );
  const me = useQuery({ queryKey: ["me"], queryFn: api.authMe, retry: false });
  const users = useQuery({ queryKey: ["users"], queryFn: api.users });

  const patch = useMutation({
    mutationFn: (body: Partial<WorkItem>) => api.patchWorkItem(item.id, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["work-items", clientId] }),
  });

  const setStatus = (status: WorkItemStatus) => patch.mutate({ status });

  const isActive = ACTIVE_STATUSES.includes(item.status);

  return (
    <div className="fixed inset-0 z-50 flex">
      <div className="absolute inset-0 bg-black/20" onClick={onClose} />
      <div className="relative ml-auto w-[400px] h-full bg-white shadow-xl flex flex-col border-l border-ink-line">
        <div className="px-4 py-3 border-b border-ink-line flex items-start justify-between gap-2">
          <div className="space-y-1">
            <div className="flex items-center gap-1.5 flex-wrap">
              <TypeBadge type={item.type} />
              <PriorityDot p={item.priority} />
              <span className="text-[10px] font-mono text-ink-mute uppercase">{STATUS_COLS.find(s => s.key === item.status)?.label ?? item.status}</span>
            </div>
            <h3 className="text-sm font-semibold leading-snug">{displayWorkTitle(item.title)}</h3>
          </div>
          <button onClick={onClose} className="text-ink-mute hover:text-ink shrink-0 text-lg leading-none">×</button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-4 text-sm">
          {item.rationale && (
            <div className="text-xs text-ink-mute bg-slate-50 rounded p-2 italic">{displayWorkBody(item.title, item.rationale)}</div>
          )}

          {item.subsection_id && (
            <div className="flex items-center gap-2">
              <span className="text-xs text-ink-mute">Ячейка:</span>
              <button
                onClick={() => { onJumpToCell(item.subsection_id!); onClose(); }}
                className="text-xs text-blue-600 hover:underline font-mono"
              >
                {item.subsection_id} →
              </button>
            </div>
          )}

          {item.suggested_channel && (
            <div className="text-xs text-ink-mute">
              Предложенный канал: <span className="font-mono">{item.suggested_channel}</span>
            </div>
          )}

          {/* Actions */}
          {isActive && (
            <div className="space-y-1.5">
              <div className="text-[10px] font-semibold uppercase text-ink-mute tracking-wide">Действия</div>
              <div className="flex flex-wrap gap-1.5">
                {item.status === "queued" && (
                  <ActionBtn label="Взять себе" onClick={() => {
                    patch.mutate(me.data?.tid
                      ? { status: "in_progress", assignee_tid: me.data.tid }
                      : { status: "in_progress", assignee: "me" });
                  }} />
                )}
                {item.status !== "in_progress" && (
                  <ActionBtn label="В работу" onClick={() => setStatus("in_progress")} />
                )}
                {item.status !== "needs_review" && (
                  <ActionBtn label="На проверку" onClick={() => setStatus("needs_review")} />
                )}
                <ActionBtn label="Готово" variant="green" onClick={() => {
                  const body: Partial<WorkItem> = { status: "done" };
                  if (relatedFactId) body.related_fact_id = Number(relatedFactId);
                  if (notes) body.notes = notes;
                  patch.mutate(body);
                }} />
                <ActionBtn label="Заблокировать" variant="amber" onClick={() => setStatus("blocked")} />
                <ActionBtn label="Отменить" variant="muted" onClick={() => setStatus("cancelled")} />
              </div>
            </div>
          )}

          {/* Assign — реальный юзер из списка (наполняется при входе в телеге) */}
          <div>
            <label className="block text-[10px] font-semibold uppercase text-ink-mute tracking-wide mb-1">Исполнитель</label>
            <select
              value={item.assignee_tid ?? ""}
              onChange={e => patch.mutate({ assignee_tid: e.target.value ? Number(e.target.value) : 0 })}
              className="w-full text-xs border border-ink-line rounded px-2 py-1 bg-white"
            >
              <option value="">— не назначен —</option>
              {(users.data ?? []).map(u => (
                <option key={u.tid} value={u.tid}>{u.name}{u.username ? ` (@${u.username})` : ""}</option>
              ))}
            </select>
            {item.assignee && item.assignee_tid == null && (
              <div className="mt-1 text-[10px] text-ink-mute">текущий: {item.assignee}</div>
            )}
          </div>

          {/* Close with fact */}
          {isActive && (
            <div>
              <label className="block text-[10px] font-semibold uppercase text-ink-mute tracking-wide mb-1">
                Закрыть фактом (опционально)
              </label>
              <input
                type="number"
                value={relatedFactId}
                onChange={e => setRelatedFactId(e.target.value)}
                className="w-full text-xs border border-ink-line rounded px-2 py-1 font-mono"
                placeholder="ID факта"
              />
            </div>
          )}

          {/* Notes */}
          <div>
            <label className="block text-[10px] font-semibold uppercase text-ink-mute tracking-wide mb-1">Заметки</label>
            <textarea
              value={notes}
              onChange={e => setNotes(e.target.value)}
              rows={3}
              className="w-full text-xs border border-ink-line rounded px-2 py-1.5 resize-none"
            />
            <button
              onClick={() => patch.mutate({ notes })}
              className="mt-1 text-xs px-2 py-1 border border-ink-line rounded hover:bg-slate-50"
            >Сохранить заметки</button>
          </div>

          <div className="text-[10px] text-ink-mute space-y-0.5">
            <div>Создано: {item.created_at.slice(0, 10)}</div>
            {item.completed_at && <div>Завершено: {item.completed_at.slice(0, 10)}</div>}
          </div>
        </div>
      </div>
    </div>
  );
}

function ActionBtn({
  label, onClick, variant = "default",
}: { label: string; onClick: () => void; variant?: "default" | "green" | "amber" | "muted" }) {
  const cls = variant === "green" ? "bg-emerald-600 text-white hover:bg-emerald-700"
    : variant === "amber" ? "bg-amber-500 text-white hover:bg-amber-600"
    : variant === "muted" ? "text-ink-mute border border-ink-line hover:bg-slate-50"
    : "bg-ink text-white hover:bg-black";
  return (
    <button onClick={onClick} className={`text-xs px-2.5 py-1 rounded ${cls}`}>{label}</button>
  );
}

export default function WorkView({ clientId, onJumpToCell }: Props) {
  const qc = useQueryClient();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [mineOnly, setMineOnly] = useState(false);
  const me = useQuery({ queryKey: ["me"], queryFn: api.authMe, retry: false });

  const items = useQuery<WorkItem[]>({
    queryKey: ["work-items", clientId],
    queryFn: () => api.listWorkItems(clientId),
  });

  const synthesize = useMutation({
    mutationFn: () => api.synthesizeWorkItems(clientId),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["work-items", clientId] });
      alert(`Создано новых задач: ${res.created.length}.`);
    },
  });

  const now = Date.now();
  const colItems = (colKey: string): WorkItem[] => {
    if (!items.data) return [];
    if (colKey === "_done14") {
      return items.data.filter(i =>
        DONE_STATUSES.includes(i.status) &&
        now - new Date(i.updated_at).getTime() < 14 * 86400000
      );
    }
    const base = items.data.filter(i => i.status === colKey);
    return mineOnly && me.data?.tid ? base.filter(i => i.assignee_tid === me.data!.tid) : base;
  };

  const total = items.data?.filter(i => ACTIVE_STATUSES.includes(i.status)).length ?? 0;
  const selected = items.data?.find(i => i.id === selectedId) ?? null;   // всегда живой (после патча обновляется)

  return (
    <div className="p-5 max-w-[1180px] mx-auto w-full space-y-4 h-full flex flex-col">
      <div className="flex items-center justify-between">
        <div className="flex items-baseline gap-3">
          <h2 className="text-lg font-semibold">Работа</h2>
          <span className="text-xs text-ink-mute">активных: {total}</span>
          {me.data?.auth && (
            <button onClick={() => setMineOnly(v => !v)}
              className={`text-xs px-2.5 py-1 rounded border transition ${mineOnly ? "bg-ink text-white border-ink" : "border-ink-line text-ink-mute hover:text-ink"}`}
              title="показать только назначенные мне">
              мои задачи
            </button>
          )}
        </div>
        <button
          onClick={() => synthesize.mutate()}
          disabled={synthesize.isPending}
          className="text-xs px-3 py-1.5 bg-ink text-white rounded hover:bg-black disabled:opacity-50"
          title="Создать задачи из списка пробелов и слабого покрытия"
        >
          {synthesize.isPending ? "Собираю…" : "Собрать задачи"}
        </button>
      </div>

      {items.isLoading && <div className="text-sm text-ink-mute">Загрузка…</div>}

      {items.data && total === 0 && items.data.length === 0 && (
        <div className="text-sm text-ink-mute italic">
          Задач пока нет. Нажмите «Собрать задачи», чтобы создать их из текущего списка пробелов.
        </div>
      )}

      <div className="flex-1 grid grid-cols-4 gap-3 min-h-0 overflow-hidden">
        {STATUS_COLS.map(col => (
          <div key={col.key} className="flex flex-col min-h-0">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-semibold text-ink-mute uppercase tracking-wide">{col.label}</span>
              <span className="text-[10px] text-ink-mute font-mono">{colItems(col.key).length}</span>
            </div>
            <div className="flex-1 overflow-y-auto space-y-2 pr-1">
              {colItems(col.key).map(item => (
                <WorkItemCard key={item.id} item={item} onClick={() => setSelectedId(item.id)} />
              ))}
            </div>
          </div>
        ))}
      </div>

      {selected && (
        <WorkItemDrawer
          item={selected}
          onClose={() => setSelectedId(null)}
          onJumpToCell={onJumpToCell}
          clientId={clientId}
        />
      )}
    </div>
  );
}
