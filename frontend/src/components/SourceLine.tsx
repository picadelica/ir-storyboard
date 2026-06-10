import type { Channel } from "../types";

interface SourceLineProps {
  channel?: Channel | string;
  source_url?: string | null;
  source_title?: string;
  source_publisher?: string;
  source_archive_url?: string | null;
  ingest_audit_id?: string | null;
  client_id: string;
  captured_at?: string;
  timestamp_sec?: number;
}

type Kind = "web" | "llm_report" | "offline" | "none";

function pickKind(props: SourceLineProps): Kind {
  const { source_url, ingest_audit_id, channel, source_title } = props;
  if (source_url && /^https?:\/\//i.test(source_url)) return "web";
  if (!source_url && ingest_audit_id) return "llm_report";
  if (!source_url && channel === "offline_interview" && source_title) return "offline";
  return "none";
}

function hostOf(url: string): string {
  try {
    return new URL(url).host.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function fmtTime(sec: number): string {
  const t = Math.floor(sec);
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const s = t % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function ChannelBadge({ channel }: { channel?: string }) {
  if (!channel) return null;
  return (
    <span className="px-1.5 py-0.5 bg-white border border-ink-line rounded text-[11px] font-mono text-ink-mute">
      {channel}
    </span>
  );
}

export default function SourceLine(props: SourceLineProps) {
  const kind = pickKind(props);
  const {
    source_url, source_title, source_archive_url, ingest_audit_id,
    client_id, captured_at, timestamp_sec, channel,
  } = props;

  const capturedDate = (captured_at ?? "").slice(0, 10);
  const archiving =
    kind === "web" && !source_archive_url
    && (channel === "online_research" || channel === "online_interview" || channel === "archival");

  return (
    <div className="mt-2 text-xs text-ink-mute flex flex-wrap items-center gap-x-2 gap-y-1">
      {kind === "web" && source_url && (
        <>
          <ChannelBadge channel={channel} />
          <span className="truncate max-w-[16rem]" title={source_title || source_url}>
            {source_title || hostOf(source_url)}
          </span>
          <a
            href={source_url}
            target="_blank"
            rel="noreferrer"
            className="text-blue-600 underline"
            title={source_url}
          >↗</a>
          {source_archive_url && (
            <a
              href={source_archive_url}
              target="_blank"
              rel="noreferrer"
              className="text-emerald-600"
              title="Wayback snapshot"
            >📦</a>
          )}
          {archiving && (
            <span className="text-amber-500" title="Archiving in background…">⏳</span>
          )}
          {typeof timestamp_sec === "number" && timestamp_sec > 0 && (
            <span className="text-violet-600 font-mono" title="Timestamp anchor">
              ▶ {fmtTime(timestamp_sec)}
            </span>
          )}
        </>
      )}

      {kind === "llm_report" && ingest_audit_id && (
        <>
          <ChannelBadge channel={channel} />
          <span>LLM Report #{ingest_audit_id.slice(0, 8)}</span>
          <a
            href={`/api/clients/${client_id}/ingest/llm-report/${ingest_audit_id}/file`}
            target="_blank"
            rel="noreferrer"
            className="text-violet-600 underline"
            title="Download original LLM report"
          >↓ скачать отчёт</a>
        </>
      )}

      {kind === "offline" && (
        <>
          <ChannelBadge channel={channel} />
          <span className="truncate max-w-[18rem]">{source_title}</span>
          <span title="Offline interview">🎙 offline</span>
        </>
      )}

      {kind === "none" && (
        <span className="text-amber-600">⚠ no source</span>
      )}

      {capturedDate && (
        <span className="ml-auto font-mono text-[11px]">{capturedDate}</span>
      )}
    </div>
  );
}
