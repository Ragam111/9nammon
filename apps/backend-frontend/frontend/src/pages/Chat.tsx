// Chat: conversation sidebar (list, new, rename, delete), message thread, composer and model picker.
// Messages render as plain text only, so model output can never run as markup.
import { useCallback, useEffect, useId, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { ApiError } from "../api";
import {
  createConversation, deleteConversation, getConversation, listChatModels, listConversations, renameConversation,
  streamChatMessage, type ChatMessage, type ChatModel, type ConversationSummary, type Provider,
} from "../chatApi";
import { Badge, Button, Dialog, ErrorState, Input, Skeleton, useToast } from "../components/ui";
import { errorDetail, errorTitle } from "./errors";

const PROVIDERS: { id: Provider; label: string }[] = [
  { id: "claude", label: "Claude" }, { id: "gemini", label: "Gemini" }, { id: "gpt", label: "GPT" },
];
const CONTROL = "min-h-10 w-full rounded-sm border border-line bg-surface px-3 text-sm text-fg";
const TITLE_MAX = 120;

type SendError = { error: ApiError; content: string; model: string };
type DialogState = { kind: "rename" | "delete"; conv: ConversationSummary } | null;

function pickModel(models: ChatModel[]): string {
  return (models.find((m) => m.configured) ?? models[0])?.id ?? "";
}

/* ---------- Copy button for assistant replies ---------- */

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
  const label = state === "copied" ? "คัดลอกแล้ว" : state === "failed" ? "คัดลอกไม่ได้" : "คัดลอก";
  return <Button variant="ghost" onClick={() => void copy()} aria-label={`${label} คำตอบ`}>{label}</Button>;
}

/* ---------- One message in the thread ---------- */

function MessageItem({ message, streaming }: { message: ChatMessage; streaming: boolean }) {
  const isUser = message.role === "user";
  const who = isUser ? "คุณ" : "ผู้ช่วย";
  const text = message.content || (streaming ? "กำลังตอบ…" : "");
  return (
    <article aria-label={who} className={`flex flex-col gap-1 ${isUser ? "items-end" : "items-start"}`}>
      <span className="text-xs text-muted">{who}</span>
      <div className={`max-w-[85%] rounded-md border border-line px-3 py-2 text-sm ${isUser ? "bg-accent-weak" : "bg-surface-2"}`}>
        <p className="whitespace-pre-wrap break-words">{text}</p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {message.status === "partial" && !streaming && <Badge status="warn">ตอบไม่ครบ</Badge>}
        {!isUser && message.content && !streaming && <CopyButton text={message.content} />}
      </div>
    </article>
  );
}

/* ---------- Model picker: grouped by provider, unconfigured options disabled ---------- */

function ModelPicker({ id, models, value, onChange }: { id: string; models: ChatModel[]; value: string; onChange: (v: string) => void }) {
  return (
    <div className="flex w-full flex-col gap-1 sm:w-64">
      <label htmlFor={id} className="text-sm font-medium text-fg">โมเดล</label>
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)} className={CONTROL}>
        {PROVIDERS.map((p) => {
          const items = models.filter((m) => m.provider === p.id);
          if (items.length === 0) return null;
          return (
            <optgroup key={p.id} label={p.label}>
              {items.map((m) => (
                <option key={m.id} value={m.id} disabled={!m.configured}>
                  {m.configured ? m.label : `${m.label} (ยังไม่ตั้งค่า)`}
                </option>
              ))}
            </optgroup>
          );
        })}
      </select>
    </div>
  );
}

/* ---------- Dialogs ---------- */

function RenameDialog({ conv, onCancel, onSave }: { conv: ConversationSummary; onCancel: () => void; onSave: (title: string) => void }) {
  const [draft, setDraft] = useState(conv.title);
  const trimmed = draft.trim();
  const valid = trimmed.length >= 1 && trimmed.length <= TITLE_MAX;
  return (
    <Dialog open onClose={onCancel} title="เปลี่ยนชื่อการสนทนา" actions={
      <>
        <Button onClick={onCancel}>ยกเลิก</Button>
        <Button variant="primary" type="submit" form="rename-form" disabled={!valid}>บันทึก</Button>
      </>
    }>
      <form id="rename-form" onSubmit={(e) => { e.preventDefault(); if (valid) onSave(trimmed); }}>
        <Input label="ชื่อใหม่" value={draft} maxLength={TITLE_MAX} onChange={(e) => setDraft(e.target.value)}
          hint={`1–${TITLE_MAX} ตัวอักษร`} />
      </form>
    </Dialog>
  );
}

function DeleteDialog({ conv, onCancel, onConfirm }: { conv: ConversationSummary; onCancel: () => void; onConfirm: () => void }) {
  return (
    <Dialog open onClose={onCancel} title="ลบการสนทนานี้?" actions={
      <>
        <Button onClick={onCancel}>ยกเลิก</Button>
        <Button variant="danger" onClick={onConfirm}>ลบถาวร</Button>
      </>
    }>
      <p>ลบ "{conv.title}" และข้อความทั้งหมดในการสนทนานี้ การลบนี้ย้อนกลับไม่ได้</p>
    </Dialog>
  );
}

/* ---------- Page ---------- */

export function Chat({ onAuthLost }: { onAuthLost: () => void }) {
  const toast = useToast();
  const pickerId = useId();
  const inputId = useId();
  const [models, setModels] = useState<ChatModel[]>([]);
  const [conversations, setConversations] = useState<ConversationSummary[] | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [model, setModel] = useState("");
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [pageError, setPageError] = useState<ApiError | null>(null);
  const [sendError, setSendError] = useState<SendError | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [dialog, setDialog] = useState<DialogState>(null);
  const activeRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const threadRef = useRef<HTMLDivElement>(null);
  const toggleRef = useRef<HTMLButtonElement>(null);

  // Converts any failure to ApiError; an expired session sends the user back to login.
  const fail = useCallback((err: unknown, fallback: string): ApiError => {
    const e = err instanceof ApiError ? err : new ApiError("unknown", fallback, true);
    if (e.type === "auth") onAuthLost();
    return e;
  }, [onAuthLost]);

  const refreshList = useCallback(async () => {
    try {
      setConversations(await listConversations());
    } catch (err) {
      toast.show("bad", fail(err, "โหลดรายการการสนทนาไม่สำเร็จ").message);
    }
  }, [fail, toast]);

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
  }, []);

  const openConversation = useCallback(async (id: string) => {
    activate(id);
    setSidebarOpen(false);
    try {
      const detail = await getConversation(id);
      if (activeRef.current === id) {
        setMessages(detail.messages);
        setModel(detail.model);
      }
    } catch (err) {
      if (activeRef.current === id) setPageError(fail(err, "เปิดการสนทนาไม่สำเร็จ"));
    }
  }, [activate, fail]);

  const loadAll = useCallback(async () => {
    try {
      const [modelList, convList] = await Promise.all([listChatModels(), listConversations()]);
      setModels(modelList);
      setConversations(convList);
      setModel((current) => current || pickModel(modelList));
      setPageError(null);
      const first = convList[0];
      if (first && activeRef.current === null) await openConversation(first.id);
    } catch (err) {
      setPageError(fail(err, "โหลดหน้าแชทไม่สำเร็จ"));
    }
  }, [fail, openConversation]);

  useEffect(() => { void loadAll(); }, [loadAll]);

  // Escape closes the mobile overlay and returns focus to its toggle.
  useEffect(() => {
    if (!sidebarOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setSidebarOpen(false);
        toggleRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [sidebarOpen]);

  // Runs after every render so the thread stays pinned to the newest text while streaming.
  useEffect(() => {
    const el = threadRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  });

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

    if (isCurrent()) {
      setMessages((prev) => [
        ...prev,
        { id: `local-${pendingId}`, role: "user", content, status: "complete", created_at: stamp },
        { id: pendingId, role: "assistant", content: "", status: "complete", created_at: stamp },
      ]);
    }
    setStreaming(true);
    setSendError(null);
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
      await reloadThread(convId);
      await refreshList();
    } catch (err) {
      const e = fail(err, "ส่งข้อความไม่สำเร็จ");
      if (e.type === "cancelled") {
        // Stop keeps the partial reply on screen.
        patchAssistant((m) => ({ ...m, status: "partial" }));
      } else {
        if (isCurrent()) setSendError({ error: e, content, model: modelId });
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
      activate(conv.id);
      setModel(conv.model);
      setSidebarOpen(false);
      composerRef.current?.focus();
    } catch (err) {
      toast.show("bad", fail(err, "สร้างการสนทนาไม่สำเร็จ").message);
    }
  };

  const submit = () => {
    const content = input.trim();
    if (!content || streaming || !activeId) return;
    setInput("");
    void sendMessage(content, model);
    composerRef.current?.focus();
  };

  const retry = () => {
    if (!sendError || streaming) return;
    const { content, model: modelId } = sendError;
    composerRef.current?.focus();
    void sendMessage(content, modelId);
  };

  const onComposerKey = (e: ReactKeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };

  const saveRename = async (conv: ConversationSummary, title: string) => {
    setDialog(null);
    try {
      const updated = await renameConversation(conv.id, title);
      setConversations((prev) => prev?.map((c) => (c.id === conv.id ? { ...c, title: updated.title } : c)) ?? null);
    } catch (err) {
      toast.show("bad", fail(err, "เปลี่ยนชื่อไม่สำเร็จ").message);
    }
  };

  const removeConversation = async (conv: ConversationSummary) => {
    setDialog(null);
    try {
      await deleteConversation(conv.id);
    } catch (err) {
      toast.show("bad", fail(err, "ลบการสนทนาไม่สำเร็จ").message);
      return;
    }
    const rest = (conversations ?? []).filter((c) => c.id !== conv.id);
    setConversations(rest);
    toast.show("ok", "ลบการสนทนาแล้ว");
    if (activeRef.current === conv.id) {
      if (rest[0]) void openConversation(rest[0].id);
      else activate(null);
    }
  };

  const stop = () => abortRef.current?.abort();
  const activeConv = conversations?.find((c) => c.id === activeId) ?? null;
  const noneConfigured = models.length > 0 && !models.some((m) => m.configured);
  const closeSidebar = () => setSidebarOpen(false);

  return (
    <div className="flex h-[calc(100dvh-9rem)] min-h-[28rem] flex-col gap-3 md:flex-row md:gap-4">
      {sidebarOpen && (
        <button type="button" aria-label="ปิดเมนูการสนทนา" onClick={closeSidebar} className="fixed inset-0 z-30 bg-black/40 md:hidden" />
      )}
      <aside id="chat-sidebar" aria-label="รายการการสนทนา"
        className={`${sidebarOpen ? "fixed inset-y-0 left-0 z-40 flex w-72 max-w-[85vw] shadow-1" : "hidden"} flex-col gap-3 border-r border-line bg-surface p-3 md:static md:z-auto md:flex md:w-64 md:shrink-0 md:rounded-md md:border md:shadow-none`}>
        <div className="flex items-center gap-2">
          <Button variant="primary" className="flex-1" onClick={() => void startNewChat()}>แชทใหม่</Button>
          <Button variant="ghost" className="md:hidden" onClick={closeSidebar}>ปิด</Button>
        </div>
        <ul aria-label="การสนทนาทั้งหมด" className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto">
          {conversations === null && <li><Skeleton className="h-9 w-full" /></li>}
          {conversations?.length === 0 && <li className="px-2 text-sm text-muted">ยังไม่มีการสนทนา</li>}
          {conversations?.map((c) => (
            <li key={c.id} className="flex items-center gap-1">
              <button type="button" aria-current={c.id === activeId ? "true" : undefined} onClick={() => void openConversation(c.id)}
                className={`min-w-0 flex-1 truncate rounded-sm px-2 py-2 text-left text-sm ${c.id === activeId ? "bg-accent-weak font-medium text-fg" : "text-muted hover:bg-surface-2 hover:text-fg"}`}>
                {c.title}
              </button>
              <button type="button" aria-label={`เปลี่ยนชื่อ ${c.title}`} onClick={() => setDialog({ kind: "rename", conv: c })}
                className="rounded-sm px-1.5 py-1 text-xs text-muted hover:text-fg">เปลี่ยนชื่อ</button>
              <button type="button" aria-label={`ลบ ${c.title}`} onClick={() => setDialog({ kind: "delete", conv: c })}
                className="rounded-sm px-1.5 py-1 text-xs text-bad hover:opacity-80">ลบ</button>
            </li>
          ))}
        </ul>
      </aside>

      <section aria-labelledby="chat-heading" className="flex min-h-0 min-w-0 flex-1 flex-col gap-3 rounded-md border border-line bg-surface p-3 md:p-4">
        <div className="flex flex-wrap items-end gap-3">
          <button ref={toggleRef} type="button" aria-expanded={sidebarOpen} aria-controls="chat-sidebar"
            onClick={() => setSidebarOpen((open) => !open)}
            className="min-h-10 rounded-sm border border-line bg-surface px-3 text-sm text-fg md:hidden">
            การสนทนา
          </button>
          <h1 id="chat-heading" className="mr-auto min-w-0 truncate text-xl font-semibold">{activeConv?.title ?? "แชท"}</h1>
          <ModelPicker id={pickerId} models={models} value={model} onChange={setModel} />
        </div>

        {noneConfigured && (
          <p className="rounded-sm bg-warn-bg px-3 py-2 text-sm text-warn">
            ยังไม่มีโมเดลที่ตั้งค่า API key บน server — ตั้งค่าก่อนจึงจะส่งข้อความได้
          </p>
        )}

        {pageError ? (
          <ErrorState title={errorTitle(pageError)} detail={errorDetail(pageError)}
            action={{ label: "ลองอีกครั้ง", onClick: () => void loadAll() }} />
        ) : (
          <div ref={threadRef} role="log" aria-live="polite" aria-label="ข้อความในการสนทนา"
            className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-1">
            {!activeId && <p className="m-auto text-center text-sm text-muted">เลือกการสนทนาจากรายการ หรือกด "แชทใหม่" เพื่อเริ่มต้น</p>}
            {activeId && messages.length === 0 && !streaming && (
              <p className="m-auto text-center text-sm text-muted">พิมพ์ข้อความด้านล่างเพื่อเริ่มสนทนา</p>
            )}
            {messages.map((m, i) => (
              <MessageItem key={m.id} message={m} streaming={streaming && m.role === "assistant" && i === messages.length - 1} />
            ))}
          </div>
        )}

        {sendError && (
          <ErrorState title={errorTitle(sendError.error)} detail={errorDetail(sendError.error)}
            action={sendError.error.retryable ? { label: "ลองส่งอีกครั้ง", onClick: retry } : undefined} />
        )}

        <form onSubmit={(e) => { e.preventDefault(); submit(); }} className="flex flex-col gap-2 sm:flex-row sm:items-end">
          <label htmlFor={inputId} className="sr-only">ข้อความ</label>
          <textarea id={inputId} ref={composerRef} value={input} onChange={(e) => setInput(e.target.value)}
            onKeyDown={onComposerKey} disabled={!activeId} rows={2}
            placeholder="พิมพ์ข้อความ (Enter ส่ง, Shift+Enter ขึ้นบรรทัดใหม่)"
            className="min-h-12 w-full flex-1 resize-y rounded-sm border border-line bg-surface px-3 py-2 text-sm text-fg placeholder:text-muted disabled:opacity-60" />
          <div className="flex gap-2">
            {streaming && <Button variant="danger" onClick={stop}>หยุด</Button>}
            <Button variant="primary" type="submit" disabled={!activeId || !input.trim() || streaming}>ส่ง</Button>
          </div>
        </form>
      </section>

      {dialog?.kind === "rename" && (
        <RenameDialog conv={dialog.conv} onCancel={() => setDialog(null)} onSave={(title) => void saveRename(dialog.conv, title)} />
      )}
      {dialog?.kind === "delete" && (
        <DeleteDialog conv={dialog.conv} onCancel={() => setDialog(null)} onConfirm={() => void removeConversation(dialog.conv)} />
      )}
    </div>
  );
}
