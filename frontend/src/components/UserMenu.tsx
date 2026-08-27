import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { HintTarget } from "./Hint";

function monogram(name: string): string {
  return name.replace(/^@/, "").split(/[\s_]+/).map(w => w[0]).join("").slice(0, 2).toUpperCase();
}

export default function UserMenu({ clientId, canSeeUsers }: { clientId?: string; canSeeUsers?: boolean } = {}) {
  const me = useQuery({ queryKey: ["me"], queryFn: api.authMe, retry: false });
  const qc = useQueryClient();
  const nav = useNavigate();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const h = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [open]);

  if (!me.data?.auth) return null;
  const name = me.data.name;

  const logout = async () => {
    try { await api.authLogout(); } catch { /* ignore */ }
    qc.invalidateQueries({ queryKey: ["me"] });
  };

  return (
    <div className="relative" ref={ref}>
      <HintTarget title="Профиль" body={`Текущий пользователь: ${name}. Здесь можно сменить режим, открыть админку или выйти.`}>
        <button
          onClick={() => setOpen(o => !o)}
          className="w-10 h-10 rounded-full bg-[#f0f1ea] text-ink text-[12px] font-black flex items-center justify-center hover:bg-[#e8eadf] transition"
          aria-label="Профиль"
        >
          {monogram(name)}
        </button>
      </HintTarget>
      {open && (
        <div className="absolute right-0 mt-2 w-56 bg-white border border-ink-line rounded-2xl py-1.5 z-50 shadow-sm overflow-hidden">
          <div className="px-3 py-2 text-[13px] text-ink truncate border-b border-ink-line">{name}</div>
          {me.data?.is_real_admin && (
            /* режим работы супер-админа: админ ↔ обычный эксперт (черновики, без админ-прав).
               Хранится в cookie ir_act_as — бэкенд уважает режим в гейтах. */
            <div className="px-3 py-2 border-b border-ink-line flex items-center gap-2">
              <span className="text-[11px] text-ink-mute">Режим:</span>
              <div className="flex items-center rounded-xl border border-ink-line overflow-hidden text-[11px] bg-[#f6f6f1]">
                {([["admin", "Админ"], ["expert", "Эксперт"]] as const).map(([mode, label]) => {
                  const active = mode === "expert" ? !me.data?.is_admin : !!me.data?.is_admin;
                  return (
                    <HintTarget key={mode} title={`Режим: ${label}`} body={mode === "expert" ? "Работать как обычный эксперт: правки идут черновиками, без админ-прав." : "Полные права супер-админа."}>
                      <button
                        onClick={() => {
                          document.cookie = mode === "expert"
                            ? "ir_act_as=expert; path=/; max-age=31536000"
                            : "ir_act_as=; path=/; max-age=0";
                          qc.invalidateQueries();   // роль поменялась → перечитать всё
                        }}
                        className={`px-2.5 py-1.5 transition ${active ? "bg-ink text-white font-semibold" : "text-ink-mute hover:text-ink hover:bg-white"}`}>
                        {label}
                      </button>
                    </HintTarget>
                  );
                })}
              </div>
            </div>
          )}
          {me.data?.is_admin && clientId ? (
            <HintTarget title="Админка" body="Журнал действий, пользователи и служебные настройки проекта.">
              <button
                onClick={() => { setOpen(false); nav(`/clients/${clientId}/admin`); }}
                className="w-full text-left px-3 py-2 text-[13px] text-ink-mute hover:bg-[#f6f6f1] hover:text-ink transition flex items-center gap-2"
              >
                <span>🛠</span> Админка
              </button>
            </HintTarget>
          ) : canSeeUsers && clientId ? (
            <HintTarget title="Пользователи" body="Участники системы и доступы к данным компании.">
              <button
                onClick={() => { setOpen(false); nav(`/clients/${clientId}/users`); }}
                className="w-full text-left px-3 py-2 text-[13px] text-ink-mute hover:bg-[#f6f6f1] hover:text-ink transition flex items-center gap-2"
              >
                <span>👥</span> Пользователи системы
              </button>
            </HintTarget>
          ) : null}
          <HintTarget title="Выйти" body="Завершить текущую сессию пользователя.">
            <button
              onClick={logout}
              className="w-full text-left px-3 py-2 text-[13px] text-ink-mute hover:bg-[#f6f6f1] hover:text-ink transition"
            >
              Выйти
            </button>
          </HintTarget>
        </div>
      )}
    </div>
  );
}
