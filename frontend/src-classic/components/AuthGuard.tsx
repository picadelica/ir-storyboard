import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";

export default function AuthGuard({ children }: { children: React.ReactNode }) {
  const me = useQuery({ queryKey: ["me"], queryFn: api.authMe, retry: false });

  if (me.isLoading) {
    return <Centered><div className="text-sm text-ink-mute">Загрузка…</div></Centered>;
  }
  if (me.isError) {
    return <Login onAuthed={() => me.refetch()} />;
  }
  return <>{children}</>;
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="h-screen flex items-center justify-center" style={{ background: "#fdf8f8" }}>
      {children}
    </div>
  );
}

type State = "idle" | "waiting" | "denied" | "error";

function Login({ onAuthed }: { onAuthed: () => void }) {
  const [state, setState] = useState<State>("idle");
  const [link, setLink] = useState("");
  const tokenRef = useRef("");

  async function start() {
    try {
      setState("waiting");
      const r = await api.authStart();
      tokenRef.current = r.token;
      setLink(r.deep_link);
      window.open(r.deep_link, "_blank", "noopener");
    } catch {
      setState("error");
    }
  }

  useEffect(() => {
    if (state !== "waiting") return;
    const iv = setInterval(async () => {
      try {
        const s = await api.authStatus(tokenRef.current);
        if (s.status === "approved") { clearInterval(iv); onAuthed(); }
        else if (s.status === "denied") { clearInterval(iv); setState("denied"); }
        else if (s.status === "expired") { clearInterval(iv); setState("idle"); }
      } catch { /* transient — keep polling */ }
    }, 2000);
    return () => clearInterval(iv);
  }, [state]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <Centered>
      <div className="w-[360px] bg-white rounded-2xl border border-ink-line px-7 py-8 text-center">
        <div className="text-xl font-semibold tracking-tight text-ink">StoryBoard</div>
        <div className="text-sm text-ink-mute mt-1.5 leading-snug">
          Доступ по приглашению в рабочую группу Telegram.
        </div>

        {state === "idle" && (
          <button
            onClick={start}
            className="mt-6 w-full py-2.5 rounded-xl bg-ink text-white text-sm font-medium hover:opacity-90 transition"
          >
            Войти через Telegram
          </button>
        )}

        {state === "waiting" && (
          <div className="mt-6 space-y-3">
            <div className="text-sm text-ink">Открой бота и нажми <span className="font-medium">Start</span>.</div>
            <a href={link} target="_blank" rel="noopener noreferrer"
               className="block w-full py-2.5 rounded-xl bg-ink text-white text-sm font-medium hover:opacity-90 transition">
              Открыть бота
            </a>
            <div className="text-xs text-ink-mute">Ждём подтверждения…</div>
          </div>
        )}

        {state === "denied" && (
          <div className="mt-6 space-y-3">
            <div className="text-sm text-flag-red">Доступа нет — тебя нет в рабочей группе.</div>
            <button onClick={() => setState("idle")}
              className="text-xs text-ink-mute hover:text-ink underline">Попробовать снова</button>
          </div>
        )}

        {state === "error" && (
          <div className="mt-6 space-y-3">
            <div className="text-sm text-flag-red">Не удалось начать вход.</div>
            <button onClick={() => setState("idle")}
              className="text-xs text-ink-mute hover:text-ink underline">Ещё раз</button>
          </div>
        )}
      </div>
    </Centered>
  );
}
