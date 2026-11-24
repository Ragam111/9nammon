// Pixel icons drawn here as plain SVG rects (no third-party assets). Every icon needs a label or a text sibling.

type IconProps = { label?: string; size?: number };

function Pixels({ label, size = 16, cells, viewBox = "0 0 8 8" }: IconProps & { cells: [number, number, string][]; viewBox?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox={viewBox}
      shapeRendering="crispEdges"
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      focusable="false"
    >
      {cells.map(([x, y, fill]) => (
        <rect key={`${x}-${y}`} x={x} y={y} width={1} height={1} fill={fill} />
      ))}
    </svg>
  );
}

/** Heart: success. */
export function HeartIcon(props: IconProps) {
  const c = "var(--ok)";
  const cells: [number, number, string][] = [
    [1, 2, c], [2, 2, c], [5, 2, c], [6, 2, c],
    [0, 3, c], [1, 3, c], [2, 3, c], [3, 3, c], [4, 3, c], [5, 3, c], [6, 3, c], [7, 3, c],
    [0, 4, c], [1, 4, c], [2, 4, c], [3, 4, c], [4, 4, c], [5, 4, c], [6, 4, c], [7, 4, c],
    [1, 5, c], [2, 5, c], [3, 5, c], [4, 5, c], [5, 5, c], [6, 5, c],
    [2, 6, c], [3, 6, c], [4, 6, c], [5, 6, c],
    [3, 7, c], [4, 7, c],
  ];
  return <Pixels {...props} cells={cells} />;
}

/** Sword: needs action. */
export function SwordIcon(props: IconProps) {
  const blade = "var(--fg)";
  const hilt = "var(--wood)";
  const cells: [number, number, string][] = [
    [7, 0, blade], [6, 1, blade], [5, 2, blade], [4, 3, blade], [3, 4, blade],
    [2, 4, hilt], [1, 5, hilt], [0, 6, hilt], [3, 3, hilt], [4, 5, hilt], [2, 5, hilt], [1, 6, hilt], [0, 7, hilt],
  ];
  return <Pixels {...props} cells={cells} />;
}

/** Block: empty state and general mark. */
export function BlockIcon(props: IconProps) {
  const grass = "var(--grass)";
  const dirt = "var(--wood)";
  const cells: [number, number, string][] = [];
  for (let y = 0; y < 8; y++) {
    for (let x = 0; x < 8; x++) {
      cells.push([x, y, y < 3 ? grass : dirt]);
    }
  }
  return <Pixels {...props} cells={cells} />;
}

/** Triangle: warning. */
export function WarnIcon(props: IconProps) {
  const c = "var(--warn)";
  const cells: [number, number, string][] = [[3, 0, c], [3, 1, c], [2, 2, c], [4, 2, c], [2, 3, c], [4, 3, c], [1, 4, c], [5, 4, c], [1, 5, c], [2, 5, c], [3, 5, c], [4, 5, c], [5, 5, c], [0, 6, c], [1, 6, c], [2, 6, c], [3, 6, c], [4, 6, c], [5, 6, c], [6, 6, c], [7, 6, c]];
  return <Pixels {...props} cells={cells} />;
}
