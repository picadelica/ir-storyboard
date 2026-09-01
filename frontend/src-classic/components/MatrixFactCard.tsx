import FlagDot from "./FlagDot";
import SourceLine from "./SourceLine";
import type { DupFact } from "../types";

/** A fact rendered the way it looks in the matrix cell drawer: flag dot + text +
 *  source line (web link / file + timecode for interviews). Read-only; used in the
 *  merge preview (originals on the left). */
export default function MatrixFactCard({
  fact, clientId, faded = false,
}: { fact: DupFact; clientId: string; faded?: boolean }) {
  return (
    <div className={`border border-l-4 rounded-lg p-3 bg-white text-sm ${faded ? "opacity-40" : ""} ${
      fact.flag === "green" ? "border-l-emerald-400" :
      fact.flag === "red" ? "border-l-red-400" : "border-l-slate-300"
    }`}>
      <div className="flex items-start gap-2">
        <FlagDot flag={fact.flag} className="mt-1.5" />
        <div className="flex-1 min-w-0">
          <div className={faded ? "line-through text-ink-mute" : "text-slate-800"}>{fact.text}</div>
          <SourceLine
            client_id={clientId}
            channel={fact.source_channel}
            source_url={fact.source_url}
            source_title={fact.source_title}
            source_publisher={fact.source_publisher}
            source_archive_url={fact.source_archive_url}
            ingest_audit_id={fact.ingest_audit_id || null}
            ingest_kind={fact.ingest_kind || null}
            timestamp_sec={fact.snippet_start_sec ?? undefined}
            captured_at={fact.captured_at}
          />
        </div>
        <span className="text-[10px] font-mono text-ink-mute shrink-0">#{fact.id}</span>
      </div>
    </div>
  );
}
