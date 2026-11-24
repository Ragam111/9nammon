// Small inline SVG icons. Decorative by default (aria-hidden); the text next to them carries meaning.

type IconProps = { className?: string };

const base = "inline-block h-4 w-4 shrink-0";

export function CheckIcon({ className = "" }: IconProps) {
  return (
    <svg className={`${base} ${className}`} viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M3 8.5l3 3 7-7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function WarnIcon({ className = "" }: IconProps) {
  return (
    <svg className={`${base} ${className}`} viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M8 2l6.5 11.5h-13L8 2z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
      <path d="M8 6.5v3.2M8 11.6v.1" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

export function ErrorIcon({ className = "" }: IconProps) {
  return (
    <svg className={`${base} ${className}`} viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <circle cx="8" cy="8" r="6.5" stroke="currentColor" strokeWidth="1.6" />
      <path d="M5.8 5.8l4.4 4.4M10.2 5.8l-4.4 4.4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

export function InfoIcon({ className = "" }: IconProps) {
  return (
    <svg className={`${base} ${className}`} viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <circle cx="8" cy="8" r="6.5" stroke="currentColor" strokeWidth="1.6" />
      <path d="M8 7.2v4M8 4.6v.1" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

export function SortIcon({ direction, className = "" }: IconProps & { direction: "asc" | "desc" | "none" }) {
  const up = direction === "asc" ? "currentColor" : "transparent";
  const down = direction === "desc" ? "currentColor" : "transparent";
  return (
    <svg className={`${base} ${className}`} viewBox="0 0 16 16" aria-hidden="true">
      <path d="M8 3l3 4H5l3-4z" fill={up} stroke="currentColor" strokeWidth="1" />
      <path d="M8 13l-3-4h6l-3 4z" fill={down} stroke="currentColor" strokeWidth="1" />
    </svg>
  );
}
