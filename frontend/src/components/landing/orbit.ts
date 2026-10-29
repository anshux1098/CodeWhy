/**
 * Orbit geometry for the landing page, expressed as percentages of the
 * hero box so the arc and the repository stars always agree, at any size.
 */
export type OrbitLayout = 'wide' | 'tablet' | 'mobile';

export interface OrbitShape {
  cx: number;
  cy: number;
  rx: number;
  ry: number;
}

/**
 * The wide shape reproduces the original backdrop arc: a wide, low ellipse
 * that clears the hero copy and settles into the wave band.
 */
export const ORBIT_SHAPES: Record<OrbitLayout, OrbitShape> = {
  wide: { cx: 50.5, cy: 49, rx: 46, ry: 42 },
  tablet: { cx: 50, cy: 49, rx: 44, ry: 40 },
  mobile: { cx: 50, cy: 44, rx: 44, ry: 36 },
};

/** One full, slow revolution. */
export const ORBIT_PERIOD_MS = 240_000;

/** Dim, non-interactive points that give the arc some company. */
export const ORBIT_DUST: readonly { angle: number; size: number; opacity: number }[] = [
  { angle: 270, size: 2.2, opacity: 0.7 },
  { angle: 210, size: 1.6, opacity: 0.4 },
  { angle: 330, size: 1.6, opacity: 0.4 },
];

export interface OrbitPoint {
  angle: number;
  left: number;
  top: number;
}

export function normalizeAngle(angle: number): number {
  const wrapped = angle % 360;
  return wrapped < 0 ? wrapped + 360 : wrapped;
}

/**
 * Deterministic star angle: repositories are spread evenly from the top of
 * the orbit, then drift clockwise at a constant rate.
 */
export function starAngle(index: number, count: number, elapsedMs: number): number {
  if (count <= 0) return 270;
  const spread = (360 * index) / count;
  const drift = (elapsedMs / ORBIT_PERIOD_MS) * 360;
  return normalizeAngle(270 + spread + drift);
}

export function orbitPoint(angle: number, shape: OrbitShape): OrbitPoint {
  const radians = (angle * Math.PI) / 180;
  return {
    angle,
    left: shape.cx + shape.rx * Math.cos(radians),
    top: shape.cy + shape.ry * Math.sin(radians),
  };
}

const round = (value: number) => Math.round(value * 100) / 100;

/** A short elliptical arc centred on `angle`, in viewBox units. */
export function arcSegmentPath(angle: number, spread: number, shape: OrbitShape): string {
  const start = orbitPoint(angle - spread / 2, shape);
  const end = orbitPoint(angle + spread / 2, shape);
  return (
    `M ${round(start.left)} ${round(start.top)}` +
    ` A ${shape.rx} ${shape.ry} 0 0 1 ${round(end.left)} ${round(end.top)}`
  );
}

/** Closed path for the travelling light, starting at the top of the orbit. */
export function orbitMotionPath(shape: OrbitShape): string {
  const { cx, cy, rx, ry } = shape;
  return (
    `M ${cx} ${cy - ry}` +
    ` A ${rx} ${ry} 0 1 1 ${cx} ${cy + ry}` +
    ` A ${rx} ${ry} 0 1 1 ${cx} ${cy - ry}`
  );
}
