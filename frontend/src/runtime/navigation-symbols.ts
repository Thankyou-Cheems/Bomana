/** Draw at the current origin; callers own size, color and selection emphasis. */
export function drawBombingZoneSymbol(context: CanvasRenderingContext2D, size: number): void {
  context.beginPath(); context.arc(0, 0, size, 0, Math.PI * 2); context.stroke();
  context.beginPath(); context.arc(0, 0, size * .38, 0, Math.PI * 2); context.fill();
}

export function drawPoiBracketSymbol(context: CanvasRenderingContext2D, size: number): void {
  const inner = size * .38;
  for (const [sx, sy] of [[-1, -1], [1, -1], [-1, 1], [1, 1]] as const) {
    context.beginPath();
    context.moveTo(sx * size, sy * inner); context.lineTo(sx * size, sy * size); context.lineTo(sx * inner, sy * size);
    context.stroke();
  }
}
