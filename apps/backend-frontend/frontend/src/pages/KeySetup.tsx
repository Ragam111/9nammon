// Set the model API key through the server. The browser only ever sees the last 4 characters.
import { useState, type FormEvent } from "react";
import { ApiError, api, json, type KeyStatus } from "../api";
import { Badge, Button, Input, useToast } from "../components/ui";

export function KeyStatusLine({ status }: { status: KeyStatus }) {
  if (!status.configured) return <Badge status="warn">ยังไม่ได้ตั้งค่า API key</Badge>;
  const source = status.source === "env" ? "จาก .env ของ server" : "ตั้งผ่านหน้านี้";
  return (
    <span className="flex flex-wrap items-center gap-2">
      <Badge status="ok">ตั้งค่าแล้ว</Badge>
      <span className="mono text-sm" aria-hidden="true">••••{status.last4}</span>
      <span className="sr-only">API key ลงท้ายด้วย {status.last4}</span>
      <span className="text-sm text-muted">{source}</span>
    </span>
  );
}

/** How to get a key. Buying happens on the provider's own site; this app never takes payment. */
export function GetKeySteps() {
  return (
    <section aria-labelledby="get-key-title" className="flex flex-col gap-2 text-sm">
      <h3 id="get-key-title" className="font-semibold">วิธีได้ API key</h3>
      <ol className="flex list-decimal flex-col gap-1 pl-5 text-muted">
        <li>เข้าเว็บของผู้ให้บริการโมเดลที่ใช้ (ดูชื่อ host ใน MODEL_BASE_URL ของ server)</li>
        <li>สมัครหรือเติมเครดิตที่หน้าบัญชีของผู้ให้บริการนั้นเอง การซื้อทำบนเว็บของผู้ให้บริการ ไม่ได้ทำในแอปนี้</li>
        <li>สร้าง API key ในหน้า API keys แล้วคัดลอกมาวางในช่องด้านล่าง (เฉพาะผู้ดูแลระบบ)</li>
      </ol>
      <p className="text-muted">อย่าส่ง API key ในแชทหรืออีเมล ถ้าหลุดให้เพิกถอนที่หน้าผู้ให้บริการทันที</p>
    </section>
  );
}

type Props = { status: KeyStatus; isAdmin: boolean; onChange: (s: KeyStatus) => void };

export function KeySetup({ status, isAdmin, onChange }: Props) {
  const toast = useToast();
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const invalid = key.length > 0 && (key.length < 8 || /\s/.test(key));

  const save = async (e: FormEvent) => {
    e.preventDefault();
    if (!key || invalid) return;
    setBusy(true);
    setError("");
    try {
      const next = await api<KeyStatus>("/api/settings/key", json("PUT", { api_key: key }));
      setKey(""); // drop the full key from memory as soon as the server has it
      onChange(next);
      toast.show("ok", `บันทึก API key แล้ว (ลงท้าย ${next.last4})`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "บันทึกไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  };

  const clear = async () => {
    try {
      onChange(await api<KeyStatus>("/api/settings/key", json("DELETE")));
      toast.show("ok", "ลบ API key ที่ตั้งไว้แล้ว");
    } catch (err) {
      toast.show("bad", err instanceof ApiError ? err.message : "ลบไม่สำเร็จ");
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <KeyStatusLine status={status} />
      {!status.configured && <GetKeySteps />}
      {!isAdmin &&<p className="text-sm text-muted">เฉพาะผู้ดูแลระบบที่ตั้งหรือเปลี่ยน API key ได้</p>}
      {isAdmin && status.source !== "env" && (
        <form onSubmit={save} className="flex flex-col gap-2" noValidate>
          <Input label="API key ใหม่" type="password" autoComplete="off" spellCheck={false} value={key}
            onChange={(e) => setKey(e.target.value)}
            error={invalid ? "API key ต้องยาวอย่างน้อย 8 ตัวและไม่มีช่องว่าง" : error || undefined}
            hint="ส่งไปเก็บที่ server เท่านั้น หน้านี้จะแสดงแค่ 4 ตัวท้าย" />
          <div className="flex flex-wrap gap-2">
            <Button type="submit" variant="primary" loading={busy} disabled={!key || invalid}>บันทึก key</Button>
            {status.source === "stored" && <Button variant="danger" onClick={clear}>ลบ key ที่ตั้งไว้</Button>}
          </div>
        </form>
      )}
    </div>
  );
}
