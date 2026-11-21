// Main job: send a prompt, watch the answer stream in, keep partial output when something breaks.
import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { ApiError, api, streamRun, type ModelList, type RunDone, type SettingsView } from "../api";
import { Badge, Button, Card, ErrorState, Select, Textarea } from "../components/ui";
import { navigate } from "../router";
import { errorDetail, errorTitle, isKeyProblem } from "./errors";

type Phase = "idle" | "streaming" | "done" | "error";
type Speed = "fast" | "balanced" | "detailed";

const SPEEDS: { value: Speed; label: string }[] = [
  { value: "fast", label: "เร็ว (คำตอบสั้น)" },
  { value: "balanced", label: "สมดุล" },
  { value: "detailed", label: "ละเอียด (ยาวสุดของระบบ)" },
];

/** Speed here means the answer length cap; it does not change how fast the model itself runs. */
function capFor(speed: Speed, max: number): number {
  if (speed === "fast") return Math.min(256, max);
  if (speed === "balanced") return Math.min(1024, max);
  return max;
}

export function Workbench({ onAuthLost }: { onAuthLost: () => void }) {
  const [prompt, setPrompt] = useState("");
  const [output, setOutput] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<ApiError | null>(null);
  const [done, setDone] = useState<RunDone | null>(null);
  const [settings, setSettings] = useState<SettingsView | null>(null);
  const [models, setModels] = useState<ModelList | null>(null);
  const [modelsFailed, setModelsFailed] = useState(false);
  const [model, setModel] = useState("");
  const [speed, setSpeed] = useState<Speed>("balanced");
  const abort = useRef<AbortController | null>(null);
  const maxChars = settings?.limits.max_input_chars ?? 8000;
  const tooLong = prompt.length > maxChars;

  const refresh = useCallback(() => {
    api<SettingsView>("/api/settings").then(setSettings).catch(() => undefined);
  }, []);
  useEffect(refresh, [refresh]);
  useEffect(() => {
    api<ModelList>("/api/models").then(setModels).catch(() => setModelsFailed(true));
  }, []);
  useEffect(() => () => abort.current?.abort(), []);

  const run = useCallback(async (text: string) => {
    abort.current = new AbortController();
    setPhase("streaming"); setOutput(""); setError(null); setDone(null);
    try {
      const cap = capFor(speed, settings?.limits.max_output_tokens ?? 1024);
      const result = await streamRun(text, { onDelta: (d) => setOutput((o) => o + d), signal: abort.current.signal },
        { model: model || undefined, maxOutputTokens: cap });
      setDone(result); setPhase("done");
    } catch (err) {
      const e = err instanceof ApiError ? err : new ApiError("unknown", "เกิดข้อผิดพลาด", false);
      if (e.type === "auth") onAuthLost();
      setError(e); setPhase("error");
    } finally {
      abort.current = null;
      refresh();
    }
  }, [onAuthLost, refresh, model, speed, settings]);

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    if (phase !== "streaming" && prompt.trim() && !tooLong) void run(prompt);
  };
  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) submit();
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-2xl font-semibold">หน้าทำงาน</h1>
        {settings && (
          <p className="text-sm text-muted">
            โมเดล <span className="mono">{settings.model}</span> · token เหลือวันนี้{" "}
            <span className="tabular">{settings.quota.remaining.toLocaleString("th-TH")}</span>
          </p>
        )}
      </div>
      <Card>
        <form onSubmit={submit} className="flex flex-col gap-3">
          <Textarea label="คำสั่งถึงโมเดล" rows={5} value={prompt} onChange={(e) => setPrompt(e.target.value)} onKeyDown={onKeyDown}
            hint={`${prompt.length.toLocaleString("th-TH")} / ${maxChars.toLocaleString("th-TH")} ตัวอักษร · Ctrl+Enter เพื่อส่ง`}
            error={tooLong ? `ยาวเกิน ${maxChars.toLocaleString("th-TH")} ตัวอักษร — ย่อให้สั้นลง` : undefined} />
          <div className="grid gap-3 sm:grid-cols-2">
            <Select label="โมเดล" value={model} onChange={(e) => setModel(e.target.value)}
              hint={modelsFailed ? "โหลดรายชื่อโมเดลไม่ได้ ใช้ค่าเริ่มต้นของระบบ" : "รายการจากเซิร์ฟเวอร์จริง"}
              options={[{ value: "", label: `ค่าเริ่มต้น (${models?.current ?? settings?.model ?? "…"})` },
                ...(models?.available ?? []).filter((m) => m !== models?.current).map((m) => ({ value: m, label: m }))]} />
            <Select label="ความเร็วคำตอบ" value={speed} onChange={(e) => setSpeed(e.target.value as Speed)}
              options={SPEEDS} hint="จำกัดความยาวคำตอบ" />
          </div>
          <div className="flex flex-wrap gap-2">
            <Button type="submit" variant="primary" loading={phase === "streaming"} disabled={!prompt.trim() || tooLong}>ส่ง</Button>
            {phase === "streaming" && <Button onClick={() => abort.current?.abort()}>หยุด</Button>}
          </div>
        </form>
      </Card>
      <Output output={output} phase={phase} done={done} error={error} />
      {error && error.type !== "auth" && (
        <ErrorState title={errorTitle(error)} detail={errorDetail(error)}
          action={isKeyProblem(error) ? { label: "ไปตั้งค่า API key", onClick: () => navigate("settings") }
            : error.retryable ? { label: "ลองใหม่", onClick: () => void run(prompt) } : undefined} />
      )}
    </div>
  );
}

function Output({ output, phase, done, error }: { output: string; phase: Phase; done: RunDone | null; error: ApiError | null }) {
  if (phase === "idle") return null;
  const partial = phase === "error" && !!output;
  return (
    <Card title="คำตอบ" actions={
      phase === "done" && done ? <Badge status="ok">สำเร็จ · <span className="tabular">{done.tokens_out} token · {done.latency_ms} ms</span></Badge>
        : partial ? <Badge status="warn">ได้คำตอบบางส่วน</Badge>
        : phase === "streaming" ? <Badge status="neutral">กำลังรับคำตอบ</Badge>
        : error ? <Badge status="bad">ไม่สำเร็จ</Badge> : null
    }>
      <div aria-live="polite" aria-busy={phase === "streaming"} className="min-h-12 whitespace-pre-wrap break-words text-sm text-fg">
        {output || (phase === "streaming" ? <span className="text-muted">กำลังรอคำตอบแรก…</span> : <span className="text-muted">ยังไม่มีข้อความ</span>)}
      </div>
    </Card>
  );
}
