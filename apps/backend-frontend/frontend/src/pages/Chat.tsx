// Chat: conversation sidebar (list, new, rename, delete), message thread, composer and model picker.
// Messages render as plain text only, so model output can never run as markup.
import {
  useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import { ApiError } from "../api";
import {
  createConversation, deleteConversation, getConversation, listChatModels, listConversations, renameConversation,
  streamChatMessage, type ChatMessage, type ChatModel, type ConversationSummary, type Provider,
} from "../chatApi";
import { Badge, Button, Dialog, ErrorState, Skeleton, useToast } from "../components/ui";
import { tr, type ThKey } from "../i18n/th";
import { errorDetail, errorTitle } from "./errors";

const PROVIDERS: { id: Provider; key: ThKey }[] = [
  { id: "claude", key: "chat.provider.claude" },
  { id: "gemini", key: "chat.provider.gemini" },
  { id: "gpt", key: "chat.provider.gpt" },
  { id: "ollama", key: "chat.provider.ollama" },
];
const CONTROL = "min-h-10 w-full rounded-sm border border-line bg-surface px-3 text-sm text-fg";
const TITLE_MAX = 120;
const MAX_INPUT_CHARS = 4000;
const COMPOSER_MAX_LINES = 6;
const PIN_THRESHOLD_PX = 48;
const MD_QUERY = "(min-width: 768px)";
const RAIL_KEY = "bf-chat-rail";
const FOCUSABLE = "button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], [tabindex]:not([tabindex='-1'])";
const SKELETON_KEYS = ["sk-1", "sk-2", "sk-3", "sk-4"] as const;
const FALLBACK_FOCUS = "__sidebar__";

type SendError = { error: ApiError; content: string; model: string };
type RenameState = { id: string; draft: string; error: string | null } | null;

const rowId = (id: string): string => `chat-conv-${id}`;
const deleteBtnId = (id: string): string => `chat-conv-del-${id}`;

function pickModel(models: ChatModel[]): string {
  return (models.find((m) => m.configured) ?? models[0])?.id ?? "";
}

function isMdUp(): boolean {
  return window.matchMedia(MD_QUERY).matches;
}

function readRail(): boolean {
  try {
    return window.localStorage.getItem(RAIL_KEY) !== "closed";
  } catch {
    return true;
  }
}

function writeRail(open: boolean): void {
  try {
    window.localStorage.setItem(RAIL_KEY, open ? "open" : "closed");
  } catch {
    // storage blocked: the toggle still works for this visit
  }
}

function formatUpdated(iso: string): string {
  const t = Date.parse(iso);
  return Number.isNaN(t) ? "" : new Date(t).toLocaleString("th-TH", { dateStyle: "medium", timeStyle: "short" });
}

/** Grows the composer with its text, up to COMPOSER_MAX_LINES, then lets it scroll. */
function fitComposer(el: HTMLTextAreaElement | null): void {
  if (!el) return;
  el.style.height = "auto";
  const cs = window.getComputedStyle(el);
  const chrome = parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom)
    + parseFloat(cs.borderTopWidth) + parseFloat(cs.borderBottomWidth);
  const maxPx = (parseFloat(cs.lineHeight) || 0) * COMPOSER_MAX_LINES + chrome;
  el.style.height = `${Math.min(el.scrollHeight, maxPx)}px`;
  el.style.overflowY = el.scrollHeight > maxPx ? "auto" : "hidden";
}

/* ---------- Copy button for complete assistant replies ---------- */

function CopyButton({ text }: { text: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  useEffect(() => {
    if (state === "idle") return;
    const t = window.setTimeout(() => setState("idle"), 2000);
    return () => window.clearTimeout(t);
  }, [state]);
  const copy = async () => {
    try {
      if (!navigator.clipboard) throw new Error("no clipboard");
      await navigator.clipboard.writeText(text);
      setState("copied");
    } catch {
      setState("failed");
    }
  };
  const label = state === "copied" ? tr("chat.copy.done") : state === "failed" ? tr("chat.copy.failed") : tr("chat.copy");
  return <Button variant="ghost" onClick={() => void copy()}>{label}</Button>;
}

/* ---------- One message in the thread ---------- */

function MessageItem({ message, streaming, onRetry }: { message: ChatMessage; streaming: boolean; onRetry: () => void }) {
  const isUser = message.role === "user";
  const who = isUser ? tr("chat.msg.user") : tr("chat.msg.assistant");
  const text = message.content || (streaming ? tr("chat.msg.placeholder") : "");
  const stopped = message.status === "partial" && !streaming;
  return (
    <article aria-label={who} className={`flex flex-col gap-1 ${isUser ? "items-end" : "items-start"}`}>
      <span className="text-xs text-muted">{who}</span>
      <div className={`max-w-[85%] rounded-md border border-line px-3 py-2 text-sm ${isUser ? "bg-accent-weak" : "bg-surface-2"}`}>
        <p className="whitespace-pre-wrap break-words">{text}</p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {stopped && <Badge status="warn">{tr("chat.msg.stopped")}</Badge>}
        {streaming && !isUser && <span className="text-xs text-muted">{tr("chat.msg.streaming")}</span>}
        {!isUser && message.status === "complete" && message.content && !streaming && <CopyButton text={message.content} />}
        {stopped && !message.content && <Button variant="secondary" onClick={onRetry}>{tr("chat.retry")}</Button>}
      </div>
    </article>
  );
}

/* ---------- Model picker: grouped by provider; unconfigured models stay focusable (aria-disabled) ---------- */

function ModelPicker({ id, models, value, onChange }: { id: string; models: ChatModel[]; value: string; onChange: (v: string) => void }) {
  const usable = models.some((m) => m.configured);
  const pick = (next: string) => {
    const chosen = models.find((m) => m.id === next);
    if (chosen?.configured) onChange(next);
  };
  return (
    <div className="flex w-full flex-col gap-1 sm:w-64">
      <label htmlFor={id} className="text-sm font-medium text-fg">{tr("chat.model.label")}</label>
      <select id={id} value={usable ? value : ""} onChange={(e) => pick(e.target.value)} className={CONTROL}>
        {!usable && <option value="" aria-disabled="true">{tr("chat.model.none")}</option>}
        {PROVIDERS.map((p) => {
          const items = models.filter((m) => m.provider === p.id);
          if (items.length === 0) return null;
          return (
            <optgroup key={p.id} label={tr(p.key)}>
              {items.map((m) => (
                <option key={m.id} value={m.id} aria-disabled={!m.configured || undefined}>
                  {m.configured ? m.label : tr("chat.model.unconfigured", { label: m.label })}
                </option>
              ))}
            </optgroup>
          );
        })}
      </select>
    </div>
  );
}

/* ---------- Inline rename: Enter saves, Escape cancels ---------- */

function RenameRow({ draft, error, onChange, onSave, onCancel }: {
  draft: string; error: string | null; onChange: (v: string) => void; onSave: () => void; onCancel: () => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const errorId = useId();
  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);
  const onKey = (e: ReactKeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation(); // keep Escape from also closing the mobile overlay
      onCancel();
    }
  };
  return (
    <form onSubmit={(e) => { e.preventDefault(); onSave(); }} className="flex w-full min-w-0 flex-col gap-1">
      <input ref={inputRef} aria-label={tr("chat.rename.field")} value={draft} maxLength={TITLE_MAX}
        onChange={(e) => onChange(e.target.value)} onKeyDown={onKey}
        aria-invalid={error ? true : undefined} aria-describedby={error ? errorId : undefined}
        className="min-h-10 w-full min-w-0 rounded-sm border border-line bg-surface px-2 text-sm text-fg" />
      {error && <p id={errorId} role="alert" className="text-xs text-bad">{error}</p>}
      <div className="flex gap-2">
        <Button variant="primary" type="submit">{tr("chat.rename.save")}</Button>
        <Button onClick={onCancel}>{tr("chat.rename.cancel")}</Button>
      </div>
    </form>
  );
}

/* ---------- Delete confirmation (default focus lands on the cancel button, the first in the footer) ---------- */

function DeleteDialog({ onCancel, onConfirm }: { onCancel: () => void; onConfirm: () => void }) {
  return (
    <Dialog open onClose={onCancel} title={tr("chat.delete.title")} actions={
      <>
        <Button onClick={onCancel}>{tr("chat.cancel")}</Button>
        <Button variant="danger" onClick={onConfirm}>{tr("chat.delete.confirm")}</Button>
      </>
    }>
      <p>{tr("chat.delete.body")}</p>
    </Dialog>
  );
}

const SKELETON_THREAD = (
  <>
    <Skeleton className="h-16 w-2/3" />
    <Skeleton className="ml-auto h-12 w-1/2" />
  </>
);

/* ---------- Page ---------- */

export function Chat({ onAuthLost }: { onAuthLost: () => void }) {
  const toast = useToast();
  const pickerId = useId();
  const inputId = useId();
  const errorId = useId();
  const sidebarTitleId = useId();
  const [models, setModels] = useState<ChatModel[]>([]);
  const [conversations, setConversations] = useState<ConversationSummary[] | null>(null);
  const [listError, setListError] = useState<ApiError | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [threadLoading, setThreadLoading] = useState(false);
  const [model, setModel] = useState("");
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [composerError, setComposerError] = useState<string | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [announce, setAnnounce] = useState("");
  const [pageError, setPageError] = useState<ApiError | null>(null);
  const [sendError, setSendError] = useState<SendError | null>(null);
  const [overlayOpen, setOverlayOpen] = useState(false);
  const [railOpen, setRailOpen] = useState(readRail);
  const [mdUp, setMdUp] = useState(isMdUp);
  const [deleteTarget, setDeleteTarget] = useState<ConversationSummary | null>(null);
  const [renaming, setRenaming] = useState<RenameState>(null);
  const activeRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const threadRef = useRef<HTMLDivElement>(null);
  const sidebarRef = useRef<HTMLElement>(null);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const pinnedRef = useRef(true);
  const focusComposerRef = useRef(false);
  const deleteOpenerRef = useRef<string | null>(null);
  const pendingFocusRef = useRef<string | null>(null);

  const input = activeId ? (drafts[activeId] ?? "") : "";
  const usable = models.some((m) => m.configured);
  const sorted = useMemo(
    () => conversations && [...conversations].sort((a, b) => (Date.parse(b.updated_at) || 0) - (Date.parse(a.updated_at) || 0)),
    [conversations],
  );
  const activeConv = conversations?.find((c) => c.id === activeId) ?? null;
  const headerTitle = activeId ? (activeConv?.title || tr("chat.title.untitled")) : tr("chat.title.fallback");

  const setInput = (value: string) => {
    if (!activeId) return;
    setDrafts((prev) => ({ ...prev, [activeId]: value }));
    setComposerError(null);
  };

  // Converts any failure to ApiError; an expired session sends the user back to login.
  const fail = useCallback((err: unknown, fallback: string): ApiError => {
    const e = err instanceof ApiError ? err : new ApiError("unknown", fallback, true);
    if (e.type === "auth") onAuthLost();
    return e;
  }, [onAuthLost]);

  const refreshList = useCallback(async () => {
    try {
      setConversations(await listConversations());
      setListError(null);
    } catch (err) {
      setListError(fail(err, tr("chat.list.error")));
    }
  }, [fail]);

  const reloadThread = useCallback(async (convId: string) => {
    try {
      const detail = await getConversation(convId);
      if (activeRef.current === convId) setMessages(detail.messages);
    } catch {
      // Keep the local thread; the list refresh reports session problems.
    }
  }, []);

  // Switches the active conversation and aborts any stream still running for the previous one.
  const activate = useCallback((id: string | null) => {
    abortRef.current?.abort();
    activeRef.current = id;
    setActiveId(id);
    setMessages([]);
    setSendError(null);
    setPageError(null);
    setComposerError(null);
    setThreadLoading(false);
    pinnedRef.current = true;
  }, []);

  // Closes the mobile overlay and returns focus to its toggle (scrim, close button, Escape, or picking a chat).
  const closeOverlay = useCallback(() => {
    setOverlayOpen(false);
    if (!isMdUp()) toggleRef.current?.focus();
  }, []);

  const openConversation = useCallback(async (id: string) => {
    activate(id);
    setThreadLoading(true);
    try {
      const detail = await getConversation(id);
      if (activeRef.current === id) {
        setMessages(detail.messages);
        setModel(detail.model);
      }
    } catch (err) {
      if (activeRef.current === id) setPageError(fail(err, tr("chat.thread.openFail")));
    } finally {
      if (activeRef.current === id) setThreadLoading(false);
    }
  }, [activate, fail]);

  const loadAll = useCallback(async () => {
    const [modelRes, listRes] = await Promise.allSettled([listChatModels(), listConversations()]);
    if (modelRes.status === "fulfilled") {
      setModels(modelRes.value);
      setModel((current) => current || pickModel(modelRes.value));
      setPageError(null);
    } else {
      setPageError(fail(modelRes.reason, tr("chat.page.loadFail")));
    }
    if (listRes.status === "fulfilled") {
      setConversations(listRes.value);
      setListError(null);
      const first = listRes.value[0];
      if (first && activeRef.current === null) await openConversation(first.id);
    } else {
      setListError(fail(listRes.reason, tr("chat.list.error")));
    }
  }, [fail, openConversation]);

  useEffect(() => { void loadAll(); }, [loadAll]);

  // The rail state (tablet) is remembered per viewer; the overlay state is not.
  useEffect(() => { writeRail(railOpen); }, [railOpen]);

  // Crossing into desktop width ends the overlay, so the overlay state never lingers there.
  useEffect(() => {
    const mql = window.matchMedia(MD_QUERY);
    const onChange = () => {
      setMdUp(mql.matches);
      if (mql.matches) setOverlayOpen(false);
    };
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, []);

  // While the mobile overlay is open: focus moves into it, Tab cycles inside it, Escape closes it.
  useEffect(() => {
    if (!overlayOpen) return;
    const aside = sidebarRef.current;
    aside?.querySelector<HTMLElement>(FOCUSABLE)?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (document.querySelector("dialog[open]")) return; // a confirm dialog owns the keyboard
      if (e.key === "Escape") {
        closeOverlay();
        return;
      }
      if (e.key !== "Tab" || !aside) return;
      const items = Array.from(aside.querySelectorAll<HTMLElement>(FOCUSABLE));
      const head = items[0];
      const tail = items[items.length - 1];
      if (!head || !tail) return;
      const active = document.activeElement;
      if (e.shiftKey && (active === head || !aside.contains(active))) {
        e.preventDefault();
        tail.focus();
      } else if (!e.shiftKey && (active === tail || !aside.contains(active))) {
        e.preventDefault();
        head.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [overlayOpen, closeOverlay]);

  // Returns focus after a rename or delete dialog closes; falls back to the first sidebar button when the row is gone.
  useEffect(() => {
    if (deleteTarget || renaming || !pendingFocusRef.current) return;
    const id = pendingFocusRef.current;
    pendingFocusRef.current = null;
    const target = id === FALLBACK_FOCUS ? null : document.getElementById(id);
    (target ?? sidebarRef.current?.querySelector<HTMLElement>("button"))?.focus();
  }, [deleteTarget, renaming]);

  // Moves focus into the composer once a new chat has rendered (the textarea is disabled until then).
  useEffect(() => {
    if (focusComposerRef.current && activeId) {
      focusComposerRef.current = false;
      composerRef.current?.focus();
    }
  }, [activeId]);

  // Follows new text only while the reader is at the bottom; scrolling up stops the follow.
  // biome-ignore lint/correctness/useExhaustiveDependencies: messages is the trigger; the body reads refs only
  useEffect(() => {
    const el = threadRef.current;
    if (el && pinnedRef.current) el.scrollTop = el.scrollHeight;
  }, [messages]);

  // biome-ignore lint/correctness/useExhaustiveDependencies: input is the trigger; fitComposer reads the element only
  useLayoutEffect(() => {
    fitComposer(composerRef.current);
  }, [input]);

  const onThreadScroll = () => {
    const el = threadRef.current;
    if (el) pinnedRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < PIN_THRESHOLD_PX;
  };

  // Sends one message and streams the reply into the thread. Guarded by abortRef against double sends.
  const sendMessage = useCallback(async (content: string, modelId: string) => {
    const convId = activeRef.current;
    if (!convId || abortRef.current) return;
    const controller = new AbortController();
    abortRef.current = controller;
    const stamp = new Date().toISOString();
    const pendingId = `pending-${Date.now()}`;
    let assistantId = pendingId;
    const isCurrent = () => activeRef.current === convId;
    const patchAssistant = (fn: (m: ChatMessage) => ChatMessage) => {
      if (!isCurrent()) return;
      const target = assistantId;
      setMessages((prev) => prev.map((m) => (m.id === target ? fn(m) : m)));
    };

    pinnedRef.current = true;
    if (isCurrent()) {
      setMessages((prev) => [
        ...prev,
        { id: `local-${pendingId}`, role: "user", content, status: "complete", created_at: stamp },
        { id: pendingId, role: "assistant", content: "", status: "complete", created_at: stamp },
      ]);
    }
    setStreaming(true);
    setSendError(null);
    setAnnounce(tr("chat.aria.thinking"));
    try {
      await streamChatMessage(convId, content, modelId, {
        signal: controller.signal,
        onStart: (id) => {
          const previous = assistantId;
          assistantId = id;
          if (isCurrent()) setMessages((prev) => prev.map((m) => (m.id === previous ? { ...m, id } : m)));
        },
        onDelta: (text) => patchAssistant((m) => ({ ...m, content: m.content + text })),
      });
      setAnnounce(tr("chat.aria.done"));
      await reloadThread(convId);
      await refreshList();
    } catch (err) {
      const e = fail(err, tr("chat.send.fail"));
      if (e.type === "cancelled") {
        // Stop keeps the partial reply on screen.
        patchAssistant((m) => ({ ...m, status: "partial" }));
      } else {
        // Failed send: the text goes back into this conversation's composer unless the user already typed something new.
        setDrafts((prev) => (prev[convId] ? prev : { ...prev, [convId]: content }));
        if (isCurrent()) setSendError({ error: e, content, model: modelId });
        setAnnounce(errorTitle(e));
        await reloadThread(convId);
      }
    } finally {
      if (abortRef.current === controller) {
        abortRef.current = null;
        setStreaming(false);
      }
    }
  }, [fail, reloadThread, refreshList]);

  const startNewChat = async () => {
    try {
      const conv = await createConversation(model || pickModel(models));
      setConversations((prev) => [conv, ...(prev ?? [])]);
      focusComposerRef.current = true;
      activate(conv.id);
      setModel(conv.model);
      closeOverlay();
    } catch (err) {
      toast.show("bad", fail(err, tr("chat.create.fail")).message);
    }
  };

  const submit = () => {
    if (!activeId || streaming || !usable) return;
    const content = input.trim();
    if (!content) {
      setComposerError(tr("chat.composer.empty"));
      return;
    }
    if (content.length > MAX_INPUT_CHARS) {
      setComposerError(tr("chat.composer.tooLong"));
      return;
    }
    setDrafts((prev) => ({ ...prev, [activeId]: "" }));
    void sendMessage(content, model);
    composerRef.current?.focus();
  };

  const retry = () => {
    if (!sendError || streaming) return;
    const { content, model: modelId } = sendError;
    setSendError(null);
    composerRef.current?.focus();
    void sendMessage(content, modelId);
  };

  // Retries a stopped reply that has no text: the stopped pair is dropped locally and the question is sent again.
  const retryReply = (index: number) => {
    const question = messages[index - 1];
    if (question?.role !== "user" || streaming) return;
    setMessages((list) => list.slice(0, index - 1));
    void sendMessage(question.content, model);
  };

  const onComposerKey = (e: ReactKeyboardEvent<HTMLTextAreaElement>) => {
    // Safari commits a Thai composition with keyCode 229 and isComposing=false; that Enter must not send.
    const composing = e.nativeEvent.isComposing || e.keyCode === 229;
    if (e.key === "Enter" && !e.shiftKey && !composing) {
      e.preventDefault();
      submit();
    }
  };

  const startRename = (c: ConversationSummary) => setRenaming({ id: c.id, draft: c.title, error: null });

  const cancelRename = () => {
    if (renaming) pendingFocusRef.current = rowId(renaming.id);
    setRenaming(null);
  };

  const saveRename = async () => {
    if (!renaming) return;
    const target = renaming;
    const title = target.draft.trim();
    if (!title) {
      setRenaming({ ...target, error: tr("chat.rename.empty") });
      return;
    }
    try {
      const updated = await renameConversation(target.id, title);
      setConversations((prev) => prev?.map((c) => (c.id === target.id ? { ...c, title: updated.title } : c)) ?? null);
      pendingFocusRef.current = rowId(target.id);
      setRenaming(null);
    } catch (err) {
      fail(err, tr("chat.rename.failed"));
      setRenaming((prev) => (prev && prev.id === target.id ? { ...prev, error: tr("chat.rename.failed") } : prev));
    }
  };

  const openDelete = (c: ConversationSummary) => {
    deleteOpenerRef.current = deleteBtnId(c.id);
    setDeleteTarget(c);
  };

  const closeDelete = () => {
    pendingFocusRef.current = deleteOpenerRef.current;
    deleteOpenerRef.current = null;
    setDeleteTarget(null);
  };

  const removeConversation = async (conv: ConversationSummary) => {
    setDeleteTarget(null);
    pendingFocusRef.current = FALLBACK_FOCUS;
    try {
      await deleteConversation(conv.id);
    } catch (err) {
      fail(err, tr("chat.delete.failed"));
      toast.show("bad", tr("chat.delete.failed"));
      return;
    }
    const rest = (conversations ?? []).filter((c) => c.id !== conv.id);
    setConversations(rest);
    setDrafts((prev) => Object.fromEntries(Object.entries(prev).filter(([key]) => key !== conv.id)));
    toast.show("ok", tr("chat.delete.done"));
    if (activeRef.current === conv.id) {
      if (rest[0]) void openConversation(rest[0].id);
      else activate(null);
    }
  };

  const stop = () => abortRef.current?.abort();

  const toggleSidebar = () => {
    if (isMdUp()) setRailOpen((open) => !open);
    else setOverlayOpen((open) => !open);
  };

  return (
    <div className="flex h-[calc(100dvh-12rem)] min-h-[28rem] flex-col gap-3 md:h-[calc(100dvh-9rem)] md:flex-row md:gap-4">
      {overlayOpen && (
        <button type="button" aria-label={tr("chat.sidebar.scrim")} onClick={closeOverlay} className="fixed inset-0 z-30 bg-black/40 md:hidden" />
      )}
      <aside id="chat-sidebar" ref={sidebarRef} aria-labelledby={sidebarTitleId}
        {...(overlayOpen ? { role: "dialog", "aria-modal": true } : {})}
        className={`flex w-[min(85vw,20rem)] flex-col gap-3 border-r border-line bg-surface p-3 transition-[transform,visibility] duration-(--motion-base)
          md:w-60 md:shrink-0 md:rounded-md md:border md:shadow-none lg:w-70 lg:flex ${railOpen ? "" : "md:hidden"}
          max-md:fixed max-md:inset-y-0 max-md:left-0 max-md:z-40 max-md:shadow-1
          ${overlayOpen ? "max-md:visible max-md:translate-x-0" : "max-md:invisible max-md:-translate-x-full"}`}>
        <h2 id={sidebarTitleId} className="sr-only">{tr("chat.sidebar.heading")}</h2>
        <div className="flex items-center gap-2">
          <Button variant="primary" className="flex-1" onClick={() => void startNewChat()}>{tr("chat.new")}</Button>
          <button type="button" onClick={closeOverlay}
            className="min-h-11 rounded-sm px-3 text-sm text-muted hover:bg-surface-2 hover:text-fg md:hidden">{tr("chat.sidebar.close")}</button>
        </div>
        {listError && (
          <ErrorState title={tr("chat.list.error")} detail={errorDetail(listError)}
            action={{ label: tr("chat.list.retry"), onClick: () => void refreshList() }} />
        )}
        <ul aria-label={tr("chat.list.all")} className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto">
          {conversations === null && !listError && SKELETON_KEYS.map((key) => (
            <li key={key}><Skeleton className="h-11 w-full" /></li>
          ))}
          {conversations?.length === 0 && <li className="px-2 text-sm text-muted">{tr("chat.list.empty")}</li>}
          {sorted?.map((c) => (
            <li key={c.id} className="flex items-center gap-1">
              {renaming?.id === c.id ? (
                <RenameRow draft={renaming.draft} error={renaming.error}
                  onChange={(draft) => setRenaming((prev) => (prev ? { ...prev, draft, error: null } : prev))}
                  onSave={() => void saveRename()} onCancel={cancelRename} />
              ) : (
                <>
                  <button type="button" id={rowId(c.id)} title={c.title} aria-current={c.id === activeId ? "page" : undefined}
                    onClick={() => { closeOverlay(); void openConversation(c.id); }}
                    className={`min-w-0 flex-1 rounded-sm px-2 py-2 text-left text-sm ${c.id === activeId ? "bg-accent-weak font-medium text-fg" : "text-muted hover:bg-surface-2 hover:text-fg"}`}>
                    <span className="block truncate">{c.title}</span>
                    <span className="block truncate text-xs text-muted">{formatUpdated(c.updated_at)}</span>
                  </button>
                  <button type="button" aria-label={tr("chat.rename.aria", { title: c.title })} onClick={() => startRename(c)}
                    className="rounded-sm px-1.5 py-1 text-xs text-muted hover:text-fg">{tr("chat.rename.open")}</button>
                  <button type="button" id={deleteBtnId(c.id)} aria-label={tr("chat.delete.aria", { title: c.title })} onClick={() => openDelete(c)}
                    className="rounded-sm px-1.5 py-1 text-xs text-bad hover:opacity-80">{tr("chat.delete.open")}</button>
                </>
              )}
            </li>
          ))}
        </ul>
      </aside>

      <section aria-labelledby="chat-heading"
        className="flex min-h-0 min-w-0 flex-1 flex-col gap-3 px-4 pb-4 md:rounded-md md:border md:border-line md:bg-surface md:p-4">
        <div className="flex flex-wrap items-end gap-3">
          <button ref={toggleRef} type="button" aria-expanded={mdUp ? railOpen : overlayOpen} aria-controls="chat-sidebar"
            onClick={toggleSidebar}
            className="min-h-11 min-w-11 rounded-sm border border-line bg-surface px-3 text-sm text-fg lg:hidden">{tr("chat.sidebar.open")}</button>
          <h1 id="chat-heading" className="mr-auto min-w-0 truncate text-xl font-semibold">{headerTitle}</h1>
          <ModelPicker id={pickerId} models={models} value={model} onChange={setModel} />
        </div>

        {models.length > 0 && !usable && (
          <p className="rounded-sm bg-warn-bg px-3 py-2 text-sm text-warn">{tr("chat.model.banner")}</p>
        )}

        {pageError ? (
          <ErrorState title={errorTitle(pageError)} detail={errorDetail(pageError)}
            action={{ label: tr("chat.retry"), onClick: () => void loadAll() }} />
        ) : (
          <div ref={threadRef} onScroll={onThreadScroll} role="log" aria-live="off" aria-label={tr("chat.thread.label")}
            className="flex min-h-0 flex-1 flex-col overflow-y-auto">
            <div className="mx-auto flex w-full max-w-content flex-col gap-4 p-1">
              {!activeId && <p className="py-8 text-center text-sm text-muted">{tr("chat.thread.pick")}</p>}
              {activeId && threadLoading && SKELETON_THREAD}
              {activeId && !threadLoading && messages.length === 0 && !streaming && (
                <p className="py-8 text-center text-sm text-muted">{tr("chat.thread.empty")}</p>
              )}
              {!threadLoading && messages.map((m, i) => (
                <MessageItem key={m.id} message={m}
                  streaming={streaming && m.role === "assistant" && i === messages.length - 1}
                  onRetry={() => retryReply(i)} />
              ))}
              {sendError && (
                <ErrorState title={errorTitle(sendError.error)} detail={errorDetail(sendError.error)}
                  action={sendError.error.retryable ? { label: tr("chat.retry"), onClick: retry } : undefined}
                  dismiss={{ label: tr("chat.dismiss"), onClick: () => setSendError(null) }} />
              )}
            </div>
          </div>
        )}

        <p role="status" aria-live="polite" className="sr-only">{announce}</p>

        <form onSubmit={(e) => { e.preventDefault(); submit(); }} className="flex flex-col gap-2 sm:flex-row sm:items-end">
          <label htmlFor={inputId} className="sr-only">{tr("chat.composer.label")}</label>
          <div className="flex w-full min-w-0 flex-1 flex-col gap-1">
            <textarea id={inputId} ref={composerRef} value={input} onChange={(e) => setInput(e.target.value)}
              onKeyDown={onComposerKey} disabled={!activeId || !usable} rows={2}
              placeholder={usable ? tr("chat.composer.placeholder") : tr("chat.composer.blocked")}
              aria-invalid={composerError ? true : undefined}
              aria-describedby={composerError ? errorId : undefined}
              className="min-h-12 w-full resize-none rounded-sm border border-line bg-surface px-3 py-2 text-sm text-fg placeholder:text-muted disabled:opacity-60" />
            {composerError && <p id={errorId} role="alert" className="text-sm text-bad">{composerError}</p>}
          </div>
          <div className="flex gap-2">
            {streaming ? (
              <Button variant="danger" onClick={stop} aria-label={tr("chat.stop.aria")}>{tr("chat.stop")}</Button>
            ) : (
              <Button variant="primary" type="submit" disabled={!activeId || !usable}>{tr("chat.send")}</Button>
            )}
          </div>
        </form>
      </section>

      {deleteTarget && (
        <DeleteDialog onCancel={closeDelete} onConfirm={() => void removeConversation(deleteTarget)} />
      )}
    </div>
  );
}
