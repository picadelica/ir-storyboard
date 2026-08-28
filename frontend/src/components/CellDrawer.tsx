import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import type { PointerEvent as ReactPointerEvent, ReactNode } from "react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { layerNameRu, subsectionNameRu } from "../lib/matrixLabels";
import { displayWorkBody, displayWorkTitle, isEmptyCellRedundantWorkTitle, isFirstMaterialWorkTitle, isInterviewWorkTitle } from "../lib/workItemDisplay";
import type { Channel, Entity, Fact, Flag, Layer, PunchList, WorkItem } from "../types";
import SourceLine from "./SourceLine";
import AudioSourcePanel, { type AudioSourceHandle } from "./AudioSourcePanel";
import FlagDot from "./FlagDot";

function SmoothCollapse({ open, children }: { open: boolean; children: ReactNode }) {
  const [mounted, setMounted] = useState(open);
  const [visible, setVisible] = useState(open);
  useEffect(() => {
    if (open) {
      setMounted(true);
      setVisible(false);
      const frame = window.requestAnimationFrame(() => {
        window.requestAnimationFrame(() => setVisible(true));
      });
      return () => window.cancelAnimationFrame(frame);
    }
    setVisible(false);
    const timer = window.setTimeout(() => setMounted(false), 320);
    return () => window.clearTimeout(timer);
  }, [open]);

  if (!mounted) return null;

  return (
    <div
      className={`grid transition-[grid-template-rows,opacity] duration-300 ease-out ${
        visible ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0"
      }`}
      aria-hidden={!visible}
    >
      <div className="min-h-0 overflow-hidden">
        {children}
      </div>
    </div>
  );
}

function monoColor(name: string): string {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
  return `hsl(${h % 360} 42% 42%)`;
}

// мини-фавикон компании (лого или двухбуквенная монограмма) для пометки карточки факта
function CompanyFavicon({ name, logo }: { name: string; logo?: string }) {
  const [bad, setBad] = useState(false);
  const initials = name.split(/\s+/).filter(Boolean).map(w => w[0]).join("").slice(0, 2).toUpperCase() || "—";
  return logo && !bad
    ? <img src={logo} alt="" onError={() => setBad(true)} className="w-4 h-4 rounded object-cover" />
    : <span className="w-4 h-4 rounded grid place-items-center text-[7px] font-semibold text-white select-none" style={{ background: monoColor(name) }}>{initials}</span>;
}

interface Props {
  clientId: string;
  subsectionId: string;
  onClose: () => void;
  layers?: Layer[];
  focusFactId?: number;   // из поиска: подсветить/раскрыть эту карточку
  auditFocus?: "all";
}

const ACTIVE_WORK_STATUSES = new Set(["queued", "in_progress", "needs_review"]);

type DrawerTaskCard = {
  key: string;
  title: string;
  body: string;
  tone: "grey" | "green" | "amber";
  meta?: string;
  createdAt?: string;
  relatedFactId?: number;
  greyFacts?: Array<{ id: number; text: string }>;
  firstMaterialActions?: string[];
};

function isReviewFact(f: Fact): boolean {
  // Режим «Ревью» в матрице считается из review-queue: это именно карточки,
  // ожидающие решения владельца/аналитика, а не все active-факты без verification.
  return f.state === "review";
}

function factTime(f: Fact): number {
  if (!f.captured_at) return 0;
  const normalized = f.captured_at.includes("T") ? f.captured_at : f.captured_at.replace(" ", "T");
  const ts = Date.parse(normalized.endsWith("Z") ? normalized : `${normalized}Z`);
  return Number.isFinite(ts) ? ts : 0;
}

function factDay(f: Fact): string {
  return (f.captured_at || "").slice(0, 10);
}

function mustScore(f: Fact): number {
  if (!f.must_have) return 0;
  return f.must_have_by === "expert" ? 2 : 1;
}

function compareFactsForDrawer(a: Fact, b: Fact): number {
  const ao = typeof a.sort_order === "number" ? a.sort_order : null;
  const bo = typeof b.sort_order === "number" ? b.sort_order : null;
  if (ao !== null || bo !== null) {
    if (ao === null) return 1;
    if (bo === null) return -1;
    if (ao !== bo) return ao - bo;
  }
  const at = factTime(a);
  const bt = factTime(b);
  if (at !== bt) return bt - at;
  const sameDay = factDay(a) && factDay(a) === factDay(b);
  if (sameDay) {
    const am = mustScore(a);
    const bm = mustScore(b);
    if (am !== bm) return bm - am;
  }
  return b.id - a.id;
}

function compareFactsByDate(a: Fact, b: Fact): number {
  const at = factTime(a);
  const bt = factTime(b);
  if (at !== bt) return bt - at;
  return b.id - a.id;
}

function workStatusLabel(status: WorkItem["status"]): string {
  switch (status) {
    case "queued": return "в очереди";
    case "in_progress": return "в работе";
    case "needs_review": return "на проверке";
    case "blocked": return "заблокировано";
    case "done": return "готово";
    case "cancelled": return "отменено";
    default: return status;
  }
}

function gapPlural(n: number) {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return "пробел";
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return "пробела";
  return "пробелов";
}

function questionPlural(n: number) {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return "открытый вопрос";
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return "открытых вопроса";
  return "открытых вопросов";
}

export default function CellDrawer({ clientId, subsectionId, onClose, layers, focusFactId, auditFocus }: Props) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const facts = useQuery<Fact[]>({
    queryKey: ["facts", clientId, subsectionId],
    queryFn: () => api.cellFacts(clientId, subsectionId),
  });
  const punch = useQuery<PunchList>({
    queryKey: ["punch", clientId],
    queryFn: () => api.punchList(clientId),
    enabled: !!auditFocus,
  });
  const workItems = useQuery<WorkItem[]>({
    queryKey: ["work-items", clientId],
    queryFn: () => api.listWorkItems(clientId),
    enabled: !!auditFocus,
  });

  // роль: одобрять черновики может владелец данных / супер-админ (локально без auth — все)
  const me = useQuery({ queryKey: ["me"], queryFn: api.authMe, retry: false });
  const client = useQuery({ queryKey: ["client", clientId], queryFn: () => api.getClient(clientId) });
  const canApprove = !me.data?.auth || !!me.data?.is_admin
    || (client.data?.owner_tid != null && me.data?.tid === client.data.owner_tid);

  const subsection = layers
    ?.flatMap(L => L.subsections.map(s => ({ ...s, layer: L })))
    .find(s => s.id === subsectionId);
  const subsectionTitle = subsectionNameRu(subsectionId, subsection?.name ?? subsectionId);
  // тег «про какую компанию» доступен на ВСЕХ карточках: если факт про другую компанию
  // (не базовую) — это сильный сигнал классификатору отправить его в слои истории фаундера (L2).
  const allowAboutCompany = true;

  const [editingId, setEditingId] = useState<number | null>(null);
  const [draftText, setDraftText] = useState("");
  const [draftFlag, setDraftFlag] = useState<Flag>("green");
  const [draftRationale, setDraftRationale] = useState("");
  const [draftTitle, setDraftTitle] = useState("");
  const [draftAbout, setDraftAbout] = useState("");

  // Audio source player: one open panel at a time, keyed by fact id.
  const [audioPanel, setAudioPanel] = useState<{ factId: number; sha: string } | null>(null);
  const audioRef = useRef<AudioSourceHandle | null>(null);

  const openAudio = (factId: number, sha: string, sec: number) => {
    if (audioPanel?.factId === factId) {
      // Already open for this fact — just seek.
      audioRef.current?.seek(sec);
    } else {
      setAudioPanel({ factId, sha });
      // Seek once the panel (and its <audio>) has mounted.
      setTimeout(() => audioRef.current?.seek(sec), 0);
    }
  };

  const [showAdd, setShowAdd] = useState(false);
  const [showHidden, setShowHidden] = useState(false);   // collapsible for merged-away cards
  const [factSortMode, setFactSortMode] = useState<"custom" | "date">("custom");
  const [factSortDir, setFactSortDir] = useState<"desc" | "asc">("desc");
  const [taskSortMode, setTaskSortMode] = useState<"custom" | "date">("custom");
  const [taskSortDir, setTaskSortDir] = useState<"desc" | "asc">("desc");
  const [taskOrderKeys, setTaskOrderKeys] = useState<string[]>([]);
  const [expandedTaskKeys, setExpandedTaskKeys] = useState<Set<string>>(new Set());
  const toggleTask = (key: string) => setExpandedTaskKeys(s => { const n = new Set(s); n.has(key) ? n.delete(key) : n.add(key); return n; });
  const [expandedKids, setExpandedKids] = useState<Set<number>>(new Set());   // inline-раскрытые исходники под собранной карточкой
  const toggleKid = (id: number) => setExpandedKids(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const [editSpeakerIds, setEditSpeakerIds] = useState<Set<number>>(new Set());   // у каких карточек открыт выбор спикера
  const openSpeaker = (id: number) => setEditSpeakerIds(s => new Set(s).add(id));
  const closeSpeaker = (id: number) => setEditSpeakerIds(s => { const n = new Set(s); n.delete(id); return n; });

  // drag-сортировка активных карточек (тянуть за ручку ⠿)
  const [dragId, setDragId] = useState<number | null>(null);               // что тащим
  const [dragOverId, setDragOverId] = useState<number | null>(null);       // над кем висим
  const [dragOffsetY, setDragOffsetY] = useState(0);
  const [dragStartIndex, setDragStartIndex] = useState<number | null>(null);
  const [dragTargetIndex, setDragTargetIndex] = useState<number | null>(null);
  const dragTargetIndexRef = useRef<number | null>(null);
  const [dragItemHeight, setDragItemHeight] = useState(0);
  const drawerScrollRef = useRef<HTMLDivElement | null>(null);
  const autoScrollFrameRef = useRef<number | null>(null);
  const pointerDragRef = useRef<{
    id: number;
    startY: number;
    currentY: number;
    grabOffsetY: number;
    ids: number[];
    mids: Array<{ id: number; mid: number }>;
    startScrollTop: number;
    scrollTop: number;
  } | null>(null);
  const dragCommittedRef = useRef(false);
  const [taskDragKey, setTaskDragKey] = useState<string | null>(null);
  const [taskDragOverKey, setTaskDragOverKey] = useState<string | null>(null);
  const [taskDragOffsetY, setTaskDragOffsetY] = useState(0);
  const [taskDragStartIndex, setTaskDragStartIndex] = useState<number | null>(null);
  const [taskDragTargetIndex, setTaskDragTargetIndex] = useState<number | null>(null);
  const [taskDragItemHeight, setTaskDragItemHeight] = useState(0);
  const taskDragTargetIndexRef = useRef<number | null>(null);
  const taskDragRef = useRef<{
    key: string;
    startY: number;
    currentY: number;
    grabOffsetY: number;
    keys: string[];
    mids: Array<{ key: string; mid: number }>;
    startScrollTop: number;
    scrollTop: number;
  } | null>(null);
  const [infoIds, setInfoIds] = useState<Set<number>>(new Set());   // per-fact "info" footer open
  const toggleInfo = (id: number) => setInfoIds(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const [newText, setNewText] = useState("");
  const [newFlag, setNewFlag] = useState<Flag>("green");
  const [newChannel, setNewChannel] = useState<Channel>("online_research");
  const [newSourceTitle, setNewSourceTitle] = useState("");
  const [newSourceUrl, setNewSourceUrl] = useState("");
  const [newSnippet, setNewSnippet] = useState("");
  const [newRationale, setNewRationale] = useState("");

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["facts", clientId, subsectionId] });
    qc.invalidateQueries({ queryKey: ["matrix", clientId] });
    qc.invalidateQueries({ queryKey: ["scorecard", clientId] });
    qc.invalidateQueries({ queryKey: ["punch", clientId] });
    qc.invalidateQueries({ queryKey: ["work-items", clientId] });
  };

  const reorderMut = useMutation({
    mutationFn: (orderedIds: number[]) => api.reorderFacts(clientId, subsectionId, orderedIds),
    onSuccess: invalidate,
  });

  const commitFactOrder = () => {
    if (dragCommittedRef.current) return;
    dragCommittedRef.current = true;
    const drag = pointerDragRef.current;
    const cur = qc.getQueryData<Fact[]>(["facts", clientId, subsectionId]) ?? [];
    const active = cur.filter(f => f.state !== "rejected").sort(compareFactsForDrawer);
    const rest = cur.filter(f => f.state === "rejected");
    const from = drag ? active.findIndex(f => f.id === drag.id) : -1;
    const to = dragTargetIndexRef.current ?? from;
    if (from >= 0 && to >= 0 && from !== to) {
      const next = [...active];
      const [moved] = next.splice(from, 1);
      next.splice(to, 0, moved);
      qc.setQueryData<Fact[]>(["facts", clientId, subsectionId], [
        ...next.map((f, index) => ({ ...f, sort_order: index })),
        ...rest,
      ]);
    }
    const orderedIds = (qc.getQueryData<Fact[]>(["facts", clientId, subsectionId]) ?? cur)
      .filter(f => f.state !== "rejected")
      .sort(compareFactsForDrawer)
      .map(f => f.id);
    if (orderedIds.length) reorderMut.mutate(orderedIds);
  };

  const endPointerDrag = () => {
    commitFactOrder();
    if (autoScrollFrameRef.current != null) {
      cancelAnimationFrame(autoScrollFrameRef.current);
      autoScrollFrameRef.current = null;
    }
    pointerDragRef.current = null;
    setDragId(null);
    setDragOverId(null);
    setDragOffsetY(0);
    setDragStartIndex(null);
    setDragTargetIndex(null);
    dragTargetIndexRef.current = null;
    setDragItemHeight(0);
    document.body.style.userSelect = "";
    document.body.style.cursor = "";
  };

  const startPointerDrag = (factId: number, e: ReactPointerEvent<HTMLElement>) => {
    const card = document.getElementById(`fact-${factId}`);
    if (!card) return;
    const rect = card.getBoundingClientRect();
    const cur = qc.getQueryData<Fact[]>(["facts", clientId, subsectionId]) ?? [];
    const ids = cur.filter(f => f.state !== "rejected").sort(compareFactsForDrawer).map(f => f.id);
    const startIndex = ids.indexOf(factId);
    if (startIndex < 0) return;
    const mids = ids.map(id => {
      const el = document.getElementById(`fact-${id}`);
      const r = el?.getBoundingClientRect();
      return r ? { id, mid: r.top + r.height / 2 } : null;
    }).filter((x): x is { id: number; mid: number } => !!x);
    pointerDragRef.current = {
      id: factId,
      startY: e.clientY,
      currentY: e.clientY,
      grabOffsetY: e.clientY - rect.top,
      ids,
      mids,
      startScrollTop: drawerScrollRef.current?.scrollTop ?? 0,
      scrollTop: drawerScrollRef.current?.scrollTop ?? 0,
    };
    dragCommittedRef.current = false;
    setFactSortMode("custom");
    setFactSortDir("desc");
    setDragId(factId);
    setDragOverId(null);
    setDragOffsetY(0);
    setDragStartIndex(startIndex);
    setDragTargetIndex(startIndex);
    dragTargetIndexRef.current = startIndex;
    setDragItemHeight(rect.height + 12);
    document.body.style.userSelect = "none";
    document.body.style.cursor = "grabbing";
    e.currentTarget.setPointerCapture(e.pointerId);
  };

  const tickAutoScroll = () => {
    const drag = pointerDragRef.current;
    const scroller = drawerScrollRef.current;
    if (!drag || !scroller) {
      autoScrollFrameRef.current = null;
      return;
    }
    const rect = scroller.getBoundingClientRect();
    const edge = 92;
    const maxSpeed = 18;
    let speed = 0;
    if (drag.currentY < rect.top + edge) {
      speed = -maxSpeed * (1 - Math.max(0, drag.currentY - rect.top) / edge);
    } else if (drag.currentY > rect.bottom - edge) {
      speed = maxSpeed * (1 - Math.max(0, rect.bottom - drag.currentY) / edge);
    }
    if (speed !== 0) {
      scroller.scrollTop += speed;
      drag.scrollTop = scroller.scrollTop;
      setDragOffsetY(drag.currentY - drag.startY + (drag.scrollTop - drag.startScrollTop));
    }
    autoScrollFrameRef.current = requestAnimationFrame(tickAutoScroll);
  };

  useEffect(() => {
    if (dragId == null) return;

    const onMove = (e: PointerEvent) => {
      const drag = pointerDragRef.current;
      if (!drag) return;
      drag.currentY = e.clientY;
      drag.scrollTop = drawerScrollRef.current?.scrollTop ?? drag.scrollTop;
      setDragOffsetY(e.clientY - drag.startY + (drag.scrollTop - drag.startScrollTop));
      if (autoScrollFrameRef.current == null) {
        autoScrollFrameRef.current = requestAnimationFrame(tickAutoScroll);
      }

      const draggedMid = e.clientY - drag.grabOffsetY + dragItemHeight / 2 + (drag.scrollTop - drag.startScrollTop);
      const rects = drag.mids
        .filter(r => r.id !== drag.id)
        .sort((a, b) => a.mid - b.mid);
      let nextIndex = 0;
      for (const r of rects) {
        if (draggedMid > r.mid) nextIndex += 1;
      }
      nextIndex = Math.max(0, Math.min(drag.ids.length - 1, nextIndex));
      dragTargetIndexRef.current = nextIndex;
      setDragTargetIndex(nextIndex);
      const overId = drag.ids[nextIndex];
      setDragOverId(overId === drag.id ? null : overId);
    };

    const onUp = () => endPointerDrag();
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp, { once: true });
    window.addEventListener("pointercancel", onUp, { once: true });
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
    };
  }, [dragId, dragItemHeight]);

  const endTaskDrag = () => {
    const drag = taskDragRef.current;
    if (drag) {
      const from = taskOrderKeys.indexOf(drag.key);
      const to = taskDragTargetIndexRef.current ?? from;
      if (from >= 0 && to >= 0 && from !== to) {
        const next = [...taskOrderKeys];
        const [moved] = next.splice(from, 1);
        next.splice(to, 0, moved);
        setTaskOrderKeys(next);
        localStorage.setItem(`cell-drawer-task-order-${clientId}-${subsectionId}`, JSON.stringify(next));
      }
    }
    if (autoScrollFrameRef.current != null) {
      cancelAnimationFrame(autoScrollFrameRef.current);
      autoScrollFrameRef.current = null;
    }
    taskDragRef.current = null;
    setTaskDragKey(null);
    setTaskDragOverKey(null);
    setTaskDragOffsetY(0);
    setTaskDragStartIndex(null);
    setTaskDragTargetIndex(null);
    taskDragTargetIndexRef.current = null;
    setTaskDragItemHeight(0);
    document.body.style.userSelect = "";
    document.body.style.cursor = "";
  };

  const startTaskDrag = (key: string, e: ReactPointerEvent<HTMLElement>) => {
    const card = document.getElementById(`task-${key}`);
    if (!card) return;
    const rect = card.getBoundingClientRect();
    const keys = taskOrderKeys.length ? taskOrderKeys : [];
    const startIndex = keys.indexOf(key);
    if (startIndex < 0) return;
    const mids = keys.map(k => {
      const el = document.getElementById(`task-${k}`);
      const r = el?.getBoundingClientRect();
      return r ? { key: k, mid: r.top + r.height / 2 } : null;
    }).filter((x): x is { key: string; mid: number } => !!x);
    taskDragRef.current = {
      key,
      startY: e.clientY,
      currentY: e.clientY,
      grabOffsetY: e.clientY - rect.top,
      keys,
      mids,
      startScrollTop: drawerScrollRef.current?.scrollTop ?? 0,
      scrollTop: drawerScrollRef.current?.scrollTop ?? 0,
    };
    setTaskSortMode("custom");
    setTaskSortDir("desc");
    setTaskDragKey(key);
    setTaskDragOverKey(null);
    setTaskDragOffsetY(0);
    setTaskDragStartIndex(startIndex);
    setTaskDragTargetIndex(startIndex);
    taskDragTargetIndexRef.current = startIndex;
    setTaskDragItemHeight(rect.height + 8);
    document.body.style.userSelect = "none";
    document.body.style.cursor = "grabbing";
    e.currentTarget.setPointerCapture(e.pointerId);
  };

  useEffect(() => {
    if (taskDragKey == null) return;

    const onMove = (e: PointerEvent) => {
      const drag = taskDragRef.current;
      if (!drag) return;
      drag.currentY = e.clientY;
      const scroller = drawerScrollRef.current;
      if (scroller) {
        const rect = scroller.getBoundingClientRect();
        const edge = 92;
        const maxSpeed = 18;
        let speed = 0;
        if (e.clientY < rect.top + edge) {
          speed = -maxSpeed * (1 - Math.max(0, e.clientY - rect.top) / edge);
        } else if (e.clientY > rect.bottom - edge) {
          speed = maxSpeed * (1 - Math.max(0, rect.bottom - e.clientY) / edge);
        }
        if (speed !== 0) scroller.scrollTop += speed;
      }
      drag.scrollTop = drawerScrollRef.current?.scrollTop ?? drag.scrollTop;
      setTaskDragOffsetY(e.clientY - drag.startY + (drag.scrollTop - drag.startScrollTop));

      const draggedMid = e.clientY - drag.grabOffsetY + taskDragItemHeight / 2 + (drag.scrollTop - drag.startScrollTop);
      const rects = drag.mids.filter(r => r.key !== drag.key).sort((a, b) => a.mid - b.mid);
      let nextIndex = 0;
      for (const r of rects) {
        if (draggedMid > r.mid) nextIndex += 1;
      }
      nextIndex = Math.max(0, Math.min(drag.keys.length - 1, nextIndex));
      taskDragTargetIndexRef.current = nextIndex;
      setTaskDragTargetIndex(nextIndex);
      const overKey = drag.keys[nextIndex];
      setTaskDragOverKey(overKey === drag.key ? null : overKey);
    };

    const onUp = () => endTaskDrag();
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp, { once: true });
    window.addEventListener("pointercancel", onUp, { once: true });
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
    };
  }, [taskDragKey, taskDragItemHeight, taskOrderKeys]);

  const isOnlineChannel = (ch: Channel) =>
    ch === "online_research" || ch === "online_interview" || ch === "archival";
  const snippetRequired = isOnlineChannel(newChannel);
  const snippetValid = !snippetRequired || newSnippet.trim().length >= 20;

  const addFact = useMutation({
    mutationFn: () => api.addFact(clientId, subsectionId, {
      text: newText, flag: newFlag, channel: newChannel,
      source_title: newSourceTitle, source_url: newSourceUrl,
      evidence_snippet: newSnippet, confidence: 1.0,
      rationale: newRationale.trim() || undefined,
    }),
    onSuccess: () => {
      setShowAdd(false); setNewText(""); setNewSourceTitle("");
      setNewSourceUrl(""); setNewSnippet(""); setNewRationale("");
      invalidate();
    },
  });

  const patchFact = useMutation({
    mutationFn: ({ id, text, flag, rationale }: { id: number; text: string; flag: Flag; rationale: string }) =>
      api.patchFact(id, { text, flag, rationale: rationale.trim() || undefined }),
    onSuccess: () => { setEditingId(null); invalidate(); },
  });

  const deleteFact = useMutation({
    mutationFn: (id: number) => api.deleteFact(id),
    onSuccess: invalidate,
  });

  // перенос факта в другой раздел (подсекцию) — факт уходит из этой ячейки
  const moveFact = useMutation({
    mutationFn: ({ id, toSid }: { id: number; toSid: string }) => api.moveFact(id, toSid),
    onSuccess: () => {
      qc.invalidateQueries({ predicate: (q) => q.queryKey[0] === "facts" });
      qc.invalidateQueries({ queryKey: ["matrix", clientId] });
      qc.invalidateQueries({ queryKey: ["scorecard", clientId] });
      qc.invalidateQueries({ queryKey: ["punch", clientId] });
    },
  });

  const restoreFact = useMutation({
    mutationFn: (id: number) => api.restoreFact(id),
    onSuccess: invalidate,
  });

  // одобрить черновик контрибьютора → active (владелец/админ)
  const approveFact = useMutation({
    mutationFn: (id: number) => api.promoteFact(id),
    onSuccess: invalidate,
  });

  // founder attribution: who (of the company's founders) this fact is from
  const entities = useQuery<Entity[]>({ queryKey: ["entities", clientId], queryFn: () => api.entities(clientId) });
  const founders = (entities.data ?? []).filter(e => e.kind === "founder");
  const setSpeaker = useMutation({
    mutationFn: ({ id, entityId }: { id: number; entityId: number | null }) => api.setFactSpeaker(id, entityId),
    onSuccess: invalidate,
  });
  const setTitle = useMutation({
    mutationFn: ({ id, title }: { id: number; title: string }) => api.setFactTitle(id, title),
    onSuccess: invalidate,
  });
  const setMustHave = useMutation({
    mutationFn: ({ id, source }: { id: number; source: "" | "client" | "expert" }) => api.setMustHave(id, source),
    onSuccess: invalidate,
  });
  const setAbout = useMutation({
    mutationFn: ({ id, value }: { id: number; value: string }) => api.setFactAbout(id, value),
    onSuccess: invalidate,
  });
  // упомянутые (внешние) компании клиента — тег «про компанию» выбирается ИЗ ЭТОГО списка
  // (не свободный текст → без бардака), их логотип помечает карточку факта.
  const mentioned = useQuery({ queryKey: ["mentioned-companies", clientId], queryFn: () => api.mentionedCompanies(clientId) });
  // тег «про компанию» двусторонний: ДРУГАЯ компания → факт про прошлое фаундера (L1/L2);
  // ТЕКУЩАЯ (is_current, авто-запись) → осознанный пин «держать в L3-8, не в L1/L2».
  const mentionedList = mentioned.data ?? [];   // включая текущую компанию (первой)
  const currentCompany = mentionedList.find(m => m.is_current);
  const currentCompanyName = (currentCompany?.name || client.data?.name || "").trim().toLowerCase();
  const isCurrentTag = (name?: string) => !!name && name.trim().toLowerCase() === currentCompanyName;
  const companyByName = (name?: string) =>
    mentionedList.find(m => m.name.trim().toLowerCase() === (name || "").trim().toLowerCase());
  const [addingCompany, setAddingCompany] = useState("");   // имя новой компании в форме добавления
  const addMentioned = useMutation({
    mutationFn: (name: string) => api.addMentionedCompany(clientId, { name }),
    onSuccess: (m) => { qc.invalidateQueries({ queryKey: ["mentioned-companies", clientId] }); setDraftAbout(m.name); setAddingCompany(""); },
  });

  // Фокус из поиска: доскроллить к карточке и подсветить; исходник — раскрыть.
  const focusedRef = useRef<number | undefined>(undefined);
  useEffect(() => {
    if (!focusFactId) { focusedRef.current = undefined; return; }
    if (!facts.data || focusedRef.current === focusFactId) return;
    const target = facts.data.find(f => f.id === focusFactId);
    if (!target) return;
    focusedRef.current = focusFactId;
    if (target.state === "rejected") setShowHidden(true);
    setInfoIds(s => new Set(s).add(focusFactId));
    setTimeout(() => {
      const el = document.getElementById(`fact-${focusFactId}`);
      el?.scrollIntoView({ block: "center", behavior: "smooth" });
      el?.classList.add("ring-2", "ring-blue-400");
      setTimeout(() => el?.classList.remove("ring-2", "ring-blue-400"), 1600);
    }, 80);
  }, [focusFactId, facts.data]);

  const channelHint = subsection
    ? `Основные каналы для слоя ${subsection.layer.id}: ${subsection.layer.primary_channels.join(", ")}`
    : "";
  const focusedTaskItems = (workItems.data ?? []).filter(item =>
    item.subsection_id === subsectionId && ACTIVE_WORK_STATUSES.has(item.status)
  );
  const focusedEmptyCell = punch.data?.empty_cells.find(c => c.subsection_id === subsectionId);
  const focusedThinCell = punch.data?.thinly_covered.find(c => c.subsection_id === subsectionId);
  const focusedKnownGap = punch.data?.cells_with_known_gaps.find(c => c.subsection_id === subsectionId);
  const firstMaterialItems = focusedEmptyCell
    ? focusedTaskItems.filter(item => isEmptyCellRedundantWorkTitle(item.title))
    : [];
  const visibleWorkItems = focusedEmptyCell
    ? focusedTaskItems.filter(item => !isEmptyCellRedundantWorkTitle(item.title))
    : focusedTaskItems;
  const hasDeepenWorkItem = visibleWorkItems.some(item =>
    item.type === "deepen" || item.title.startsWith("Deepen:")
  );
  const baseTaskCards: DrawerTaskCard[] = [
    ...(focusedKnownGap ? [{
      key: "gap",
      title: "Открытые вопросы",
      body: focusedKnownGap.grey_facts.length
        ? `${focusedKnownGap.grey_facts.length} ${gapPlural(focusedKnownGap.grey_facts.length)} требуют закрытия.`
        : "Есть отмеченные пробелы, которые нужно закрыть.",
      tone: "grey" as const,
      greyFacts: focusedKnownGap.grey_facts,
      createdAt: "",
    }] : []),
    ...visibleWorkItems.map(item => {
      const fallbackFactId = Number(item.title.match(/\((\d+)\)\s*$/)?.[1] ?? NaN);
      return {
        key: `work-${item.id}`,
        title: displayWorkTitle(item.title),
        body: displayWorkBody(item.title, item.rationale || item.notes || workStatusLabel(item.status)),
        meta: workStatusLabel(item.status),
        createdAt: item.created_at,
        relatedFactId: item.related_fact_id ?? (Number.isFinite(fallbackFactId) ? fallbackFactId : undefined),
        tone: "green" as const,
      };
    }),
    ...(focusedThinCell && !focusedEmptyCell && !hasDeepenWorkItem
      ? [{ key: "thin", title: "Добрать подтверждения", body: "Фактов недостаточно: стоит добрать источники или подтверждения.", tone: "amber" as const, createdAt: "" }]
      : []),
    ...(focusedEmptyCell ? [{
      key: "empty",
      title: "Нужен первый материал",
      body: "Фактов пока нет. Начните с источника или подготовьте вопрос для интервью.",
      tone: "amber" as const,
      firstMaterialActions: firstMaterialItems.map(item => item.title),
      createdAt: "",
    }] : []),
  ];
  useEffect(() => {
    const storageKey = `cell-drawer-task-order-${clientId}-${subsectionId}`;
    let stored: string[] = [];
    try {
      stored = JSON.parse(localStorage.getItem(storageKey) || "[]");
    } catch {
      stored = [];
    }
    const keys = baseTaskCards.map(t => t.key);
    const next = [...stored.filter(k => keys.includes(k)), ...keys.filter(k => !stored.includes(k))];
    setTaskOrderKeys(next);
  }, [clientId, subsectionId, baseTaskCards.map(t => t.key).join("|")]);
  const taskCards = (() => {
    const sorted = [...baseTaskCards].sort((a, b) => {
      if (taskSortMode === "date") {
        const at = Date.parse(a.createdAt || "") || 0;
        const bt = Date.parse(b.createdAt || "") || 0;
        if (at !== bt) return bt - at;
      }
      const ai = taskOrderKeys.indexOf(a.key);
      const bi = taskOrderKeys.indexOf(b.key);
      const ao = ai >= 0 ? ai : 9999;
      const bo = bi >= 0 ? bi : 9999;
      if (ao !== bo) return ao - bo;
      return a.key.localeCompare(b.key);
    });
    return taskSortDir === "asc" ? sorted.reverse() : sorted;
  })();
  const relatedFactIds = Array.from(new Set(taskCards
    .map(task => "relatedFactId" in task ? task.relatedFactId : undefined)
    .filter((id): id is number => typeof id === "number" && Number.isFinite(id))
  ));
  const relatedFactQueries = useQueries({
    queries: relatedFactIds.map(id => ({
      queryKey: ["fact", clientId, id],
      queryFn: () => api.getFact(clientId, id),
      enabled: !!auditFocus,
      retry: false,
    })),
  });
  const relatedFactsById = new Map<number, Fact>();
  for (const fact of facts.data ?? []) relatedFactsById.set(fact.id, fact);
  relatedFactQueries.forEach(q => {
    if (q.data) relatedFactsById.set(q.data.id, q.data);
  });
  return (
    <aside className="fixed top-0 right-0 bottom-0 w-[28rem] bg-white border-l border-ink-line shadow-xl
                      flex flex-col z-30">
      <div className="px-4 py-3 border-b border-ink-line flex items-center justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-base font-semibold leading-tight">
            {subsectionTitle}
          </h3>
        </div>
        <button
          onClick={onClose}
          className="shrink-0 text-ink-mute hover:text-ink rounded p-1 -mr-1"
          aria-label="Закрыть"
        >
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
            <path d="M5 5l10 10M15 5L5 15" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
          </svg>
        </button>
      </div>

      <div ref={drawerScrollRef} className="flex-1 overflow-y-auto p-4 space-y-3">
        {facts.isLoading && <div className="text-sm text-ink-mute">Загружаю факты…</div>}

        {facts.data && facts.data.length === 0 && !showAdd && !auditFocus && (
          <div className="text-sm text-ink-mute italic py-3">
            В этой ячейке пока нет фактов. Добавьте факт вручную или загрузите данные через подходящий канал.
          </div>
        )}

        {(() => {
          const all = facts.data ?? [];
          const sortFacts = (items: Fact[]) => {
            const sorted = [...items].sort(factSortMode === "date" ? compareFactsByDate : compareFactsForDrawer);
            return factSortDir === "asc" ? sorted.reverse() : sorted;
          };
          const activeAll = sortFacts(all.filter(f => f.state !== "rejected"));
          const active = sortFacts(auditFocus ? activeAll.filter(isReviewFact) : activeAll);
          const hidden = all.filter(f => f.state === "rejected").sort(compareFactsForDrawer);
          const jumpTo = (id: number) => {
            setShowHidden(true);
            setTimeout(() => {
              const el = document.getElementById(`fact-${id}`);
              el?.scrollIntoView({ block: "nearest", behavior: "smooth" });
              el?.classList.add("ring-2", "ring-blue-400");
              setTimeout(() => el?.classList.remove("ring-2", "ring-blue-400"), 1200);
            }, 60);
          };
          return (<>
            {auditFocus && active.length === 0 && taskCards.length === 0 && (
              <div className="rounded-lg border border-ink-line bg-white p-3 text-sm text-ink-mute">
                В этой ячейке нет открытых вопросов проверки.
              </div>
            )}
            {active.length > 0 && (
              <div className="flex items-center justify-between gap-3">
                <div className="text-[11px] font-semibold uppercase tracking-wide text-ink-mute">Факты</div>
                {active.length > 1 && (
                  <div className="flex items-center gap-1 text-[11px] text-ink-mute">
                    <span>сортировка:</span>
                    <button
                      onClick={() => setFactSortMode(m => m === "custom" ? "date" : "custom")}
                      className="font-medium text-ink transition-colors hover:text-ink/75"
                      title="Переключить сортировку: своя / дата"
                    >
                      {factSortMode === "custom" ? "своя" : "дата"}
                    </button>
                    <button
                      onClick={() => setFactSortDir(d => d === "desc" ? "asc" : "desc")}
                      className="ml-1 text-ink-mute transition-colors hover:text-ink"
                      title={factSortDir === "desc" ? "Сейчас сверху вниз: новые или первые в своём порядке" : "Сейчас снизу вверх: обратный порядок"}
                    >
                      {factSortDir === "desc" ? "↓" : "↑"}
                    </button>
                  </div>
                )}
              </div>
            )}

            {active.map((f, index) => {
              const kids = hidden.filter(h => h.merged_into === f.id);
              const shiftY = (() => {
                if (dragId == null || dragStartIndex == null || dragTargetIndex == null || dragItemHeight === 0 || f.id === dragId) return 0;
                if (dragTargetIndex > dragStartIndex && index > dragStartIndex && index <= dragTargetIndex) return -dragItemHeight;
                if (dragTargetIndex < dragStartIndex && index >= dragTargetIndex && index < dragStartIndex) return dragItemHeight;
                return 0;
              })();
              const mustHaveBy = f.must_have_by || (f.must_have ? "client" : "");
              const nextMustHave = mustHaveBy === "" ? "client" : mustHaveBy === "client" ? "expert" : "";
              const mustHaveColor = mustHaveBy === "client"
                ? "text-[#5f789c] hover:text-[#405f88]"
                : mustHaveBy === "expert"
                  ? "text-[#756082] hover:text-[#5f486d]"
                  : "text-ink-mute/45 hover:text-[#5f789c]";
              const mustHaveTitle = mustHaveBy === "client" ? "обязательное от клиента → клик: важное от эксперта"
                : mustHaveBy === "expert" ? "важное от эксперта (приоритет) → клик: снять"
                : "клик: отметить как обязательное от клиента";
              const mustHaveLabel = mustHaveBy === "client" ? "от клиента" : mustHaveBy === "expert" ? "от эксперта" : "★";
              return (
                <div key={f.id} id={`fact-${f.id}`} data-fact-id={f.id}
                  role={editingId === f.id ? undefined : "button"}
                  tabIndex={editingId === f.id ? undefined : 0}
                  style={
                    dragId === f.id
                      ? { transform: `translate3d(0, ${dragOffsetY}px, 0)` }
                      : shiftY
                        ? { transform: `translate3d(0, ${shiftY}px, 0)` }
                        : undefined
                  }
                  onClick={(e) => {
                    if (editingId === f.id) return;
                    const target = e.target as HTMLElement;
                    if (target.closest("button, select, input, textarea, a, summary, [data-no-card-toggle]")) return;
                    toggleInfo(f.id);
                  }}
                  onKeyDown={(e) => {
                    if (editingId === f.id) return;
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      toggleInfo(f.id);
                    }
                  }}
                  className={`group/fact relative rounded-xl border border-ink-line bg-white p-3.5 shadow-[0_4px_18px_rgba(35,39,28,0.04)]
                    transition-[background-color,box-shadow,opacity,transform] duration-300 ease-out hover:-translate-y-px hover:bg-[#fbfbf7]
                    ${editingId === f.id ? "" : "cursor-pointer"} ${dragId === f.id ? "z-20 bg-[#fbfbf7] opacity-80 shadow-[0_16px_34px_rgba(35,39,28,0.12)]" : ""} ${dragOverId === f.id ? "bg-[#fbfbf7]" : ""}`}>
                  {editingId === f.id ? (
                    <div className="space-y-2">
                      <input value={draftTitle} onChange={e => setDraftTitle(e.target.value)}
                        placeholder="Заголовок (2-3 слова)"
                        className="w-full text-sm font-semibold border border-ink-line rounded px-2 py-1.5" />
                      <textarea value={draftText} onChange={e => setDraftText(e.target.value)}
                        className="w-full text-sm border border-ink-line rounded px-2 py-1.5 min-h-[5rem]" />
                      <textarea value={draftRationale} onChange={e => setDraftRationale(e.target.value)}
                        placeholder={draftFlag === "red" ? "Проблема: что именно требует внимания (обязательно для риска)" : "Пояснение (опц.)"}
                        rows={3}
                        className={`w-full text-xs border rounded px-2 py-1.5 min-h-[3rem] resize-none ${draftFlag === "red" && !draftRationale.trim() ? "border-red-400" : "border-ink-line"}`} />
                      {/* только слои 1-2: факт может быть про ДРУГУЮ компанию (характеризует фаундера).
                          Выбор ИЗ списка упомянутых компаний (не свободный текст) + добавить новую. */}
                      {allowAboutCompany && (
                        <div className="flex items-center gap-1.5 flex-wrap">
                          <span className="text-[11px] text-ink-mute" title="про какую компанию факт: другую (→ история фаундера, L1/L2) или текущую (пин: держать в L3-8)">🏢 про компанию:</span>
                          <select value={draftAbout} onChange={e => setDraftAbout(e.target.value)}
                            className="text-xs border border-ink-line rounded px-1.5 py-1 bg-white max-w-[12rem]">
                            <option value="">— не указано (решит LLM) —</option>
                            {mentionedList.map(m => <option key={m.id} value={m.name}>{m.is_current ? `📌 ${m.name} (текущая)` : m.name}</option>)}
                            {draftAbout && !companyByName(draftAbout) && <option value={draftAbout}>{draftAbout}</option>}
                          </select>
                          <input value={addingCompany} onChange={e => setAddingCompany(e.target.value)}
                            onKeyDown={e => { if (e.key === "Enter" && addingCompany.trim()) { e.preventDefault(); addMentioned.mutate(addingCompany.trim()); } }}
                            placeholder="+ новая компания"
                            className="text-xs border border-dashed border-ink-line rounded px-1.5 py-1 w-32" />
                          {addingCompany.trim() && (
                            <button onClick={() => addMentioned.mutate(addingCompany.trim())} disabled={addMentioned.isPending}
                              className="text-[11px] text-ink hover:underline">добавить</button>
                          )}
                        </div>
                      )}
                      <div className="flex items-center gap-2">
                        <FlagPicker value={draftFlag} onChange={setDraftFlag} />
                        <button onClick={() => {
                            patchFact.mutate({ id: f.id, text: draftText, flag: draftFlag, rationale: draftRationale });
                            if ((draftTitle ?? "") !== (f.title ?? "")) setTitle.mutate({ id: f.id, title: draftTitle });
                            if (allowAboutCompany && (draftAbout.trim() !== (f.about_company ?? "").trim())) setAbout.mutate({ id: f.id, value: draftAbout });
                          }}
                          disabled={draftFlag === "red" && !draftRationale.trim()}
                          className="text-xs px-3 py-1 bg-ink text-white rounded hover:bg-black disabled:bg-slate-300">Сохранить</button>
                        <button onClick={() => setEditingId(null)} className="text-xs px-3 py-1 hover:bg-slate-100 rounded text-ink-mute">Отмена</button>
                      </div>
                      {/* перенос в другой раздел (подсекцию) — факт уходит из этой ячейки */}
                      <div className="flex items-center gap-2 pt-1 border-t border-ink-line/60">
                        <span className="text-xs text-ink-mute" title="перенести факт в другой раздел матрицы">Раздел:</span>
                        <select value={subsectionId} disabled={moveFact.isPending}
                          onChange={e => {
                            const to = e.target.value;
                            if (to && to !== subsectionId) { moveFact.mutate({ id: f.id, toSid: to }); setEditingId(null); }
                          }}
                          className="text-xs border border-ink-line rounded px-1.5 py-1 bg-white max-w-[18rem]">
                          {(layers ?? []).map(L => (
                            <optgroup key={L.id} label={`L${L.id}. ${layerNameRu(L.id, L.name)}`}>
                              {L.subsections.map(s => <option key={s.id} value={s.id}>{s.id} {subsectionNameRu(s.id, s.name)}</option>)}
                            </optgroup>
                          ))}
                        </select>
                        {moveFact.isPending && <span className="text-[11px] text-ink-mute">переношу…</span>}
                      </div>
                    </div>
                  ) : (
                    <>
                      {auditFocus && (
                        <div className="mb-2 flex items-start gap-1.5 text-[11px] leading-snug text-amber-900">
                          <span className="mt-[0.45em] h-1.5 w-1.5 shrink-0 rounded-full bg-amber-400" />
                          <span><span className="font-medium">Причина:</span> {reviewReason(f)}</span>
                        </div>
                      )}

                      {/* title + fact text */}
                      <div className="mb-1 flex items-start gap-2">
                        {f.title && <div className="min-w-0 flex-1 text-[14px] font-semibold leading-tight text-ink">{f.title}</div>}
                        <span
                          data-no-card-toggle
                          onPointerDown={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            startPointerDrag(f.id, e);
                          }}
                          title="перетащить: изменить порядок"
                          className="ml-auto shrink-0 cursor-grab select-none text-[13px] leading-none text-ink-mute/0 transition-colors hover:text-ink-mute/70 group-hover/fact:text-ink-mute/30 active:cursor-grabbing">⠿</span>
                      </div>
                      <div className="text-[13px] leading-snug whitespace-pre-wrap text-ink">{f.text}</div>

                      <div className="mt-2.5 flex items-center gap-2 border-t border-ink-line/50 pt-2 text-[11px] text-ink-mute">
                        <div className="flex min-w-0 flex-1 items-center gap-1.5 overflow-hidden">
                          {allowAboutCompany && f.about_company && (
                            isCurrentTag(f.about_company) ? (
                              <button onClick={() => { setEditingId(f.id); setDraftText(f.text); setDraftFlag(f.flag); setDraftRationale(f.rationale ?? ""); setDraftTitle(f.title ?? ""); setDraftAbout(f.about_company ?? ""); }}
                                title="закреплено за текущей компанией — не уйдёт в L1/L2 (клик — изменить)"
                                className="flex min-w-0 items-center gap-1 hover:text-ink">
                                <span className="shrink-0">📌</span><span className="truncate">{f.about_company}</span>
                              </button>
                            ) : (
                              <button onClick={() => { setEditingId(f.id); setDraftText(f.text); setDraftFlag(f.flag); setDraftRationale(f.rationale ?? ""); setDraftTitle(f.title ?? ""); setDraftAbout(f.about_company ?? ""); }}
                                title="про какую компанию (клик — изменить в форме)"
                                className="flex min-w-0 items-center gap-1 hover:text-ink">
                                <CompanyFavicon name={f.about_company} logo={companyByName(f.about_company)?.logo} />
                                <span className="truncate">{f.about_company}</span>
                              </button>
                            )
                          )}
                          {founders.length > 0 && (
                            <>
                              {(allowAboutCompany && f.about_company) && <span className="text-ink-mute/45">·</span>}
                              {editSpeakerIds.has(f.id) ? (
                                <div className="flex min-w-0 items-center gap-1.5">
                                  <select autoFocus value={f.speaker_entity_id ?? ""}
                                    onChange={e => { setSpeaker.mutate({ id: f.id, entityId: e.target.value ? Number(e.target.value) : null }); closeSpeaker(f.id); }}
                                    className="max-w-[9rem] rounded border border-ink-line bg-white px-1.5 py-0.5 text-[11px] text-ink">
                                    <option value="">— не указан —</option>
                                    {founders.map(fo => <option key={fo.id} value={fo.id}>{fo.name}</option>)}
                                  </select>
                                  <button onClick={() => closeSpeaker(f.id)} className="text-ink-mute hover:text-ink">✕</button>
                                </div>
                              ) : (
                                <button onClick={() => openSpeaker(f.id)} title={f.speaker_name ? "сменить спикера" : "указать, кто говорит"}
                                  className="min-w-0 truncate hover:text-ink">
                                  {f.speaker_name || "указать спикера"}
                                </button>
                              )}
                            </>
                          )}
                          {f.captured_at && (
                            <>
                              <span className="text-ink-mute/45">·</span>
                              <span className="shrink-0 tabular-nums">{f.captured_at.slice(0, 10)}</span>
                            </>
                          )}
                        </div>
                        <div className="ml-auto flex shrink-0 items-center gap-2 text-ink-mute">
                          {f.state === "review" && (
                            <span className="text-[11px] font-medium text-amber-800"
                              title="черновик — ждёт одобрения владельца данных">на ревью</span>
                          )}
                          <button onClick={() => setMustHave.mutate({ id: f.id, source: nextMustHave as "" | "client" | "expert" })}
                            title={mustHaveTitle}
                            className={`text-[11px] leading-none font-medium transition-opacity ${mustHaveColor} ${mustHaveBy ? "" : "opacity-0 group-hover/fact:opacity-100 focus-visible:opacity-100"}`}>
                            {mustHaveLabel}
                          </button>
                          {f.state === "review" && canApprove && (
                            <button onClick={() => approveFact.mutate(f.id)} disabled={approveFact.isPending}
                              className="rounded-full bg-emerald-600 px-2 py-0.5 text-[11px] text-white hover:bg-emerald-700 disabled:bg-emerald-300"
                              title="одобрить черновик — попадёт в матрицу">одобрить</button>
                          )}
                          <button onClick={() => { setEditingId(f.id); setDraftText(f.text); setDraftFlag(f.flag); setDraftRationale(f.rationale ?? ""); setDraftTitle(f.title ?? ""); setDraftAbout(f.about_company ?? ""); }}
                            aria-label="Редактировать" className="opacity-0 transition-opacity hover:text-ink group-hover/fact:opacity-100 focus-visible:opacity-100">
                            <svg width="15" height="15" viewBox="0 0 20 20" fill="none"><path d="M4 13.5V16h2.5l7.4-7.4-2.5-2.5L4 13.5zM13.1 4.9l2.5 2.5 1-1a1.4 1.4 0 0 0-2-2l-1.5.5z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round"/></svg>
                          </button>
                          <button onClick={() => { if (confirm("Удалить факт безвозвратно?")) deleteFact.mutate(f.id); }}
                            aria-label="Удалить" className="opacity-0 transition-opacity hover:text-flag-red group-hover/fact:opacity-100 focus-visible:opacity-100">
                            <svg width="15" height="15" viewBox="0 0 20 20" fill="none"><path d="M4 6h12M8 6V4.5h4V6M6.5 6l.7 9.5h5.6L13.5 6" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"/></svg>
                          </button>
                        </div>
                      </div>

                      {/* risk / gap — kept in the text body */}
                      {f.flag === "red" && (f.rationale
                        ? <div className="mt-1.5 text-xs border-l-2 pl-2 leading-snug border-flag-red/60 text-flag-red">
                            <span className="font-medium uppercase tracking-wide text-[10px] mr-1">риск:</span>{f.rationale}</div>
                        : <div className="mt-1.5 text-xs text-amber-600 italic">⚠ риск не указан — добавьте через редактирование</div>)}
                      {f.flag === "grey" && f.rationale && (
                        <div className="mt-1.5 text-xs border-l-2 pl-2 leading-snug border-flag-grey/60 text-ink-mute">
                          <span className="font-medium uppercase tracking-wide text-[10px] mr-1">пробел:</span>{f.rationale}</div>)}

                      {/* verification (only when meaningful) */}
                      {f.verification && f.verification !== "unverified" && (
                        <div className="mt-1.5 flex items-center gap-1.5 flex-wrap">
                          <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium uppercase tracking-wide ${f.verification === "verified" ? "bg-emerald-50 text-emerald-700" : f.verification === "refuted" ? "bg-flag-red-bg text-flag-red" : "bg-amber-50 text-amber-700"}`}>
                            {f.verification === "verified" ? "проверено" : f.verification === "refuted" ? "опровергнуто" : "под вопросом"}</span>
                          {f.entity && <span className="text-[11px] font-mono text-ink-mute border border-ink-line rounded px-1.5">≠ {f.entity}</span>}
                        </div>
                      )}

                      {/* лаконичный general view: провенанс (кто/когда) + источник — всё за (i).
                          Сентинелы пайплайна (merge/attribute/…) — не пользователи, не показываем как автора. */}
                      <SmoothCollapse open={infoIds.has(f.id)}>
                        <div className="mt-2 pt-2 border-t border-ink-line/60">
                          {(() => {
                            const SENT = new Set(["merge", "attribute", "dev", "stub", "import", "seed", ""]);
                            const isJoint = kids.length > 0 || f.created_by === "merge" || !!f.merged_by;
                            const author = isJoint
                              ? (f.merged_by && !SENT.has(f.merged_by) ? `собрал ${f.merged_by}` : "собрано")
                              : (f.created_by && !SENT.has(f.created_by) ? `внёс ${f.created_by}` : "");
                            const parts: string[] = [];
                            if (author) parts.push(author);
                            if (f.approved_by) parts.push(`подтвердил ${f.approved_by}`);
                            if (f.captured_at) parts.push(f.captured_at.slice(0, 10));
                            if (!parts.length) return null;
                            return (
                              <div className="mb-1.5 text-[10px] text-ink-mute/70 flex flex-wrap gap-x-2 gap-y-0.5">
                                {parts.map((p, i) => <span key={i}>{i ? "· " : ""}{p}</span>)}
                              </div>
                            );
                          })()}
                          {kids.length > 0 && (() => {
                            // Скрытые «дети» бывают двух природ — НЕ путать:
                            //  • переименование спикера (attribute_fact): тот же факт, где «Фаундер» заменён
                            //    на имя. Из-за иммутабельности старая версия стала новой карточкой. Это НЕ мерж —
                            //    показываем «спикер уточнён», без «собрано из N».
                            //  • реальная склейка дублей → «собрано из N карточек», где N = число СВЁРНУТЫХ
                            //    (сама видимая карточка в счёт не входит).
                            const isRename = (k: Fact) => (k.verification_note || "").startsWith("переименован спикер");
                            const renameKids = kids.filter(isRename);
                            const mergeKids = kids.filter(k => !isRename(k));
                            const nounForm = mergeKids.length === 1 ? "карточки" : "карточек";
                            const chip = (k: Fact) => {
                              const open = expandedKids.has(k.id);
                              return (
                                <button key={k.id} onClick={() => toggleKid(k.id)} title={k.text}
                                  className={`font-mono px-1.5 py-0.5 rounded border text-blue-600 hover:bg-blue-50 ${open ? "border-blue-300 bg-blue-50" : "border-ink-line"}`}>
                                  {open ? "▾" : "▸"} #{k.id}
                                </button>
                              );
                            };
                            const expandedAll = kids.filter(k => expandedKids.has(k.id));
                            return (
                            <div className="mb-1 space-y-1">
                              {mergeKids.length > 0 && (
                                <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-ink-mute">
                                  <span title="эта карточка — канонический вариант; в счёт входят только свёрнутые в неё">собрано из {mergeKids.length} {nounForm}:</span>
                                  {mergeKids.map(chip)}
                                </div>
                              )}
                              {renameKids.length > 0 && (
                                <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-ink-mute">
                                  <span title="тот же факт — ранее спикер был без имени">спикер уточнён · ранее без имени:</span>
                                  {renameKids.map(chip)}
                                </div>
                              )}
                              {/* исходники раскрываются тут же, без прыжка вниз */}
                              <SmoothCollapse open={expandedAll.length > 0}>
                                <div className="mt-1.5 space-y-1.5">
                                  {expandedAll.map(k => (
                                    <div key={k.id} className="rounded border border-ink-line bg-slate-50/70 p-2">
                                      <div className="flex items-center gap-1.5 text-[10px] text-ink-mute mb-1">
                                        <FlagDot flag={k.flag} size={9} />
                                        <span>{isRename(k) ? `ранее (без имени) #${k.id}` : `исходная #${k.id}`}</span>
                                        <button onClick={() => restoreFact.mutate(k.id)}
                                          className="ml-auto text-ink-mute hover:text-ink" title="вернуть в матрицу как отдельную карточку">вернуть</button>
                                      </div>
                                      {k.title && <div className="text-xs font-semibold text-ink-mute leading-tight">{k.title}</div>}
                                      <div className="text-xs leading-snug whitespace-pre-wrap text-ink-mute">{k.text}</div>
                                      {k.evidence_snippet && (
                                        <blockquote className="mt-1 text-[11px] text-ink-mute border-l-2 border-ink-line pl-2 italic leading-snug">{k.evidence_snippet}</blockquote>
                                      )}
                                      <SourceLine client_id={clientId} channel={k.source_channel} source_url={k.source_url}
                                        source_title={k.source_title} source_archive_url={k.source_archive_url}
                                        ingest_audit_id={k.ingest_audit_id} ingest_kind={k.ingest_kind} audio_sha={k.audio_sha}
                                        timestamp_sec={k.snippet_start_sec ?? undefined} captured_at={k.captured_at}
                                        onOpenAudio={(sha, sec) => openAudio(k.id, sha, sec)} />
                                    </div>
                                  ))}
                                </div>
                              </SmoothCollapse>
                            </div>
                            );
                          })()}
                          {/* собранная карточка несёт ТОЛЬКО ссылки на исходные — цитата/источник живут в исходных */}
                          {kids.length === 0 && (<>
                            {f.evidence_snippet && (
                              <blockquote className="text-[11px] text-ink-mute border-l-2 border-ink-line pl-2 italic leading-snug mb-1">{f.evidence_snippet}</blockquote>
                            )}
                            <SourceLine client_id={clientId} channel={f.source_channel} source_url={f.source_url}
                              source_title={f.source_title} source_archive_url={f.source_archive_url}
                              ingest_audit_id={f.ingest_audit_id} ingest_kind={f.ingest_kind} audio_sha={f.audio_sha}
                              timestamp_sec={f.snippet_start_sec ?? undefined} captured_at={f.captured_at}
                              onOpenAudio={(sha, sec) => openAudio(f.id, sha, sec)} />
                            {audioPanel?.factId === f.id && (
                              <div className="mt-2 border-t border-ink-line/60 pt-2">
                                <AudioSourcePanel ref={audioRef} clientId={clientId} sha={audioPanel.sha} />
                              </div>
                            )}
                          </>)}
                        </div>
                      </SmoothCollapse>
                    </>
                  )}
                </div>
              );
            })}

            {auditFocus && taskCards.length > 0 && (
              <div className="space-y-2">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-[11px] font-semibold uppercase tracking-wide text-ink-mute">Задачи</div>
                  {taskCards.length > 1 && (
                    <div className="flex items-center gap-1 text-[11px] text-ink-mute">
                      <span>сортировка:</span>
                      <button
                        onClick={() => setTaskSortMode(m => m === "custom" ? "date" : "custom")}
                        className="font-medium text-ink transition-colors hover:text-ink/75"
                        title="Переключить сортировку: своя / дата"
                      >
                        {taskSortMode === "custom" ? "своя" : "дата"}
                      </button>
                      <button
                        onClick={() => setTaskSortDir(d => d === "desc" ? "asc" : "desc")}
                        className="ml-1 text-ink-mute transition-colors hover:text-ink"
                        title={taskSortDir === "desc" ? "Сейчас сверху вниз" : "Сейчас снизу вверх"}
                      >
                        {taskSortDir === "desc" ? "↓" : "↑"}
                      </button>
                    </div>
                  )}
                </div>
                {taskCards.map((task, index) => {
                  const greyFacts = "greyFacts" in task && Array.isArray(task.greyFacts) ? task.greyFacts : [];
                  const isGapTask = greyFacts.length > 0;
                  const taskShiftY = (() => {
                    if (taskDragKey == null || taskDragStartIndex == null || taskDragTargetIndex == null || taskDragItemHeight === 0 || task.key === taskDragKey) return 0;
                    if (taskDragTargetIndex > taskDragStartIndex && index > taskDragStartIndex && index <= taskDragTargetIndex) return -taskDragItemHeight;
                    if (taskDragTargetIndex < taskDragStartIndex && index >= taskDragTargetIndex && index < taskDragStartIndex) return taskDragItemHeight;
                    return 0;
                  })();
                  const relatedFact = "relatedFactId" in task && typeof task.relatedFactId === "number"
                    ? relatedFactsById.get(task.relatedFactId)
                    : undefined;
                  const canExpand = "relatedFactId" in task && typeof task.relatedFactId === "number";
                  const expanded = expandedTaskKeys.has(task.key);

                  return (
                    <div key={task.key} id={`task-${task.key}`} data-task-key={task.key}
                      style={
                        taskDragKey === task.key
                          ? { transform: `translate3d(0, ${taskDragOffsetY}px, 0)` }
                          : taskShiftY
                            ? { transform: `translate3d(0, ${taskShiftY}px, 0)` }
                            : undefined
                      }
                      onClick={(e) => {
                        const target = e.target as HTMLElement;
                        if (target.closest("button, select, input, textarea, a, summary, [data-no-card-toggle]")) return;
                        if (canExpand || isGapTask) toggleTask(task.key);
                      }}
                      role={canExpand || isGapTask ? "button" : undefined}
                      tabIndex={canExpand || isGapTask ? 0 : undefined}
                      onKeyDown={(e) => {
                        if (!canExpand && !isGapTask) return;
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          toggleTask(task.key);
                        }
                      }}
                      className={`group/task relative rounded-xl border border-ink-line bg-white p-3.5 shadow-[0_4px_18px_rgba(35,39,28,0.04)]
                        transition-[background-color,box-shadow,opacity,transform] duration-300 ease-out hover:-translate-y-px hover:bg-[#fbfbf7]
                        ${canExpand || isGapTask ? "cursor-pointer" : ""} ${taskDragKey === task.key ? "z-20 bg-[#fbfbf7] opacity-80 shadow-[0_16px_34px_rgba(35,39,28,0.12)]" : ""} ${taskDragOverKey === task.key ? "bg-[#fbfbf7]" : ""}`}>
                      <div>
                        <div className="min-w-0">
                          <div className="mb-1 flex items-start gap-2">
                            <div className="min-w-0 flex-1 text-[14px] font-semibold leading-tight text-ink">{task.title}</div>
                            <span
                              data-no-card-toggle
                              onPointerDown={(e) => {
                                e.preventDefault();
                                e.stopPropagation();
                                startTaskDrag(task.key, e);
                              }}
                              title="перетащить: изменить порядок"
                              className="ml-auto shrink-0 cursor-grab select-none text-[13px] leading-none text-ink-mute/0 transition-colors hover:text-ink-mute/70 group-hover/task:text-ink-mute/30 active:cursor-grabbing">⠿</span>
                          </div>
                          <div className="mt-1 text-[13px] text-ink-mute leading-snug whitespace-pre-wrap">{task.body}</div>
                          {isGapTask && (
                            <SmoothCollapse open={expanded}>
                              <div className="mt-3 space-y-2">
                                {greyFacts.map((gap, index) => (
                                  <div key={gap.id} className="rounded-lg border border-ink-line/80 bg-[#fbfbf7] p-2.5">
                                    <div className="mb-1 flex items-center gap-1.5 text-[10px] font-medium text-ink-mute">
                                      <span className="tabular-nums">{index + 1}</span>
                                      <span>открытый вопрос</span>
                                    </div>
                                    <div className="text-[12px] leading-snug text-ink">{gap.text}</div>
                                    <div className="mt-2 flex flex-wrap gap-1.5">
                                      <button
                                        onClick={(e) => { e.stopPropagation(); nav(`/clients/${clientId}/ingest`); }}
                                        className="rounded-lg border border-ink-line bg-white px-2 py-1 text-[11px] font-medium text-ink hover:bg-[#f6f6f1]"
                                        title="Перейти в сбор данных и добавить источник, который закрывает этот пробел"
                                      >
                                        Добавить источник
                                      </button>
                                      <button
                                        onClick={(e) => { e.stopPropagation(); nav(`/clients/${clientId}/interview`); }}
                                        className="rounded-lg border border-ink-line bg-white px-2 py-1 text-[11px] font-medium text-ink-mute hover:bg-[#f6f6f1] hover:text-ink"
                                        title="Перейти к вопросам интервью и использовать этот пробел как вопрос"
                                      >
                                        Вопрос для интервью
                                      </button>
                                    </div>
                                  </div>
                                ))}
                              </div>
                            </SmoothCollapse>
                          )}
                          {canExpand && (
                            <SmoothCollapse open={expanded}>
                              <div className="mt-3 rounded-lg border border-ink-line/80 bg-[#fbfbf7] p-2.5">
                                {relatedFact ? (
                                  <>
                                    <div className="mb-1 text-[10px] font-medium uppercase tracking-wide text-ink-mute">Факт на проверку</div>
                                    <div className="text-[12px] leading-snug text-ink">{relatedFact.text}</div>
                                    <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[10px] text-ink-mute">
                                      <span>уверенность {relatedFact.confidence.toFixed(2)}</span>
                                      {relatedFact.source_title && <span>· {relatedFact.source_title}</span>}
                                      {relatedFact.rationale && <span>· {relatedFact.rationale}</span>}
                                    </div>
                                  </>
                                ) : (
                                  <>
                                    <div className="mb-1 text-[10px] font-medium uppercase tracking-wide text-ink-mute">Связанный факт не найден</div>
                                    <div className="text-[12px] leading-snug text-ink-mute">
                                      Возможно, факт был удалён, слит с другой карточкой или перенесён после создания задачи.
                                    </div>
                                    <div className="mt-2 flex flex-wrap gap-1.5">
                                      <button
                                        onClick={(e) => { e.stopPropagation(); nav(`/clients/${clientId}/ingest`); }}
                                        className="rounded-lg border border-ink-line bg-white px-2 py-1 text-[11px] font-medium text-ink hover:bg-[#f6f6f1]"
                                      >
                                        Добавить источник
                                      </button>
                                    </div>
                                  </>
                                )}
                              </div>
                            </SmoothCollapse>
                          )}
                          {"firstMaterialActions" in task && Array.isArray(task.firstMaterialActions) && (
                            <div className="mt-2 flex flex-wrap gap-1.5">
                              <button
                                onClick={(e) => { e.stopPropagation(); nav(`/clients/${clientId}/ingest`); }}
                                className="rounded-lg border border-ink-line bg-white px-2 py-1 text-[11px] font-medium text-ink hover:bg-[#f6f6f1]"
                              >
                                Добавить источник
                              </button>
                              {(task.firstMaterialActions.some(isInterviewWorkTitle) || subsection?.layer.id && subsection.layer.id <= 3) && (
                                <button
                                  onClick={(e) => { e.stopPropagation(); nav(`/clients/${clientId}/interview`); }}
                                  className="rounded-lg border border-ink-line bg-white px-2 py-1 text-[11px] font-medium text-ink-mute hover:bg-[#f6f6f1] hover:text-ink"
                                >
                                  Вопрос для интервью
                                </button>
                              )}
                            </div>
                          )}
                        </div>
                        {(task.meta || isGapTask) && (
                          <div className="mt-2.5 flex items-center justify-between gap-3 border-t border-ink-line/50 pt-2 text-[11px] text-ink-mute">
                            <div className="min-w-0">
                              {task.meta && <span className="font-medium">{task.meta}</span>}
                              {isGapTask && <span>{greyFacts.length} {questionPlural(greyFacts.length)}</span>}
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}

            {/* merged-away originals under a collapsible (each keeps its own source) */}
            {hidden.length > 0 && (
              <details open={showHidden} onToggle={e => setShowHidden((e.currentTarget as HTMLDetailsElement).open)}
                className="rounded-lg border border-dashed border-ink-line p-2">
                <summary className="text-[11px] text-ink-mute cursor-pointer list-none">
                  показать {hidden.length} исходных карточек
                </summary>
                <div className="mt-2 space-y-2">
                  {hidden.map(h => (
                    <div key={h.id} id={`fact-${h.id}`} className="rounded border border-ink-line bg-slate-50/60 p-2.5 transition-shadow">
                      <div className="flex items-center justify-between gap-2 mb-1">
                        <span className="flex items-center gap-2 text-[10px] text-ink-mute">
                          <FlagDot flag={h.flag} size={9} />
                          <span className="px-1.5 py-0.5 rounded bg-slate-200/70">
                            исходная{h.merged_into ? ` · в #${h.merged_into}` : ""}
                          </span>
                        </span>
                        <span className="flex items-center gap-2 shrink-0">
                          {h.merged_into && (
                            <button onClick={() => jumpTo(h.merged_into!)} className="text-[11px] text-blue-600 hover:underline">↑ к общей #{h.merged_into}</button>
                          )}
                          <button onClick={() => restoreFact.mutate(h.id)} className="text-[11px] text-ink-mute hover:text-ink">вернуть</button>
                        </span>
                      </div>
                      {h.title && <div className="text-xs font-semibold text-ink-mute leading-tight">{h.title}</div>}
                      <div className="text-xs leading-snug whitespace-pre-wrap text-ink-mute">{h.text}</div>
                      {/* originals keep their own provenance — always shown here */}
                      <div className="mt-1.5 pt-1.5 border-t border-ink-line/60">
                        {h.evidence_snippet && (
                          <blockquote className="text-[11px] text-ink-mute border-l-2 border-ink-line pl-2 italic leading-snug mb-1">{h.evidence_snippet}</blockquote>
                        )}
                        <SourceLine client_id={clientId} channel={h.source_channel} source_url={h.source_url}
                          source_title={h.source_title} source_archive_url={h.source_archive_url}
                          ingest_audit_id={h.ingest_audit_id} ingest_kind={h.ingest_kind} audio_sha={h.audio_sha}
                          timestamp_sec={h.snippet_start_sec ?? undefined} captured_at={h.captured_at}
                          onOpenAudio={(sha, sec) => openAudio(h.id, sha, sec)} />
                      </div>
                    </div>
                  ))}
                </div>
              </details>
            )}
          </>);
        })()}
      </div>

      {!auditFocus && <div className="border-t border-ink-line p-4 bg-slate-50">
        {!showAdd ? (
          <button
            onClick={() => setShowAdd(true)}
            className="w-full text-sm px-3 py-2 bg-ink text-white rounded hover:bg-black"
          >+ Добавить факт</button>
        ) : (
          <div className="space-y-2">
            <textarea
              placeholder="Текст факта"
              value={newText}
              onChange={e => setNewText(e.target.value)}
              className="w-full text-sm border border-ink-line rounded px-2 py-1.5 min-h-[5rem]"
            />
            <div className="grid grid-cols-2 gap-2">
              <FlagPicker value={newFlag} onChange={setNewFlag} />
              <select
                value={newChannel}
                onChange={e => setNewChannel(e.target.value as Channel)}
                className="text-sm border border-ink-line rounded px-2 py-1.5"
              >
                <option value="online_research">онлайн-исследование</option>
                <option value="online_interview">онлайн-интервью</option>
                <option value="archival">архив</option>
                <option value="offline_interview">офлайн-интервью</option>
              </select>
            </div>
            <input
              placeholder="Название источника (опц.)"
              value={newSourceTitle}
              onChange={e => setNewSourceTitle(e.target.value)}
              className="w-full text-sm border border-ink-line rounded px-2 py-1.5"
            />
            <input
              placeholder={snippetRequired ? "URL источника (обязательно для онлайн/архива)" : "URL источника (опц.)"}
              value={newSourceUrl}
              onChange={e => setNewSourceUrl(e.target.value)}
              className="w-full text-sm border border-ink-line rounded px-2 py-1.5"
            />
            <div>
              <textarea
                placeholder={snippetRequired
                  ? "Цитата из источника ≥20 символов (обязательно)"
                  : "Цитата из источника (опц.)"}
                value={newSnippet}
                onChange={e => setNewSnippet(e.target.value)}
                rows={3}
                className={`w-full text-sm border rounded px-2 py-1.5 resize-none
                  ${snippetRequired && newSnippet.trim().length > 0 && !snippetValid
                    ? "border-red-400" : "border-ink-line"}`}
              />
              {snippetRequired && (
                <div className={`text-[10px] mt-0.5 ${snippetValid ? "text-ink-mute" : "text-red-500"}`}>
                  {newSnippet.trim().length}/20 символов минимум
                </div>
              )}
            </div>
            <textarea
              placeholder={newFlag === "red"
                ? "Проблема: что именно требует внимания (обязательно для риска)"
                : "Пояснение (опц.)"}
              value={newRationale}
              onChange={e => setNewRationale(e.target.value)}
              rows={2}
              className={`w-full text-xs border rounded px-2 py-1.5 resize-none ${
                newFlag === "red" && !newRationale.trim() && newText
                  ? "border-red-400" : "border-ink-line"
              }`}
            />
            {channelHint && (
              <div className="text-[11px] text-ink-mute">{channelHint}</div>
            )}
            <div className="flex gap-2">
              <button
                onClick={() => addFact.mutate()}
                disabled={!newText.trim() || !snippetValid || (newFlag === "red" && !newRationale.trim()) || addFact.isPending}
                className="text-sm px-3 py-1.5 bg-ink text-white rounded hover:bg-black disabled:bg-slate-300"
                title={
                  !snippetValid ? "Для онлайн-источников нужна цитата минимум 20 символов"
                  : (newFlag === "red" && !newRationale.trim()) ? "Для риска нужно пояснение"
                  : undefined
                }
              >Сохранить</button>
              <button
                onClick={() => setShowAdd(false)}
                className="text-sm px-3 py-1.5 hover:bg-slate-200 rounded text-ink-mute"
              >Отмена</button>
            </div>
          </div>
        )}
      </div>}
    </aside>
  );
}

function flagLabel(f: Flag) {
  return f === "green" ? "факт" : f === "red" ? "риск" : "пробел";
}

function flagChipClass(f: Flag) {
  return f === "green"
    ? "bg-[#eaf3de] text-[#3b6d11]"
    : f === "red"
      ? "bg-[#fde8e3] text-[#9b3a2a]"
      : "bg-[#ecece6] text-ink-mute";
}

function reviewReason(f: Fact) {
  if (f.state === "review") return "карточка ждёт одобрения владельца данных.";
  if (f.flag === "grey") return f.rationale ? "пробел нужно закрыть источником или уточнением." : "пробел без пояснения.";
  if (f.flag === "red") return f.rationale ? "риск требует решения или комментария." : "риск без пояснения.";
  if (f.verification === "questioned") return "формулировка или источник под вопросом.";
  if (f.verification === "refuted") return "факт помечен как опровергнутый.";
  return "карточка требует внимания в рамках проверки этой ячейки.";
}

function FlagPicker({ value, onChange }: { value: Flag; onChange: (f: Flag) => void }) {
  return (
    <select
      value={value}
      onChange={e => onChange(e.target.value as Flag)}
      className="text-sm border border-ink-line rounded px-2 py-1.5"
    >
      <option value="green">факт</option>
      <option value="red">риск</option>
      <option value="grey">пробел</option>
    </select>
  );
}
