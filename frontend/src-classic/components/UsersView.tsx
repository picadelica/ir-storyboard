import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import type { UserOverview } from "../types";

function fmtWhen(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso.replace(" ", "T") + (iso.includes("Z") ? "" : "Z"));
  if (isNaN(d.getTime())) return iso;
  const days = Math.floor((Date.now() - d.getTime()) / 86400_000);
  if (days <= 0) return "сегодня";
  if (days === 1) return "вчера";
  if (days < 30) return `${days} дн. назад`;
  return d.toLocaleDateString("ru-RU");
}

export default function UsersView() {
  const users = useQuery<UserOverview[]>({
    queryKey: ["users-overview"],
    queryFn: api.usersOverview,
    retry: false,
  });

  return (
    <div className="p-5 max-w-4xl space-y-4">
      <div>
        <h2 className="text-lg font-semibold">Пользователи системы</h2>
        <div className="text-xs text-ink-mute mt-0.5">
          Кто есть кто: роль (админ / владелец данных каких компаний) и активность.
          Имена приходят из Telegram при входе.
        </div>
      </div>

      {users.isLoading && <div className="text-sm text-ink-mute">Загрузка…</div>}
      {users.isError && (
        <div className="text-sm text-red-600">
          {String(users.error).includes("403")
            ? "Доступно владельцам данных и супер-админу."
            : String(users.error)}
        </div>
      )}

      {users.data && users.data.length === 0 && (
        <div className="text-sm text-ink-mute">Пока никто не заходил в систему.</div>
      )}

      {users.data && users.data.length > 0 && (
        <div className="border border-ink-line rounded-lg divide-y divide-ink-line bg-white">
          {users.data.map((u) => <UserRow key={u.tid} u={u} />)}
        </div>
      )}
    </div>
  );
}

function UserRow({ u }: { u: UserOverview }) {
  return (
    <div className="flex items-start gap-4 px-4 py-3">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-semibold">{u.name || "(без имени)"}</span>
          {u.username && <span className="text-xs text-ink-mute">@{u.username}</span>}
          <span className="font-mono text-[10px] px-1 py-0.5 rounded bg-slate-100 border border-slate-200 text-slate-500">
            tid {u.tid}
          </span>
          {u.is_admin && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-100 border border-amber-300 text-amber-800 font-medium">
              👑 админ
            </span>
          )}
        </div>
        <div className="mt-1 text-xs text-ink-mute">
          {u.owned_clients.length > 0 ? (
            <span>
              Владелец данных:{" "}
              <span className="text-ink">{u.owned_clients.join(", ")}</span>
            </span>
          ) : (
            <span>Контрибьютор</span>
          )}
        </div>
      </div>
      <div className="shrink-0 text-right text-xs text-ink-mute space-y-0.5">
        <div>
          <span className="text-ink font-medium">{u.actions}</span> действий над карточками
        </div>
        <div>
          {u.facts_created > 0 && <><span className="text-ink font-medium">{u.facts_created}</span> внёс</>}
          {u.facts_approved > 0 && (
            <>{u.facts_created > 0 ? " · " : ""}<span className="text-ink font-medium">{u.facts_approved}</span> одобрил</>
          )}
        </div>
        <div>был {fmtWhen(u.last_seen)}</div>
      </div>
    </div>
  );
}
