/**
 * Contour-wave geometry for the landing backdrop.
 *
 * Each wave is stored as the twelve numbers of an absolute
 * `M x y C x y x y x y S x y x y` path, so the same data can be
 * re-emitted as a deformed path without parsing strings.
 */
export type WaveTone = 'sage' | 'bronze' | 'taupe';

export interface WaveSpec {
  /** x0 y0 c1x c1y c2x c2y x3 y3 s4x s4y s5x s5y */
  points: readonly number[];
  tone: WaveTone;
  width: number;
  opacity: number;
  /** Idle drift duration in seconds. */
  drift: number;
}

const W = (
  points: readonly number[],
  tone: WaveTone,
  width: number,
  opacity: number,
  drift: number,
): WaveSpec => ({ points, tone, width, opacity, drift });

const round = (value: number) => Math.round(value * 10) / 10;

export function buildWavePath(points: readonly number[]): string {
  return (
    `M ${round(points[0])} ${round(points[1])}` +
    ` C ${round(points[2])} ${round(points[3])} ${round(points[4])} ${round(points[5])} ${round(points[6])} ${round(points[7])}` +
    ` S ${round(points[8])} ${round(points[9])} ${round(points[10])} ${round(points[11])}`
  );
}

/**
 * Bend a wave around the pointer. Only points near the pointer move,
 * and the lift decays with vertical distance so far lines stay still.
 */
export function deformWave(
  base: readonly number[],
  pointerX: number,
  pointerY: number,
  energy: number,
): string {
  if (energy <= 0.002) return buildWavePath(base);

  const out: number[] = new Array(12);
  for (let i = 0; i < 12; i += 2) {
    const x = base[i];
    const y = base[i + 1];
    const distanceX = (x - pointerX) / 300;
    const distanceY = (pointerY - y) / 260;
    const falloff = Math.exp(-(distanceX * distanceX)) * Math.exp(-(distanceY * distanceY));
    const lift = Math.max(-13, Math.min(13, (pointerY - y) * 0.12 * falloff));
    out[i] = x;
    out[i + 1] = y + lift * energy;
  }
  return buildWavePath(out);
}

export const WAVE_FIELD: readonly WaveSpec[] = [
  W([-150, 598, 110, 558, 340, 700, 640, 664, 1140, 596, 1720, 638], 'sage', 0.7, 0.55, 46),
  W([-140, 632, 170, 592, 400, 700, 700, 672, 1200, 604, 1720, 656], 'bronze', 0.8, 0.62, 58),
  W([-150, 662, 120, 618, 360, 690, 620, 668, 1120, 618, 1720, 665], 'taupe', 0.7, 0.55, 39),
  W([-120, 694, 180, 642, 380, 730, 660, 700, 1180, 642, 1720, 700], 'bronze', 0.95, 0.76, 64),
  W([-140, 724, 160, 672, 420, 760, 720, 730, 1220, 672, 1720, 725], 'sage', 0.7, 0.58, 51),
  W([-130, 748, 140, 698, 400, 782, 690, 755, 1200, 700, 1720, 748], 'taupe', 0.75, 0.6, 43),
  W([-120, 762, 200, 706, 460, 796, 760, 765, 1240, 706, 1730, 760], 'bronze', 0.9, 0.8, 68),
  W([-145, 796, 220, 742, 500, 834, 800, 807, 1280, 748, 1720, 800], 'sage', 0.7, 0.58, 47),
  W([-140, 812, 180, 766, 470, 852, 770, 826, 1260, 772, 1720, 820], 'taupe', 0.8, 0.64, 55),
  W([-120, 842, 240, 792, 540, 876, 840, 849, 1320, 792, 1720, 842], 'bronze', 0.75, 0.66, 61),
  W([-130, 872, 260, 828, 560, 906, 860, 884, 1340, 830, 1720, 878], 'sage', 0.65, 0.5, 41),
  W([-110, 900, 280, 856, 580, 926, 880, 902, 1360, 856, 1720, 900], 'taupe', 0.7, 0.52, 57),
];
