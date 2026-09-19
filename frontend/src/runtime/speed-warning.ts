/** Lead margins below the conservative source VNE/MNE/flap reference.
 * These are notification policy, not three native fracture thresholds.
 * Native damage also depends on unobserved state; see the native-speed research.
 */
export const SPEED_WARNING_RATIOS = [.9, .95, 1] as const;

export function speedWarningLevel(ratio: number): "none" | "caution" | "warning" | "critical" {
  if (ratio >= SPEED_WARNING_RATIOS[2]) return "critical";
  if (ratio >= SPEED_WARNING_RATIOS[1]) return "warning";
  if (ratio >= SPEED_WARNING_RATIOS[0]) return "caution";
  return "none";
}
