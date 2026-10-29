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

/**
 * Angles in degrees; 270 is the top of the orbit. Slots fan out from the
 * sides upward so repository stars never sit on the hero copy.
 */
export const ORBIT_SLOTS: Record<OrbitLayout, readonly number[]> = {
  wide: [208, 332, 242, 298, 190, 350],
  tablet: [212, 328],
  mobile: [250, 290],
};

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
