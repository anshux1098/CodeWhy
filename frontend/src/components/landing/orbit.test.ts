import { describe, expect, it } from 'vitest';
import {
  ORBIT_SHAPES,
  ORBIT_SLOTS,
  arcSegmentPath,
  orbitMotionPath,
  orbitPoint,
} from './orbit';

const shape = ORBIT_SHAPES.wide;

describe('orbit geometry', () => {
  it('puts 270deg at the top of the orbit', () => {
    const top = orbitPoint(270, shape);
    expect(top.left).toBeCloseTo(shape.cx);
    expect(top.top).toBeCloseTo(shape.cy - shape.ry);
  });

  it('places stars on the arc instead of near it', () => {
    for (const angle of ORBIT_SLOTS.wide) {
      const point = orbitPoint(angle, shape);
      const nx = (point.left - shape.cx) / shape.rx;
      const ny = (point.top - shape.cy) / shape.ry;
      expect(nx * nx + ny * ny).toBeCloseTo(1, 5);
    }
  });

  it('centres an arc segment on the star angle', () => {
    const angle = 208;
    const start = orbitPoint(angle - 3, shape);
    const end = orbitPoint(angle + 3, shape);
    const d = arcSegmentPath(angle, 6, shape);
    expect(d.startsWith(`M ${Math.round(start.left * 100) / 100} ${Math.round(start.top * 100) / 100}`)).toBe(true);
    expect(d).toContain(`A ${shape.rx} ${shape.ry} 0 0 1`);
    expect(d.endsWith(`${Math.round(end.left * 100) / 100} ${Math.round(end.top * 100) / 100}`)).toBe(true);
  });

  it('starts and ends the travelling light at the top of the orbit', () => {
    const d = orbitMotionPath(shape);
    const top = `${shape.cx} ${shape.cy - shape.ry}`;
    expect(d.startsWith(`M ${top}`)).toBe(true);
    expect(d.endsWith(top)).toBe(true);
  });
});
