import { useQuery } from "@tanstack/react-query";
import ReactMarkdown from "react-markdown";
import { api } from "../api";

export default function InterviewView({ clientId }: { clientId: string }) {
  const q = useQuery({
    queryKey: ["interview", clientId],
    queryFn: () => api.interviewQuestions(clientId),
  });

  const copyToClipboard = async () => {
    if (q.data) {
      await navigator.clipboard.writeText(q.data.markdown);
      alert("Скопировано в буфер обмена");
    }
  };

  return (
    <div className="p-5 max-w-3xl">
      <div className="flex items-baseline justify-between mb-4">
        <h2 className="text-lg font-semibold">Interview questions</h2>
        <button onClick={copyToClipboard}
          className="text-xs px-3 py-1.5 bg-ink text-white rounded hover:bg-black">
          Copy markdown
        </button>
      </div>
      <div className="bg-white rounded-lg border border-ink-line p-6">
        {q.isLoading && <div className="text-sm text-ink-mute">Loading…</div>}
        {q.data && (
          <article className="prose-md">
            <ReactMarkdown>{q.data.markdown}</ReactMarkdown>
          </article>
        )}
      </div>
    </div>
  );
}
