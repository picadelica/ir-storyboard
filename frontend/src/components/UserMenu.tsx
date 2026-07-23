import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api";

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
      <button
        onClick={() => setOpen(o => !o)}
        className="w-7 h-7 rounded-full bg-ink/[0.06] text-ink text-[11px] font-semibold flex items-center justify-center hover:bg-ink/[0.1] transition"
        title={name}
        aria-label="Профиль"
      >
        {monogram(name)}
      </button>
      {open && (
        <div className="absolute right-0 mt-2 w-52 bg-white border border-ink-line rounded-xl py-1 z-50 shadow-sm">
          <div className="px-3 py-2 text-[13px] text-ink truncate border-b border-ink-line">{name}</div>
          {canSeeUsers && clientId && (
            <button
              onClick={() => { setOpen(false); nav(`/clients/${clientId}/users`); }}
              className="w-full text-left px-3 py-2 text-[13px] text-ink-mute hover:bg-ink/[0.04] hover:text-ink transition flex items-center gap-2"
              title="Пользователи системы (пока здесь — до отдельного админ-интерфейса)"
            >
              <span>👥</span> Пользователи системы
            </button>
          )}
          <button
            onClick={logout}
            className="w-full text-left px-3 py-2 text-[13px] text-ink-mute hover:bg-ink/[0.04] hover:text-ink transition"
          >
            Выйти
          </button>
        </div>
      )}
    </div>
  );
}
