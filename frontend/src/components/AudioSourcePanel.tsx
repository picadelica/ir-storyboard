import {
  forwardRef, useEffect, useImperativeHandle, useRef, useState,
} from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import type { TranscriptSegment } from "../types";

export interface AudioSourceHandle {
  /** Seek the player to `sec` and start playback. */
  seek: (sec: number) => void;
}

interface Props {
  clientId: string;
  sha: string;
  title?: string;
}

function fmtTime(sec: number): string {
  const t = Math.max(0, Math.floor(sec));
  const m = Math.floor(t / 60);
  const s = t % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

/**
 * Compact audio player for the original uploaded file plus an expandable
 * transcript panel. Both the player and the transcript segments seek the same
 * <audio> element. Exposes an imperative `seek(sec)` via ref so fact cards can
 * jump the player to a fact's snippet start.
 */
const AudioSourcePanel = forwardRef<AudioSourceHandle, Props>(
  function AudioSourcePanel({ clientId, sha, title }, ref) {
    const audioRef = useRef<HTMLAudioElement | null>(null);
    const [showTranscript, setShowTranscript] = useState(false);
    const [currentSec, setCurrentSec] = useState(0);
    const segRefs = useRef<Record<number, HTMLLIElement | null>>({});

    const src = api.audioSourceUrl(clientId, sha);

    const transcriptQ = useQuery({
      queryKey: ["audio-transcript", clientId, sha],
      queryFn: () => api.audioTranscript(clientId, sha),
      enabled: showTranscript && !!sha,
      staleTime: 5 * 60 * 1000,
    });

    function seek(sec: number) {
      const el = audioRef.current;
      if (!el) return;
      el.currentTime = Math.max(0, sec);
      void el.play().catch(() => { /* autoplay may be blocked; ignore */ });
    }

    useImperativeHandle(ref, () => ({ seek }), []);

    // Track playback position to highlight the active transcript segment.
    useEffect(() => {
      const el = audioRef.current;
      if (!el) return;
      const onTime = () => setCurrentSec(el.currentTime);
      el.addEventListener("timeupdate", onTime);
      return () => el.removeEventListener("timeupdate", onTime);
    }, []);

    const segments: TranscriptSegment[] = transcriptQ.data?.segments ?? [];
    const activeIdx = segments.findIndex(
      (s) => currentSec >= s.start && currentSec < s.end,
    );

    // Scroll the active segment into view when the panel is open.
    useEffect(() => {
      if (!showTranscript || activeIdx < 0) return;
      segRefs.current[activeIdx]?.scrollIntoView({ block: "nearest" });
    }, [activeIdx, showTranscript]);

    function seekToSegment(idx: number) {
      const s = segments[idx];
      if (s) seek(s.start);
    }

    return (
      <div className="space-y-2">
        <div className="flex items-center gap-3">
          <audio ref={audioRef} src={src} controls preload="metadata" className="h-8 flex-1 min-w-0" />
          <button
            type="button"
            onClick={() => setShowTranscript((v) => !v)}
            className="shrink-0 text-xs px-2.5 py-1 border border-ink-line rounded hover:bg-slate-50 text-ink-mute"
          >
            {showTranscript ? "Скрыть транскрипт" : "Транскрипт"}
          </button>
        </div>

        {showTranscript && (
          <div className="border border-ink-line rounded-lg bg-white max-h-72 overflow-y-auto p-2 text-sm">
            {transcriptQ.isLoading && (
              <div className="text-xs text-ink-mute p-2">Загрузка транскрипта…</div>
            )}
            {transcriptQ.isError && (
              <div className="text-xs text-red-600 p-2">
                Транскрипт недоступен ({String(transcriptQ.error)})
              </div>
            )}
            {transcriptQ.data && segments.length === 0 && (
              <div className="text-xs text-ink-mute p-2">Транскрипт пуст.</div>
            )}
            <ul className="space-y-0.5">
              {segments.map((s, i) => (
                <li
                  key={i}
                  ref={(el) => { segRefs.current[i] = el; }}
                  className={`flex gap-2 rounded px-1.5 py-1 cursor-pointer hover:bg-slate-50 ${
                    i === activeIdx ? "bg-violet-50" : ""
                  }`}
                  onClick={() => seekToSegment(i)}
                >
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); seekToSegment(i); }}
                    className="shrink-0 font-mono text-[11px] text-violet-600 hover:underline mt-0.5"
                  >
                    {fmtTime(s.start)}
                  </button>
                  <span className="text-slate-700 leading-snug">{s.text}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {title && <div className="sr-only">{title}</div>}
      </div>
    );
  },
);

export default AudioSourcePanel;
