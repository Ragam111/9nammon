// Showcase: every component, rendered once in a light panel and once in a dark panel.
import { useState } from "react";
import {
  Badge, Button, Card, CodeBlock, Dialog, ErrorState, Input, Select, Skeleton, Table, Tabs,
  ToastProvider, useToast, type Column,
} from "./components/ui";

type Run = { id: string; model: string; status: string; tokens: number; latency: number };

const RUNS: Run[] = [
  { id: "run_8f21", model: "model-small", status: "สำเร็จ", tokens: 1840, latency: 920 },
  { id: "run_8f22", model: "model-large", status: "ล้มเหลว", tokens: 0, latency: 30000 },
  { id: "run_8f23", model: "model-small", status: "สำเร็จ", tokens: 512, latency: 410 },
];

const COLUMNS: Column<Run>[] = [
  { key: "id", label: "ID", mono: true },
  { key: "model", label: "โมเดล", sortable: true },
  { key: "status", label: "สถานะ" },
  { key: "tokens", label: "token", numeric: true, sortable: true },
  { key: "latency", label: "latency (ms)", numeric: true, sortable: true },
];

function Panel({ theme }: { theme: "light" | "dark" }) {
  const toast = useToast();
  const [dialog, setDialog] = useState(false);
  const [key, setKey] = useState("");
  const [loading, setLoading] = useState(false);
  const keyError = key && !key.startsWith("sk-") ? "API key ต้องขึ้นต้นด้วย sk-" : undefined;
  const fakeSave = () => {
    setLoading(true);
    window.setTimeout(() => { setLoading(false); toast.show("ok", "บันทึก API key แล้ว (แสดงเฉพาะ 4 ตัวท้าย)"); }, 900);
  };
  const title = theme === "light" ? "ธีมสว่าง" : "ธีมมืด";

  return (
    <div data-theme={theme} className="flex min-w-0 flex-col gap-4 rounded-md border border-line bg-bg p-4 text-fg">
      <h2 className="text-xl font-semibold">{title}</h2>

      <Card title="Button">
        <div className="flex flex-wrap gap-2">
          <Button variant="primary">บันทึก</Button>
          <Button variant="secondary">ยกเลิก</Button>
          <Button variant="danger" onClick={() => setDialog(true)}>ลบประวัติ</Button>
          <Button variant="ghost">รายละเอียด</Button>
          <Button variant="primary" loading>กำลังบันทึก</Button>
        </div>
      </Card>

      <Card title="Input และ Select">
        <div className="grid gap-3 sm:grid-cols-2">
          <Input label="API key" type="password" autoComplete="off" placeholder="sk-..." value={key}
            onChange={(e) => setKey(e.target.value)} error={keyError} hint="เก็บที่ server เท่านั้น" />
          <Select label="โมเดล" options={[{ value: "small", label: "model-small" }, { value: "large", label: "model-large" }]} />
        </div>
        <div className="mt-3">
          <Button variant="primary" loading={loading} disabled={!key || !!keyError} onClick={fakeSave}>ตั้งค่า key</Button>
        </div>
      </Card>

      <Card title="Badge สถานะ">
        <div className="flex flex-wrap gap-2">
          <Badge status="ok">สำเร็จ</Badge>
          <Badge status="warn">เตือน: quota เหลือ 10%</Badge>
          <Badge status="bad">ล้มเหลว: timeout</Badge>
          <Badge status="neutral">รอคิว</Badge>
        </div>
      </Card>

      <Card title="Tabs">
        <Tabs label={`ตัวอย่างแท็บ (${title})`} tabs={[
          { id: "output", label: "ผลลัพธ์", content: <p className="text-sm">ผลลัพธ์ล่าสุดจากโมเดล</p> },
          { id: "log", label: "Log", content: <CodeBlock label="log" code={'{"request_id":"req_42","latency_ms":920,"error":null}'} /> },
          { id: "loading", label: "กำลังโหลด", content: <div className="flex flex-col gap-2"><Skeleton /><Skeleton className="h-4 w-2/3" /></div> },
        ]} />
      </Card>

      <Card title="Table">
        <Table caption="ประวัติการเรียกโมเดล" columns={COLUMNS} rows={RUNS} rowKey={(r) => r.id} empty="ยังไม่มีประวัติ" />
        <div className="mt-3">
          <Table caption="ประวัติว่าง" columns={COLUMNS} rows={[]} rowKey={(r) => r.id} empty="ยังไม่มีประวัติ — ลองเรียกโมเดลครั้งแรกจากหน้าหลัก" />
        </div>
      </Card>

      <Card title="Code block">
        <CodeBlock label="ตัวอย่าง curl" code={"curl -X POST http://127.0.0.1:8000/api/run \\\n  -H 'Content-Type: application/json' -d '{\"prompt\":\"hi\"}'"} />
      </Card>

      <Card title="Toast">
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => toast.show("ok", "บันทึกแล้ว")}>แสดง toast สำเร็จ</Button>
          <Button onClick={() => toast.show("bad", "เรียกโมเดลไม่สำเร็จ: quota เต็ม")}>แสดง toast ล้มเหลว</Button>
        </div>
      </Card>

      <ErrorState title="เน็ตหลุดระหว่างรับคำตอบ" detail="แสดงผลที่ได้รับมาแล้วด้านบน ส่วนที่เหลือยังไม่มา"
        action={{ label: "ลองใหม่", onClick: () => toast.show("neutral", "กำลังลองใหม่...") }} />

      <Dialog open={dialog} onClose={() => setDialog(false)} title="ลบประวัติทั้งหมด?"
        actions={<>
          <Button onClick={() => setDialog(false)}>ยกเลิก</Button>
          <Button variant="danger" onClick={() => { setDialog(false); toast.show("ok", "ลบประวัติแล้ว"); }}>ลบ</Button>
        </>}>
        การลบย้อนกลับไม่ได้ ประวัติ 3 รายการจะหายไป
      </Dialog>
    </div>
  );
}

export function Showcase() {
  return (
    <ToastProvider>
      <main className="mx-auto flex max-w-7xl flex-col gap-4 p-4">
        <header>
          <h1 className="text-2xl font-semibold">Component showcase</h1>
          <p className="text-sm text-muted">ทุก component ในสองธีม ใช้โทเคนจาก tokens.css เท่านั้น</p>
        </header>
        <div className="grid gap-4 lg:grid-cols-2">
          <Panel theme="light" />
          <Panel theme="dark" />
        </div>
      </main>
    </ToastProvider>
  );
}
