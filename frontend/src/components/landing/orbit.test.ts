import { describe, expect, it } from 'vitest';
import {
  ORBIT_PERIOD_MS,
  ORBIT_SHAPES,
  arcSegmentPath,
  normalizeAngle,
  orbitMotionPath,
  orbitPoint,
  starAngle,
} from './orbit';

const shape = ORBIT_SHAPES.wide;

describe('orbit geometry', () => {
  it('puts 270deg at the top of the orbit', () => {
    const top = orbitPoint(270, shape);
    expect(top.left).toBeCloseTo(shape.cx);
    expect(top.top).toBeCloseTo(shape.cy - shape.ry);
  });

  it('spreads repositories evenly around the orbit', () => {
    const angles = Array.from({ length: 4 }, (_, i) => starAngle(i, 4, 0));
    expect(angles).toEqual([270, 0, 90, 180]);
    expect(normalizeAngle(-90)).toBe(270);
    expect(normalizeAngle(450)).toBe(90);
  });

  it('drifts one full revolution per period and stays deterministic', () => {
    const start = starAngle(1, 3, 0);
    expect(starAngle(1, 3, ORBIT_PERIOD_MS)).toBeCloseTo(start, 6);
    expect(starAngle(1, 3, ORBIT_PERIOD_MS / 4)).toBeCloseTo(normalizeAngle(start + 90), 6);
    expect(starAngle(2, 3, 12_345)).toBe(starAngle(2, 3, 12_345));
  });

  it('places every drifting star on the arc', () => {
    for (let i = 0; i < 6; i += 1) {
      for (const elapsed of [0, 30_000, 90_000]) {
        const point = orbitPoint(starAngle(i, 6, elapsed), shape);
        const nx = (point.left - shape.cx) / shape.rx;
        const ny = (point.top - shape.cy) / shape.ry;
        expect(nx * nx + ny * ny).toBeCloseTo(1, 5);
      }
    }
  });

  it('centres an arc segment on the star angle', () => {
    const angle = 208;
    const start = orbitPoint(angle - 3, shape);
    const end = orbitPoint(angle + 3, shape);
    const d = arcSegmentPath(angle, 6, shape);
    expect(
      d.startsWith(
        `M ${Math.round(start.left * 100) / 100} ${Math.round(start.top * 100) / 100}`,
      ),
    ).toBe(true);
    expect(d).toContain(`A ${shape.rx} ${shape.ry} 0 0 1`);
    expect(
      d.endsWith(`${Math.round(end.left * 100) / 100} ${Math.round(end.top * 100) / 100}`),
    ).toBe(true);
  });

  it('starts and ends the travelling light at the top of the orbit', () => {
    const d = orbitMotionPath(shape);
    const top = `${shape.cx} ${shape.cy - shape.ry}`;
    expect(d.startsWith(`M ${top}`)).toBe(true);
    expect(d.endsWith(top)).toBe(true);
  });
});
