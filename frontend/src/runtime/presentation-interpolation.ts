export function interpolatePresentationValue(
  current: number,
  target: number,
  elapsedMs: number,
  timeConstantMs: number,
  snapDelta = Number.POSITIVE_INFINITY,
): number {
  if (!Number.isFinite(target)) return Number.isFinite(current) ? current : 0;
  if (!Number.isFinite(current) || Math.abs(target - current) >= snapDelta) return target;
  const elapsed = Math.max(0, Math.min(500, elapsedMs));
  const timeConstant = Math.max(1, timeConstantMs);
  const next = current + (target - current) * (1 - Math.exp(-elapsed / timeConstant));
  return Math.abs(target - next) < 0.1 ? target : next;
}
