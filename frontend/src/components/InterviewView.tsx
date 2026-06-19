import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import type { InterviewGuide } from "../types";

interface Props {
  clientId: string;
  onJumpToCell: (sid: string) => void;
}

export default function InterviewView({ clientId, onJumpToCell }: Props) {
  const qc = useQueryClient();
  // The generated guide lives in the query cache (keyed by client), not local
  // state — so it survives a tab switch / unmount; setQueryData also lands the
  // result even if the analyst navigates away while generation is still running.
  const guideQ = useQuery<InterviewGuide | null>({
    queryKey: ["interview-guide", clientId],
    queryFn: () => null,
    enabled: false,
    staleTime: Infinity,
    gcTime: Infinity,
  });
  const guide = guideQ.data ?? null;
  const gen = useMutation({
    mutationFn: async () => {
      const g = await api.interviewGuide(clientId);
      qc.setQueryData(["interview-guide", clientId], g);
      return g;
    },
  });

  return (
    <div className="p-5 max-w-3xl space-y-5">
      <div className="flex items-baseline justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold">Гайд интервью</h2>
          <p className="text-xs text-ink-mute mt-0.5">
            Грунтован на проверенной матрице: досье, диагноз и вопросы по дугам близости.
          </p>
        </div>
        <button
          onClick={() => gen.mutate()}
          disabled={gen.isPending}
          className="text-xs px-3 py-1.5 bg-ink text-white rounded hover:bg-black disabled:bg-slate-300 shrink-0"
        >
          {gen.isPending ? "Генерирую…" : guide ? "Перегенерировать" : "Сгенерировать гайд"}
        </button>
      </div>

      {gen.isPending && <div className="text-sm text-ink-mute">Читаю матрицу и собираю гайд…</div>}

      {guide && !guide.available && (
        <div className="bg-flag-grey-bg border border-flag-grey/40 rounded p-3 text-sm text-ink-mute">
          Не удалось сгенерировать (нет ключа LLM или пустой ответ). Попробуй ещё раз.
        </div>
      )}

      {guide?.available && (
        <>
          {guide.dossier && (
            <section className="bg-white rounded-lg border border-ink-line p-4">
              <h3 className="text-sm font-semibold mb-2">Досье</h3>
              <p className="text-sm leading-relaxed whitespace-pre-wrap">{guide.dossier}</p>
            </section>
          )}

          <section className="bg-white rounded-lg border border-ink-line p-4 space-y-2">
            <h3 className="text-sm font-semibold">Диагноз</h3>
            {guide.diagnosis.covered && (
              <div className="text-sm"><span className="text-ink-mute">Покрыто: </span>{guide.diagnosis.covered}</div>
            )}
            {guide.diagnosis.gaps && (
              <div className="text-sm"><span className="text-ink-mute">Зияет: </span>{guide.diagnosis.gaps}</div>
            )}
            {guide.diagnosis.priorities.length > 0 && (
              <div>
                <div className="text-xs text-ink-mute mb-1">Приоритеты на интервью</div>
                <ol className="list-decimal pl-5 text-sm space-y-0.5">
                  {guide.diagnosis.priorities.map((p, i) => <li key={i}>{p}</li>)}
                </ol>
              </div>
            )}
          </section>

          {guide.arcs.length === 0 ? (
            <div className="text-sm text-ink-mute italic">Вопросов нет — мало проверенных фактов.</div>
          ) : guide.arcs.map((arc, ai) => (
            <section key={ai} className="bg-white rounded-lg border border-ink-line p-4">
              <h3 className="text-sm font-semibold mb-3">{arc.title}</h3>
              <div className="space-y-3">
                {arc.questions.map((q, qi) => (
                  <div key={qi} className="border-l-2 border-ink-line pl-3">
                    <div className="text-sm font-medium leading-snug">{q.question}</div>
                    <div className="mt-1 flex items-center gap-1.5 flex-wrap">
                      {q.targets.map(t => (
                        <button key={t} onClick={() => onJumpToCell(t)}
                          className="text-[11px] font-mono text-blue-600 hover:underline border border-ink-line rounded px-1.5">{t} →</button>
                      ))}
                    </div>
                    {(q.know || q.close) && (
                      <div className="mt-1 text-xs text-ink-mute">
                        {q.know && <span>знаем: {q.know}. </span>}
                        {q.close && <span>закрываем: {q.close}.</span>}
                      </div>
                    )}
                    {q.grounds.length > 0 ? (
                      <details className="mt-1">
                        <summary className="text-[11px] text-blue-600 cursor-pointer select-none">
                          основано на {q.grounds.length} факт(ах)
                        </summary>
                        <ul className="mt-1 list-disc pl-4 text-xs text-ink-mute space-y-0.5">
                          {q.grounds.map(g => <li key={g.id}>{g.text}</li>)}
                        </ul>
                      </details>
                    ) : (
                      <div className="mt-1 text-[11px] text-amber-700">открытый вопрос — нет опоры на факт</div>
                    )}
                    {q.followups.length > 0 && (
                      <ul className="mt-1 list-disc pl-4 text-xs text-ink-mute space-y-0.5">
                        {q.followups.map((f, fi) => <li key={fi}>{f}</li>)}
                      </ul>
                    )}
                  </div>
                ))}
              </div>
            </section>
          ))}
        </>
      )}

      {!guide && !gen.isPending && (
        <div className="text-sm text-ink-mute italic">
          Нажми «Сгенерировать гайд» — на основе проверенных фактов соберётся персональный план интервью.
        </div>
      )}
    </div>
  );
}
