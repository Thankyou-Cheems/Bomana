/** Shared aircraft camera for the return corridor and forward terrain. */
export type CameraPoint = readonly [number, number, number];
export type ScreenPoint = readonly [number, number];
export type ScreenSegment = readonly [ScreenPoint, ScreenPoint];
const near = 30;
const perspective = (p: CameraPoint): ScreenPoint => [p[0] / p[2], p[1] / p[2]];
function intersectNear(p: CameraPoint, q: CameraPoint): CameraPoint {
  const t = (near - p[2]) / (q[2] - p[2]);
  return [p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t, near];
}

/** Right/down/forward metres; positive camera pitch looks down. */
export function aircraftCamera(pitch: number, roll: number) {
  const cp = Math.cos(pitch), sp = Math.sin(pitch), cr = Math.cos(roll), sr = Math.sin(roll);
  return (right: number, down: number, forward: number): CameraPoint => {
    const y = down * cp - forward * sp;
    return [right * cr + y * sr, -right * sr + y * cr, forward * cp + down * sp];
  };
}

/** Uniform 60-degree horizontal view; never fit the camera to terrain/target. */
export function aircraftCameraFrame(width: number, height: number) {
  return { focal: width / (2 * Math.tan(Math.PI / 6)), x: width / 2, y: Math.max(28, height * .25) };
}

export function projectCameraSegment(a: CameraPoint, b: CameraPoint): ScreenSegment | null {
  if (a[2] < near && b[2] < near) return null;
  return [perspective(a[2] < near ? intersectNear(a, b) : a), perspective(b[2] < near ? intersectNear(b, a) : b)];
}

export function projectCameraSurface(corners: readonly CameraPoint[]): ScreenPoint[] {
  const clipped: CameraPoint[] = [];
  for (let i = 0; i < corners.length; i++) {
    const a = corners[i]!, b = corners[(i + 1) % corners.length]!;
    if (a[2] >= near) clipped.push(a);
    if ((a[2] >= near) !== (b[2] >= near)) clipped.push(intersectNear(a, b));
  }
  return clipped.map(perspective);
}
