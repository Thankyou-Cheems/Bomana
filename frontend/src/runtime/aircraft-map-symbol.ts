/** Official role icons describe aircraft classes, not AI/player ownership or exact models. */
const SYMBOLS = {
  // In-game references: F-16 swept wings, A-10 straight wings, B-29 four engines.
  // These are class pictograms, never identified aircraft models.
  fighter: { label: "战斗机", short: "战", path: "M0 -11 L2 -5 L2 -2 L8 4 L8 6 L3 3 L2 7 L5 9 L5 10 L1 9 L-1 9 L-5 10 L-5 9 L-2 7 L-3 3 L-8 6 L-8 4 L-2 -2 L-2 -5 Z" },
  assault: { label: "攻击机", short: "攻", path: "M0 -10 L2 -7 L2 -2 L11 -2 L11 1 L6 2 L6 6 L4 6 L4 2 L2 2 L2 7 L6 7 L6 9 L-6 9 L-6 7 L-2 7 L-2 2 L-4 2 L-4 6 L-6 6 L-6 2 L-11 1 L-11 -2 L-2 -2 L-2 -7 Z" },
  bomber: { label: "轰炸机", short: "轰", path: "M0 -11 L2 -7 L2 -3 L5 -2 L5 -5 L7 -5 L7 -1 L9 0 L9 -3 L11 -3 L11 1 L13 2 L13 4 L2 1 L2 7 L6 9 L6 10 L1 9 L-1 9 L-6 10 L-6 9 L-2 7 L-2 1 L-13 4 L-13 2 L-11 1 L-11 -3 L-9 -3 L-9 0 L-7 -1 L-7 -5 L-5 -5 L-5 -2 L-2 -3 L-2 -7 Z" },
  helicopter: { label: "直升机", short: "直", path: "M-10 -7 L10 -7 L10 -5 L1 -5 L1 -3 L4 0 L3 4 L1 5 L1 8 L4 8 L4 10 L-4 10 L-4 8 L-1 8 L-1 5 L-3 4 L-4 0 L-1 -3 L-1 -5 L-10 -5 Z" },
  unknown: { label: "机种未知", short: "?", path: "M0 -6 L6 0 L0 6 L-6 0 Z" },
} as const;

export function aircraftMapSymbol(officialIcon: string | undefined) {
  switch (officialIcon?.trim().toLowerCase()) {
    case "fighter": return SYMBOLS.fighter;
    case "assault": return SYMBOLS.assault;
    case "bomber": return SYMBOLS.bomber;
    case "helicopter": return SYMBOLS.helicopter;
    default: return SYMBOLS.unknown;
  }
}

const paths = new Map<string, Path2D>();

/** Paths point up; callers apply heading and size without rotating labels or edge bearings. */
export function drawAircraftMapSymbol(ctx: CanvasRenderingContext2D, icon: string | undefined): void {
  const symbol = aircraftMapSymbol(icon);
  let path = paths.get(symbol.path);
  if (!path) { path = new Path2D(symbol.path); paths.set(symbol.path, path); }
  ctx.lineJoin = "round";
  ctx.stroke(path);
  ctx.fill(path);
}
