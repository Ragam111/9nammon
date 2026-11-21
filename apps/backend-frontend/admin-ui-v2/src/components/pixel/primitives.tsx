// Shared pixel components: bevel buttons, status badges, state screens, the slot table and the block loader.
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { BlockIcon, HeartIcon, SwordIcon, WarnIcon } from "./icons";

type ButtonVariant = "primary" | "secondary" | "tertiary" | "danger" | "ghost";

export function BevelButton({
  variant = "primary",
  loading = false,
  disabled,
  className = "",
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant; loading?: boolean }) {
  const isDisabled = disabled || loading;
  return (
    <button
      type="button"
      {...rest}
      className={`btn btn--${variant} ${className}`.trim()}
      disabled={isDisabled}
      aria-busy={loading || undefined}
    >
      {loading ? "กำลังทำงาน…" : children}
    </button>
  );
}

type BadgeTone = "ok" | "warn" | "bad" | "info" | "neutral";

const TONE_ICON: Record<BadgeTone, (p: { label?: string; size?: number }) => ReactNode> = {
  ok: HeartIcon,
  warn: WarnIcon,
  bad: SwordIcon,
  info: BlockIcon,
  neutral: BlockIcon,
};

/** Icon and text together, so the state never depends on color alone. */
export function StatusBadge({ tone, children }: { tone: BadgeTone; children: ReactNode }) {
  const Icon = TONE_ICON[tone];
  return (
    <span className={`badge badge--${tone}`}>
      <Icon size={12} />
      {children}
    </span>
  );
}

export function StateScreen({
  kind,
  title,
  detail,
  action,
}: {
  kind: "empty" | "error" | "forbidden" | "notfound";
  title: string;
  detail?: string;
  action?: ReactNode;
}) {
  const Icon = kind === "empty" ? BlockIcon : kind === "error" ? SwordIcon : WarnIcon;
  return (
    <section className="frame state" role={kind === "error" ? "alert" : undefined}>
      <Icon size={48} label={kind === "empty" ? "ยังไม่มีข้อมูล" : undefined} />
      <h2 className="state__title">{title}</h2>
      {detail && <p className="muted">{detail}</p>}
      {action}
    </section>
  );
}

export function BlockLoader({ label = "กำลังโหลด" }: { label?: string }) {
  return (
    <div role="progressbar" aria-label={label} aria-busy="true" className="blockbar" style={{ width: "100%" }}>
      <div className="blockbar__fill" style={{ width: "100%", opacity: 0.6 }} />
    </div>
  );
}

export type Column<T> = {
  key: string;
  label: string;
  sortKey?: string;
  render: (row: T) => ReactNode;
};

/** Table whose rows are slots. Sortable headers expose aria-sort. */
export function SlotTable<T extends { id: number }>({
  columns,
  rows,
  sortKey,
  order,
  onSort,
  caption,
}: {
  columns: Column<T>[];
  rows: T[];
  sortKey?: string;
  order?: "asc" | "desc";
  onSort?: (key: string) => void;
  caption: string;
}) {
  return (
    <div style={{ overflowX: "auto" }}>
      <table className="slot-table">
        <caption className="visually-hidden">{caption}</caption>
        <thead>
          <tr>
            {columns.map((col) => {
              const sortable = Boolean(col.sortKey && onSort);
              const active = sortable && sortKey === col.sortKey;
              return (
                <th key={col.key} scope="col" aria-sort={active ? (order === "asc" ? "ascending" : "descending") : undefined}>
                  {sortable ? (
                    <button type="button" className="sort" onClick={() => onSort?.(col.sortKey as string)}>
                      {col.label}
                      {active ? (order === "asc" ? " ▲" : " ▼") : ""}
                    </button>
                  ) : (
                    col.label
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              {columns.map((col) => (
                <td key={col.key} data-label={col.label}>
                  {col.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
