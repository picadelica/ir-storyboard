import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import type { YouTubeFact, YouTubePreviewResult, YouTubeSkipped } from "../types";

interface Props {
  clientId: string;
  onJumpToCell: (sid: string) => void;
}

const FLAG_COLORS: Record<string, string> = {
  green: "text-emerald-700 bg-emerald-50 border-emerald-200",
  red: "text-red-700 bg-red-50 border-red-200",
  grey: "text-slate-500 bg-slate-50 border-slate-200",
};

function fmtDuration(sec: number): string {
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export default function IngestYouTube({ clientId, onJumpToCell }: Props) {
  const [screen, setScreen] = useState<"input" | "preview" | "done">("input");
  const [url, setUrl] = useState("");
  const [preview, setPreview] = useState<YouTubePreviewResult | null>(null);
  const [dropped, setDropped] = useState<Set<number>>(new Set());
  const [overrides, setOverrides] = useState<Set<number>>(new Set());
  const [expertEmail, setExpertEmail] = useState("");
  const qc = useQueryClient();

  const history = useQuery({
    queryKey: ["yt-ingest-history", clientId],
    queryFn: () => api.youtubeHistory(clientId),
  });

  const previewMut = useMutation({
    mutationFn: () => api.youtubePreview(clientId, url),
    onSuccess: (data) => {
      setPreview(data);
      setDropped(new Set());
      setOverrides(new Set());
      setScreen("preview");
    },
  });

  const commitMut = useMutation({
    mutationFn: () => {
      if (!preview) throw new Error("No preview");
      const accepted = preview.facts
        .map((_, i) => i)
        .filter((i) => !dropped.has(i));
      const ov = Array.from(overrides).map((i) => ({
        fact_idx: i,
        force_keep: true,
      }));
      return api.youtubeCommit(
        clientId,
        preview.preview_id,
        accepted,
        ov,
        expertEmail || "anonymous@example.com",
      );
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["matrix", clientId] });
      qc.invalidateQueries({ queryKey: ["punch", clientId] });
      qc.invalidateQueries({ queryKey: ["yt-ingest-history", clientId] });
      setScreen("done");
    },
  });

  const keptCount = preview
    ? preview.facts.filter((_, i) => !dropped.has(i)).length
    : 0;

  // ── Input screen ─────────────────────────────────────────────────────────

  if (screen === "input") {
    return (
      <div className="p-5 max-w-2xl space-y-6">
        <div className="flex items-baseline justify-between">
          <h2 className="text-lg font-semibold">Ingest YouTube Interview</h2>
          {history.data && history.data.length > 0 && (
            <span className="text-xs text-ink-mute">
              {history.data.length} previous ingest{history.data.length !== 1 ? "s" : ""}
            </span>
          )}
        </div>

        <div className="space-y-2">
          <label className="block text-xs font-medium text-ink-mute">YouTube URL</label>
          <div className="flex gap-2">
            <input
              type="url"
              placeholder="https://youtube.com/watch?v=..."
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && url.trim()) previewMut.mutate();
              }}
              className="flex-1 text-sm border border-ink-line rounded px-3 py-2 focus:outline-none focus:ring-1 focus:ring-ink"
            />
            <button
              onClick={() => previewMut.mutate()}
              disabled={!url.trim() || previewMut.isPending}
              className={`px-4 py-2 text-sm rounded font-medium transition ${
                !url.trim() || previewMut.isPending
                  ? "bg-slate-200 text-slate-400 cursor-not-allowed"
                  : "bg-ink text-white hover:bg-ink/90"
              }`}
            >
              {previewMut.isPending ? "Processing…" : "Preview"}
            </button>
          </div>
          {previewMut.isPending && (
            <div className="text-xs text-ink-mute">
              Downloading audio and transcribing… (~5–10 min for a 1h video)
            </div>
          )}
        </div>

        {previewMut.isError && (
          <div className="text-sm text-red-600 bg-red-50 rounded p-3">
            {String(previewMut.error)}
          </div>
        )}

        {/* History table */}
        {history.data && history.data.length > 0 && (
          <div>
            <div className="text-xs font-medium text-ink-mute mb-2 uppercase tracking-wide">
              Previous ingests
            </div>
            <table className="w-full text-xs">
              <thead className="text-[10px] text-ink-mute uppercase">
                <tr>
                  <th className="text-left py-1 pr-3">Date</th>
                  <th className="text-left py-1 pr-3">Video</th>
                  <th className="text-right py-1 pr-3">Facts</th>
                  <th className="text-right py-1">Warnings</th>
                </tr>
              </thead>
              <tbody>
                {history.data.map((row) => (
                  <tr key={row.id} className="border-t border-ink-line">
                    <td className="py-1.5 pr-3 font-mono">
                      {new Date(row.parsed_at).toLocaleDateString()}
                    </td>
                    <td className="py-1.5 pr-3 truncate max-w-[140px]">
                      {row.video_id ?? "—"}
                    </td>
                    <td className="py-1.5 pr-3 text-right">{row.facts_committed}</td>
                    <td className="py-1.5 text-right">{row.channel_warnings}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    );
  }

  // ── Done screen ────────────────────────────────────────────────────────────

  if (screen === "done" && commitMut.data) {
    const r = commitMut.data;
    return (
      <div className="p-5 max-w-2xl space-y-4">
        <div className="bg-emerald-50 border border-emerald-200 rounded-lg p-4">
          <div className="font-semibold text-emerald-800 mb-1">Saved to matrix</div>
          <div className="text-sm text-emerald-700">
            {r.committed} fact{r.committed !== 1 ? "s" : ""} committed ·{" "}
            {r.skipped} skipped (duplicates or dropped)
          </div>
        </div>
        <div className="flex gap-3">
          <button
            onClick={() => onJumpToCell(preview?.facts[0]?.subsection_id ?? "2.1")}
            className="px-4 py-2 text-sm bg-ink text-white rounded hover:bg-ink/90"
          >
            View in Matrix
          </button>
          <button
            onClick={() => {
              setScreen("input");
              setPreview(null);
              setUrl("");
              previewMut.reset();
              commitMut.reset();
            }}
            className="px-4 py-2 text-sm border border-ink-line rounded hover:bg-slate-50"
          >
            Ingest another
          </button>
        </div>
      </div>
    );
  }

  // ── Preview screen ─────────────────────────────────────────────────────────

  if (!preview) return null;

  return (
    <div className="p-5 max-w-4xl space-y-6">
      <div className="flex items-baseline justify-between">
        <div>
          <h2 className="text-lg font-semibold">Preview</h2>
          <div className="text-xs text-ink-mute mt-0.5">
            {preview.facts.length} facts · {preview.skipped.length} skipped by LayerGuard
          </div>
        </div>
        <button
          onClick={() => { setScreen("input"); previewMut.reset(); }}
          className="text-xs text-ink-mute hover:text-ink"
        >
          ← Back
        </button>
      </div>

      {/* Video meta */}
      <div className="bg-slate-50 border border-ink-line rounded-lg p-4 space-y-1 text-sm">
        <div className="font-medium truncate">{preview.meta.title}</div>
        <div className="text-xs text-ink-mute">
          {preview.meta.channel_name} · {fmtDuration(preview.meta.duration_sec)}
          {preview.from_cache && " · transcript from cache"}
          {preview.transcribe_cost_usd != null &&
            ` · ~$${preview.transcribe_cost_usd.toFixed(2)} (OpenAI Whisper)`}
        </div>
        <a
          href={preview.meta.canonical_url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs text-blue-600 hover:underline"
        >
          {preview.meta.canonical_url}
        </a>
      </div>

      {/* Parser notes */}
      {preview.notes.length > 0 && (
        <details className="text-xs text-ink-mute">
          <summary className="cursor-pointer hover:text-ink">
            {preview.notes.length} note{preview.notes.length !== 1 ? "s" : ""}
          </summary>
          <ul className="mt-1 space-y-0.5 pl-3">
            {preview.notes.map((n, i) => <li key={i}>— {n}</li>)}
          </ul>
        </details>
      )}

      {/* Facts */}
      <div>
        <div className="text-xs font-medium uppercase text-ink-mute tracking-wide mb-2">
          Facts ({preview.facts.length})
        </div>
        <div className="space-y-2">
          {preview.facts.map((fact, idx) => (
            <FactCard
              key={idx}
              fact={fact}
              dropped={dropped.has(idx)}
              onToggleDrop={() => setDropped((prev) => {
                const next = new Set(prev);
                next.has(idx) ? next.delete(idx) : next.add(idx);
                return next;
              })}
            />
          ))}
        </div>
      </div>

      {/* Skipped facts (LayerGuard) */}
      {preview.skipped.length > 0 && (
        <div>
          <div className="text-xs font-medium uppercase text-ink-mute tracking-wide mb-2">
            Skipped by LayerGuard ({preview.skipped.length})
          </div>
          <div className="space-y-2">
            {preview.skipped.map((s, idx) => (
              <SkippedCard
                key={idx}
                skipped={s}
                overridden={overrides.has(idx)}
                onToggleOverride={() => setOverrides((prev) => {
                  const next = new Set(prev);
                  next.has(idx) ? next.delete(idx) : next.add(idx);
                  return next;
                })}
              />
            ))}
          </div>
        </div>
      )}

      {/* Commit bar */}
      <div className="sticky bottom-0 bg-white border-t border-ink-line pt-4 pb-2 space-y-3">
        <div className="flex items-center gap-3">
          <input
            type="email"
            placeholder="your@email.com"
            value={expertEmail}
            onChange={(e) => setExpertEmail(e.target.value)}
            className="flex-1 text-sm border border-ink-line rounded px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-ink"
          />
          <button
            onClick={() => commitMut.mutate()}
            disabled={keptCount === 0 || commitMut.isPending}
            className={`px-5 py-2 text-sm rounded font-medium transition ${
              keptCount === 0 || commitMut.isPending
                ? "bg-slate-200 text-slate-400 cursor-not-allowed"
                : "bg-ink text-white hover:bg-ink/90"
            }`}
          >
            {commitMut.isPending
              ? "Saving…"
              : `Save ${keptCount} fact${keptCount !== 1 ? "s" : ""} to matrix`}
          </button>
        </div>
        {keptCount === 0 && (
          <div className="text-xs text-red-600">Drop all facts — nothing to commit</div>
        )}
        {commitMut.isError && (
          <div className="text-xs text-red-600">{String(commitMut.error)}</div>
        )}
      </div>
    </div>
  );
}

// ── FactCard ──────────────────────────────────────────────────────────────────

interface FactCardProps {
  fact: YouTubeFact;
  dropped: boolean;
  onToggleDrop: () => void;
}

function FactCard({ fact, dropped, onToggleDrop }: FactCardProps) {
  const flagStyle = FLAG_COLORS[fact.flag] ?? FLAG_COLORS.grey;
  const tSec = Math.floor(fact.snippet_start_sec);

  return (
    <div className={`border rounded-lg p-3 text-sm transition ${
      dropped ? "opacity-40 bg-slate-50" : "bg-white"
    } ${flagStyle}`}>
      <div className="flex items-start gap-2">
        <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-white/60 border shrink-0 mt-0.5">
          L{fact.subsection_id}
        </span>
        <span className={`text-[10px] px-1.5 py-0.5 rounded border shrink-0 mt-0.5 ${flagStyle}`}>
          {fact.flag}
        </span>

        <div className="flex-1 min-w-0">
          <div className={dropped ? "line-through" : ""}>{fact.text}</div>
          {fact.evidence_snippet && (
            <div className="mt-1 text-xs text-ink-mute italic line-clamp-2">
              "{fact.evidence_snippet}"
            </div>
          )}
          <div className="mt-1 flex items-center gap-2">
            <a
              href={fact.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-[10px] text-blue-600 hover:underline"
              onClick={(e) => e.stopPropagation()}
            >
              ▶ {Math.floor(tSec / 60)}:{String(tSec % 60).padStart(2, "0")}
            </a>
            {fact.needs_review && (
              <span className="text-[10px] text-amber-600">needs review</span>
            )}
          </div>
        </div>

        <button
          onClick={onToggleDrop}
          className={`text-[10px] px-2 py-0.5 border rounded shrink-0 ${
            dropped
              ? "border-emerald-200 text-emerald-600 hover:bg-emerald-50"
              : "border-red-200 text-red-600 hover:bg-red-50"
          }`}
        >
          {dropped ? "restore" : "drop"}
        </button>
      </div>
    </div>
  );
}

// ── SkippedCard ───────────────────────────────────────────────────────────────

interface SkippedCardProps {
  skipped: YouTubeSkipped;
  overridden: boolean;
  onToggleOverride: () => void;
}

function SkippedCard({ skipped, overridden, onToggleOverride }: SkippedCardProps) {
  return (
    <div className={`border rounded-lg p-3 text-sm ${
      overridden ? "border-amber-300 bg-amber-50" : "border-slate-200 bg-slate-50 opacity-70"
    }`}>
      <div className="flex items-start gap-2">
        <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-white/60 border shrink-0 mt-0.5 text-slate-500">
          L{skipped.subsection_id}
        </span>
        <span className="text-[10px] px-1.5 py-0.5 rounded border border-slate-200 text-slate-500 shrink-0 mt-0.5">
          ⚠ skipped
        </span>

        <div className="flex-1 min-w-0">
          <div className="text-slate-600">{skipped.text}</div>
          <div className="text-[10px] text-slate-400 mt-0.5">{skipped.reason}</div>
          {skipped.evidence_snippet && (
            <div className="mt-1 text-xs text-ink-mute italic line-clamp-2">
              "{skipped.evidence_snippet}"
            </div>
          )}
        </div>

        {skipped.override_allowed && (
          <button
            onClick={onToggleOverride}
            className={`text-[10px] px-2 py-0.5 border rounded shrink-0 ${
              overridden
                ? "border-amber-400 text-amber-700 bg-amber-100"
                : "border-slate-300 text-slate-500 hover:border-amber-300 hover:text-amber-600"
            }`}
          >
            {overridden ? "undo override" : "override & keep"}
          </button>
        )}
      </div>
    </div>
  );
}
