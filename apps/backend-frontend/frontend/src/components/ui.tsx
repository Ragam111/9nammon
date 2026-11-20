// Component library for backend-frontend. Every color, radius and space comes from the design
// tokens (via the Tailwind theme mapping in index.css). See ../../../DESIGN.md.
import {
  createContext, useCallback, useContext, useEffect, useId, useMemo, useRef, useState,
  type ButtonHTMLAttributes, type InputHTMLAttributes, type KeyboardEvent, type ReactNode, type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
import { CheckIcon, ErrorIcon, InfoIcon, SortIcon, WarnIcon } from "./icons";

/* ---------- Button ---------- */

type ButtonVariant = "primary" | "secondary" | "danger" | "ghost";

const buttonVariants: Record<ButtonVariant, string> = {
  primary: "bg-accent text-accent-fg border-accent hover:opacity-90",
  secondary: "bg-surface text-fg border-line hover:bg-surface-2",
  danger: "bg-bad text-surface border-bad hover:opacity-90",
  ghost: "bg-transparent text-fg border-transparent hover:bg-surface-2",
};

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  loading?: boolean;
};

export function Button({ variant = "secondary", loading = false, disabled, children, className = "", type = "button", ...rest }: ButtonProps) {
  return (
    <button
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={`inline-flex min-h-10 items-center justify-center gap-2 rounded-sm border px-4 text-sm font-medium
        transition-[background-color,opacity] duration-(--motion-fast) disabled:cursor-not-allowed disabled:opacity-50
        ${buttonVariants[variant]} ${className}`}
      {...rest}
    >
      {loading && <Spinner />}
      <span>{children}</span>
    </button>
  );
}

function Spinner() {
  return (
    <span
      aria-hidden="true"
      className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-r-transparent"
    />
  );
}

/* ---------- Field wrapper (label, hint, error) ---------- */

type FieldProps = { id: string; label: string; hint?: string; error?: string; children: ReactNode };

function Field({ id, label, hint, error, children }: FieldProps) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-sm font-medium text-fg">{label}</label>
      {children}
      {error ? (
        <p id={`${id}-msg`} className="flex items-center gap-1 text-sm text-bad">
          <ErrorIcon /> {error}
        </p>
      ) : hint ? (
        <p id={`${id}-msg`} className="text-sm text-muted">{hint}</p>
      ) : null}
    </div>
  );
}

const controlBase = `min-h-10 w-full rounded-sm border bg-surface px-3 text-sm text-fg placeholder:text-muted
  aria-invalid:border-bad`;

/* ---------- Input ---------- */

type InputProps = InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: string; error?: string };

export function Input({ label, hint, error, id, className = "", ...rest }: InputProps) {
  const autoId = useId();
  const inputId = id ?? autoId;
  return (
    <Field id={inputId} label={label} hint={hint} error={error}>
      <input
        id={inputId}
        aria-invalid={error ? true : undefined}
        aria-describedby={error || hint ? `${inputId}-msg` : undefined}
        className={`${controlBase} border-line ${className}`}
        {...rest}
      />
    </Field>
  );
}

/* ---------- Textarea ---------- */

type TextareaProps = TextareaHTMLAttributes<HTMLTextAreaElement> & { label: string; hint?: string; error?: string };

export function Textarea({ label, hint, error, id, className = "", ...rest }: TextareaProps) {
  const autoId = useId();
  const areaId = id ?? autoId;
  return (
    <Field id={areaId} label={label} hint={hint} error={error}>
      <textarea
        id={areaId}
        aria-invalid={error ? true : undefined}
        aria-describedby={error || hint ? `${areaId}-msg` : undefined}
        className={`${controlBase} border-line py-2 ${className}`}
        {...rest}
      />
    </Field>
  );
}

/* ---------- Select ---------- */

type SelectProps = SelectHTMLAttributes<HTMLSelectElement> & {
  label: string;
  options: { value: string; label: string }[];
  hint?: string;
  error?: string;
};

export function Select({ label, options, hint, error, id, className = "", ...rest }: SelectProps) {
  const autoId = useId();
  const selectId = id ?? autoId;
  return (
    <Field id={selectId} label={label} hint={hint} error={error}>
      <select
        id={selectId}
        aria-invalid={error ? true : undefined}
        aria-describedby={error || hint ? `${selectId}-msg` : undefined}
        className={`${controlBase} border-line ${className}`}
        {...rest}
      >
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </Field>
  );
}

/* ---------- Badge (status always has icon + text) ---------- */

export type Status = "ok" | "warn" | "bad" | "neutral";

const badgeStyles: Record<Status, string> = {
  ok: "bg-ok-bg text-ok",
  warn: "bg-warn-bg text-warn",
  bad: "bg-bad-bg text-bad",
  neutral: "bg-surface-2 text-muted",
};

const statusIcon: Record<Status, ReactNode> = {
  ok: <CheckIcon />, warn: <WarnIcon />, bad: <ErrorIcon />, neutral: <InfoIcon />,
};

export function Badge({ status, children }: { status: Status; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-sm px-2 py-0.5 text-xs font-medium ${badgeStyles[status]}`}>
      {statusIcon[status]}
      {children}
    </span>
  );
}

/* ---------- Card ---------- */

export function Card({ title, actions, children }: { title?: string; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-md border border-line bg-surface p-4 shadow-1">
      {(title || actions) && (
        <header className="mb-3 flex flex-wrap items-center justify-between gap-2">
          {title && <h3 className="text-base font-semibold text-fg">{title}</h3>}
          {actions}
        </header>
      )}
      {children}
    </section>
  );
}

/* ---------- Dialog (native <dialog>: focus trap and Escape handled by the browser) ---------- */

type DialogProps = { open: boolean; onClose: () => void; title: string; children: ReactNode; actions?: ReactNode };

export function Dialog({ open, onClose, title, children, actions }: DialogProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) el.showModal();
    if (!open && el.open) el.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onClose={onClose}
      onCancel={onClose}
      className="m-auto w-[min(32rem,calc(100vw-2rem))] rounded-md border border-line bg-surface p-0 text-fg shadow-1 backdrop:bg-black/40"
    >
      <div className="p-4">
        <h2 id={titleId} className="mb-2 text-lg font-semibold">{title}</h2>
        <div className="text-sm text-fg">{children}</div>
      </div>
      <footer className="flex flex-wrap justify-end gap-2 border-t border-line p-3">
        {actions ?? <Button onClick={onClose}>ปิด</Button>}
      </footer>
    </dialog>
  );
}

/* ---------- Toast ---------- */

type ToastItem = { id: number; status: Status; text: string };
type ToastApi = { show: (status: Status, text: string) => void };

const ToastContext = createContext<ToastApi | null>(null);
const TOAST_MS = 4000;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(1);
  const dismiss = useCallback((id: number) => setItems((all) => all.filter((t) => t.id !== id)), []);
  const show = useCallback((status: Status, text: string) => {
    const id = nextId.current++;
    setItems((all) => [...all, { id, status, text }]);
    window.setTimeout(() => dismiss(id), TOAST_MS);
  }, [dismiss]);
  const api = useMemo(() => ({ show }), [show]);
  return (
    <ToastContext.Provider value={api}>
      {children}
      <div role="status" aria-live="polite" className="fixed bottom-4 right-4 left-4 z-50 flex flex-col items-end gap-2 sm:left-auto">
        {items.map((t) => (
          <div key={t.id} className={`flex w-full max-w-sm items-start gap-2 rounded-md border border-line px-3 py-2 text-sm shadow-1 ${badgeStyles[t.status]}`}>
            {statusIcon[t.status]}
            <span className="flex-1 text-fg">{t.text}</span>
            <button type="button" onClick={() => dismiss(t.id)} aria-label="ปิดการแจ้งเตือน" className="rounded-sm px-1 text-muted hover:text-fg">×</button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const api = useContext(ToastContext);
  if (!api) throw new Error("useToast must be used inside <ToastProvider>");
  return api;
}

/* ---------- Tabs (arrow keys, Home, End) ---------- */

type Tab = { id: string; label: string; content: ReactNode };

export function Tabs({ tabs, label }: { tabs: Tab[]; label: string }) {
  const [active, setActive] = useState(tabs[0]?.id ?? "");
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});
  const baseId = useId();
  const move = (index: number) => {
    const tab = tabs[(index + tabs.length) % tabs.length];
    setActive(tab.id);
    refs.current[tab.id]?.focus();
  };
  const onKey = (e: KeyboardEvent, index: number) => {
    const keys: Record<string, number> = { ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: tabs.length - 1 };
    if (e.key in keys) { e.preventDefault(); move(keys[e.key]); }
  };
  return (
    <div>
      <div role="tablist" aria-label={label} className="flex gap-1 overflow-x-auto border-b border-line">
        {tabs.map((t, i) => (
          <button
            key={t.id}
            ref={(el) => { refs.current[t.id] = el; }}
            role="tab"
            id={`${baseId}-tab-${t.id}`}
            aria-selected={active === t.id}
            aria-controls={`${baseId}-panel-${t.id}`}
            tabIndex={active === t.id ? 0 : -1}
            onClick={() => setActive(t.id)}
            onKeyDown={(e) => onKey(e, i)}
            className={`-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm ${active === t.id ? "border-accent text-fg font-medium" : "border-transparent text-muted hover:text-fg"}`}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tabs.map((t) => (
        <div key={t.id} role="tabpanel" id={`${baseId}-panel-${t.id}`} aria-labelledby={`${baseId}-tab-${t.id}`} hidden={active !== t.id} className="pt-3">
          {t.content}
        </div>
      ))}
    </div>
  );
}

/* ---------- Table (sortable columns, empty state) ---------- */

export type Column<T> = {
  key: keyof T & string; label: string; numeric?: boolean; mono?: boolean; sortable?: boolean;
  render?: (row: T) => ReactNode;
};

type TableProps<T> = { caption: string; columns: Column<T>[]; rows: T[]; rowKey: (row: T) => string; empty: ReactNode };

export function Table<T extends Record<string, unknown>>({ caption, columns, rows, rowKey, empty }: TableProps<T>) {
  const [sort, setSort] = useState<{ key: keyof T & string; dir: "asc" | "desc" } | null>(null);
  const sorted = useMemo(() => {
    if (!sort) return rows;
    const factor = sort.dir === "asc" ? 1 : -1;
    const val = (r: T) => r[sort.key] as string | number;
    return [...rows].sort((a, b) => (val(a) > val(b) ? factor : val(a) < val(b) ? -factor : 0));
  }, [rows, sort]);
  const toggle = (key: keyof T & string) =>
    setSort((s) => (s?.key === key ? { key, dir: s.dir === "asc" ? "desc" : "asc" } : { key, dir: "asc" }));

  if (rows.length === 0) return <div className="rounded-md border border-dashed border-line p-6 text-center text-sm text-muted">{empty}</div>;
  return (
    <div className="overflow-x-auto rounded-md border border-line">
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="bg-surface-2">
          <tr>
            {columns.map((c) => {
              const dir = sort?.key === c.key ? sort.dir : "none";
              const ariaSort = dir === "asc" ? "ascending" : dir === "desc" ? "descending" : "none";
              return (
                <th key={c.key} scope="col" aria-sort={c.sortable ? ariaSort : undefined}
                  className={`px-3 py-2 font-medium text-muted ${c.numeric ? "text-right" : "text-left"}`}>
                  {c.sortable ? (
                    <button type="button" onClick={() => toggle(c.key)} className="inline-flex items-center gap-1 rounded-sm hover:text-fg">
                      {c.label} <SortIcon direction={dir} />
                    </button>
                  ) : c.label}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => (
            <tr key={rowKey(row)} className="border-t border-line">
              {columns.map((c) => (
                <td key={c.key} className={`px-3 py-2 text-fg ${c.numeric ? "text-right tabular" : ""} ${c.mono ? "mono" : ""}`}>
                  {c.render ? c.render(row) : String(row[c.key] ?? "")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ---------- Code block with copy (falls back to selecting text on insecure origins) ---------- */

export function CodeBlock({ code, label }: { code: string; label: string }) {
  const [state, setState] = useState<"idle" | "copied" | "manual">("idle");
  const preRef = useRef<HTMLPreElement>(null);
  const selectText = () => {
    const el = preRef.current;
    const sel = window.getSelection();
    if (!el || !sel) return;
    const range = document.createRange();
    range.selectNodeContents(el);
    sel.removeAllRanges();
    sel.addRange(range);
  };
  const copy = async () => {
    try {
      if (!window.isSecureContext || !navigator.clipboard) throw new Error("no clipboard");
      await navigator.clipboard.writeText(code);
      setState("copied");
    } catch {
      selectText();
      setState("manual");
    }
    window.setTimeout(() => setState("idle"), 2000);
  };
  const text = state === "copied" ? "คัดลอกแล้ว" : state === "manual" ? "กด Ctrl+C" : "คัดลอก";
  return (
    <div className="flex items-start gap-2 rounded-md border border-line bg-surface-2 p-3">
      <pre ref={preRef} aria-label={label} className="mono min-w-0 flex-1 overflow-x-auto text-sm text-fg">{code}</pre>
      <Button variant="ghost" onClick={copy} aria-live="polite">{text}</Button>
    </div>
  );
}

/* ---------- Skeleton ---------- */

export function Skeleton({ className = "h-4 w-full" }: { className?: string }) {
  return <div aria-hidden="true" className={`animate-pulse rounded-sm bg-surface-2 ${className}`} />;
}

/* ---------- Error state: what happened and what to do next ---------- */

type ErrorStateProps = { title: string; detail: string; action?: { label: string; onClick: () => void } };

export function ErrorState({ title, detail, action }: ErrorStateProps) {
  return (
    <div role="alert" className="flex flex-col items-start gap-2 rounded-md border border-line bg-bad-bg p-4">
      <p className="flex items-center gap-2 font-semibold text-bad"><ErrorIcon /> {title}</p>
      <p className="text-sm text-fg">{detail}</p>
      {action && <Button variant="secondary" onClick={action.onClick}>{action.label}</Button>}
    </div>
  );
}
