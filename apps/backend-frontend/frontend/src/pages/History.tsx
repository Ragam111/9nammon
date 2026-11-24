// History: search, filter by status, view detail, delete (with confirmation).
import { useCallback, useEffect, useState } from "react";
import { ApiError, api, json, type HistoryPage, type RunDetail, type RunStatus, type RunSummary } from "../api";
import {
  Badge, Button, Card, CodeBlock, Dialog, ErrorState, Input, Select, Skeleton, Table, useToast, type Column, type Status,
} from "../components/ui";
import { errorDetail, errorTitle } from "./errors";

const PAGE = 20;
const STATUS_BADGE: Record<RunStatus, [Status, string]> = {
  ok: ["ok", "สำเร็จ"], partial: ["warn", "บางส่วน"], error: ["bad", "ล้มเหลว"],
};

const formatTime = (iso: string) =>
  new Date(iso).toLocaleString("th-TH", { dateStyle: "medium", timeStyle: "short" });

function useDebounced(value: string, ms: number): string {
  const [v, setV] = useState(value);
  useEffect(() => { const t = window.setTimeout(() => setV(value), ms); return () => window.clearTimeout(t); }, [value, ms]);
  return v;
}

export function History({ onAuthLost }: { onAuthLost: () => void }) {
  const toast = useToast();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState<HistoryPage | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [confirm, setConfirm] = useState(false);
  const query = useDebounced(q, 300);

  const load = useCallback(async (offset = 0) => {
    setError(null);
    const params = new URLSearchParams({ q: query, status, limit: String(PAGE), offset: String(offset) });
    try {
      const next = await api<HistoryPage>(`/api/history?${params}`);
      setPage((prev) => (offset && prev ? { items: [...prev.items, ...next.items], total: next.total } : next));
    } catch (err) {
      const e = err instanceof ApiError ? err : new ApiError("unknown", "โหลดประวัติไม่สำเร็จ", true);
      if (e.type === "auth") onAuthLost();
      setError(e);
    }
  }, [query, status, onAuthLost]);
  useEffect(() => { void load(0); }, [load]);

  const open = async (id: string) => {
    try { setDetail(await api<RunDetail>(`/api/history/${encodeURIComponent(id)}`)); }
    catch (err) { toast.show("bad", err instanceof ApiError ? err.message : "เปิดรายละเอียดไม่สำเร็จ"); }
  };

  const remove = async () => {
    if (!detail) return;
    setConfirm(false);
    try {
      await api(`/api/history/${encodeURIComponent(detail.id)}`, json("DELETE"));
      toast.show("ok", "ลบประวัติแล้ว");
      setDetail(null);
      void load(0);
    } catch (err) {
      toast.show("bad", err instanceof ApiError ? err.message : "ลบไม่สำเร็จ");
    }
  };

  const columns: Column<RunSummary>[] = [
    { key: "created_at", label: "เวลา", sortable: true, render: (r) => <span className="tabular whitespace-nowrap">{formatTime(r.created_at)}</span> },
    { key: "prompt_preview", label: "คำสั่ง", render: (r) => <span className="line-clamp-2 break-words">{r.prompt_preview}</span> },
    { key: "status", label: "สถานะ", render: (r) => <Badge status={STATUS_BADGE[r.status][0]}>{STATUS_BADGE[r.status][1]}</Badge> },
    { key: "tokens_out", label: "token", numeric: true, sortable: true, render: (r) => r.tokens_in + r.tokens_out },
    { key: "id", label: "", render: (r) => <Button variant="ghost" onClick={() => void open(r.id)} aria-label={`ดูรายละเอียด ${r.id}`}>ดู</Button> },
  ];
  const filtered = Boolean(query || status);

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-semibold">ประวัติ</h1>
      <div className="grid gap-3 sm:grid-cols-[1fr_12rem]">
        <Input label="ค้นหา" type="search" placeholder="ค้นในคำสั่งหรือคำตอบ" value={q} onChange={(e) => setQ(e.target.value)} />
        <Select label="สถานะ" value={status} onChange={(e) => setStatus(e.target.value)} options={[
          { value: "", label: "ทั้งหมด" }, { value: "ok", label: "สำเร็จ" }, { value: "partial", label: "บางส่วน" }, { value: "error", label: "ล้มเหลว" },
        ]} />
      </div>
      {error && <ErrorState title={errorTitle(error)} detail={errorDetail(error)} action={{ label: "ลองใหม่", onClick: () => void load(0) }} />}
      {!page && !error && <div className="flex flex-col gap-2"><Skeleton className="h-8 w-full" /><Skeleton className="h-8 w-full" /></div>}
      {page && (
        <>
          <p className="text-sm text-muted">ทั้งหมด <span className="tabular">{page.total}</span> รายการ</p>
          <Table caption="ประวัติการเรียกโมเดล" columns={columns} rows={page.items} rowKey={(r) => r.id}
            empty={filtered ? "ไม่พบรายการที่ตรงกับตัวกรอง" : "ยังไม่มีประวัติ — ไปหน้าทำงานเพื่อเรียกโมเดลครั้งแรก"} />
          {page.items.length < page.total && <Button onClick={() => void load(page.items.length)}>โหลดเพิ่ม</Button>}
        </>
      )}
      {detail && <DetailCard run={detail} onClose={() => setDetail(null)} onDelete={() => setConfirm(true)} />}
      <Dialog open={confirm} onClose={() => setConfirm(false)} title="ลบประวัตินี้?"
        actions={<><Button onClick={() => setConfirm(false)}>ยกเลิก</Button><Button variant="danger" onClick={() => void remove()}>ลบ</Button></>}>
        ลบแล้วย้อนกลับไม่ได้
      </Dialog>
    </div>
  );
}

function DetailCard({ run, onClose, onDelete }: { run: RunDetail; onClose: () => void; onDelete: () => void }) {
  const [s, label] = STATUS_BADGE[run.status];
  return (
    <Card title="รายละเอียด" actions={<div className="flex gap-2"><Button variant="danger" onClick={onDelete}>ลบ</Button><Button onClick={onClose}>ปิด</Button></div>}>
      <dl className="mb-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
        <dt className="text-muted">ID</dt><dd className="mono">{run.id}</dd>
        <dt className="text-muted">สถานะ</dt><dd><Badge status={s}>{label}{run.error_type ? ` · ${run.error_type}` : ""}</Badge></dd>
        <dt className="text-muted">เวลา</dt><dd className="tabular">{formatTime(run.created_at)} · {run.latency_ms} ms</dd>
        <dt className="text-muted">token</dt><dd className="tabular">เข้า {run.tokens_in} · ออก {run.tokens_out}</dd>
      </dl>
      <h4 className="mb-1 text-sm font-medium">คำสั่ง</h4>
      <p className="mb-3 whitespace-pre-wrap break-words text-sm">{run.prompt}</p>
      <h4 className="mb-1 text-sm font-medium">คำตอบ</h4>
      {run.output ? <CodeBlock label="คำตอบ" code={run.output} /> : <p className="text-sm text-muted">ไม่มีคำตอบ</p>}
    </Card>
  );
}
