import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import UsersView from "./UsersView";
import type { AdminActivityEntry, Client, UserOverview } from "../types";

/** Админка (только супер-админы): Журнал действий над карточками (все компании,
 *  фильтры компания/пользователь/действие) + Пользователи системы. */

const ACTION_RU: Record<string, string> = {
  created: "создал", moved: "перенёс", edited: "правил", merged: "склеил",
  speaker_renamed: "переименовал спикера", title: "заголовок", speaker: "спикер",
  must_have: "must-have", about_company: "про компанию", approved: "одобрил",
  rejected: "отклонил", restored: "вернул", deleted: "удалил",
};

function fmtAt(at: string): string {
  // "2026-07-25 05:44:52" → "25.07 05:44"
  const m = at?.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/);
  return m ? `${m[3]}.${m[2]} ${m[4]}:${m[5]}` : at || "";
}

export default function AdminView() {
  const [tab, setTab] = useState<"log" | "users">("log");
  return (
    <div className="p-5 max-w-5xl">
      <div className="flex items-baseline gap-4 mb-1">
        <h2 className="text-lg font-semibold">Админка</h2>
        <div className="flex items-center gap-1 text-[13px]">
          {([["log", "Журнал действий"], ["users", "Пользователи"]] as const).map(([id, label]) => (
            <button key={id} onClick={() => setTab(id)}
              className={`px-2.5 py-1 rounded-lg transition ${tab === id ? "bg-ink text-white font-medium" : "text-ink-mute hover:text-ink hover:bg-ink/[0.04]"}`}>
              {label}
            </button>
          ))}
        </div>
      </div>
      <p className="text-xs text-ink-mute mb-4">
        {tab === "log"
          ? "Полная история действий над карточками по всем компаниям: кто, когда, что, при какой версии методологии. Включая системные действия."
          : "Кто есть кто: роль, активность, последний вход."}
      </p>
      {tab === "log" ? <ActivityLog /> : <UsersView />}
    </div>
  );
}

function ActivityLog() {
  const nav = useNavigate();
  const [clientId, setClientId] = useState("");
  const [actorTid, setActorTid] = useState("");
  const [action, setAction] = useState("");

  const clients = useQuery<Client[]>({ queryKey: ["clients"], queryFn: () => api.listClients() });
  const users = useQuery<UserOverview[]>({ queryKey: ["users-overview"], queryFn: api.usersOverview });
  const log = useQuery({
    queryKey: ["admin-activity", clientId, actorTid, action],
    queryFn: () => api.adminActivity({
      clientId: clientId || undefined,
      actorTid: actorTid ? Number(actorTid) : undefined,
      action: action || undefined,
      limit: 300,
    }),
  });

  const entries = log.data?.activity ?? [];
  const sel = "text-xs border border-ink-line rounded-lg px-2 py-1.5 bg-white max-w-[14rem]";
  const openFact = (e: AdminActivityEntry) => {
    if (!e.client_id) return;
    const cell = e.to_sid || e.from_sid;
    nav(`/clients/${e.client_id}/matrix${cell ? `?cell=${cell}&fact=${e.fact_id}` : ""}`);
  };

  return (
    <div>
      {/* фильтры */}
      <div className="flex flex-wrap items-center gap-2 mb-3">
        <select value={clientId} onChange={e => setClientId(e.target.value)} className={sel}>
          <option value="">— все компании —</option>
          {(clients.data ?? []).map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <select value={actorTid} onChange={e => setActorTid(e.target.value)} className={sel}>
          <option value="">— все пользователи —</option>
          {(users.data ?? []).map(u => <option key={u.tid} value={u.tid}>{u.name}</option>)}
        </select>
        <select value={action} onChange={e => setAction(e.target.value)} className={sel}>
          <option value="">— все действия —</option>
          {Object.entries(ACTION_RU).map(([id, label]) => <option key={id} value={id}>{label}</option>)}
        </select>
        {(clientId || actorTid || action) && (
          <button onClick={() => { setClientId(""); setActorTid(""); setAction(""); }}
            className="text-xs text-ink-mute hover:text-ink">сбросить</button>
        )}
        <span className="ml-auto text-[11px] text-ink-mute">{entries.length}{entries.length === 300 ? "+" : ""} записей</span>
      </div>

      {log.isLoading && <div className="text-sm text-ink-mute py-4">Загрузка…</div>}
      {log.isError && <div className="text-sm text-red-600 py-4">Нет доступа или ошибка: {String(log.error)}</div>}
      {!log.isLoading && !log.isError && entries.length === 0 && (
        <div className="text-sm text-ink-mute italic py-4">
          Пока пусто. Журнал копится с 25.07.2026 — что было раньше, не записывалось.
        </div>
      )}

      <ul className="divide-y divide-ink-line/60 bg-white rounded-lg border border-ink-line">
        {entries.map(e => (
          <li key={e.id}>
            <button onClick={() => openFact(e)} className="w-full text-left px-3.5 py-2.5 hover:bg-slate-50 transition">
              <div className="flex items-center gap-2 text-xs flex-wrap">
                <span className="font-mono text-[11px] text-ink-mute shrink-0">{fmtAt(e.at)}</span>
                <span className="font-medium text-ink">{e.actor_name || "система"}</span>
                <span className="text-ink-mute">{ACTION_RU[e.action] || e.action}</span>
                {e.action === "moved" && e.from_sid && e.to_sid && (
                  <span className="font-mono text-[11px]">
                    <span className="px-1 py-0.5 rounded bg-slate-100 border border-slate-200 text-slate-600">{e.from_sid}</span>
                    <span className="text-ink-mute mx-0.5">→</span>
                    <span className="px-1 py-0.5 rounded bg-emerald-100 border border-emerald-200 text-emerald-700">{e.to_sid}</span>
                  </span>
                )}
                {e.detail && e.action !== "moved" && <span className="text-ink-mute italic truncate max-w-[14rem]">· {e.detail}</span>}
                {e.action === "moved" && e.detail === "reclassify" && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-700 uppercase tracking-wide">методология</span>
                )}
                <span className="ml-auto flex items-center gap-2 shrink-0">
                  {e.methodology_version != null && (
                    <span className="text-[10px] text-ink-mute/70 font-mono" title="версия методологии в момент действия">v{e.methodology_version}</span>
                  )}
                  <span className="text-[11px] text-ink-mute bg-ink/[0.04] rounded px-1.5 py-0.5">{e.client_name}</span>
                </span>
              </div>
              <div className="mt-0.5 text-xs text-ink-mute truncate">
                <span className="font-mono text-[10px] text-ink-mute/60 mr-1.5">#{e.fact_id}</span>
                {e.fact_title && <span className="font-medium text-ink mr-1">{e.fact_title}</span>}
                {e.fact_text || (e.action === "deleted" ? "(карточка удалена)" : "")}
              </div>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
