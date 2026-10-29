import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowRight, GitBranch } from 'lucide-react';
import type { Repository } from '../types';
import { branchFromScope } from '../lib/repoBranch';
import { WAVE_FIELD, buildWavePath, deformWave } from './landing/waves';
import {
  ORBIT_DUST,
  ORBIT_SHAPES,
  ORBIT_SLOTS,
  arcSegmentPath,
  orbitMotionPath,
  orbitPoint,
  type OrbitLayout,
} from './landing/orbit';

interface HeroProps {
  onNavigateToWorkspace?: (initialQuestion?: string) => void;
  repositories?: Repository[];
  selectedRepo?: Repository | null;
  onSelectRepo?: (repo: Repository) => void;
}

const STAR_RADIUS = 180;

export const Hero: React.FC<HeroProps> = ({
  onNavigateToWorkspace,
  repositories = [],
  selectedRepo = null,
  onSelectRepo,
}) => {
  const heroRef = useRef<HTMLElement>(null);
  const [layout, setLayout] = useState<OrbitLayout>('wide');
  const [hoveredRepoId, setHoveredRepoId] = useState<string | null>(null);

  // Keep the star slots comfortable on smaller viewports.
  useEffect(() => {
    const mobile = window.matchMedia('(max-width: 767px)');
    const wide = window.matchMedia('(min-width: 1100px)');
    const update = () => {
      setLayout(mobile.matches ? 'mobile' : wide.matches ? 'wide' : 'tablet');
    };
    update();
    mobile.addEventListener('change', update);
    wide.addEventListener('change', update);
    return () => {
      mobile.removeEventListener('change', update);
      wide.removeEventListener('change', update);
    };
  }, []);

  const shape = ORBIT_SHAPES[layout];

  const stars = useMemo(() => {
    const slots = ORBIT_SLOTS[layout];
    return repositories
      .slice(0, slots.length)
      .map((repo, index) => ({ repo, ...orbitPoint(slots[index], shape) }));
  }, [repositories, layout, shape]);

  // One pointer loop drives star proximity, wave deformation and the local glow.
  useEffect(() => {
    const hero = heroRef.current;
    if (!hero) return;

    const reduceQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    const waveEls = Array.from(hero.querySelectorAll<SVGPathElement>('[data-cw-wave]'));
    const basePaths = waveEls.map((el) => el.getAttribute('d') ?? '');
    const glow = hero.querySelector<HTMLElement>('[data-cw-wave-glow]');
    const arcSvg = hero.querySelector<SVGSVGElement>('.cw-arc-svg');
    if (document.hidden || reduceQuery.matches) arcSvg?.pauseAnimations();
    const starEls = new Map<string, HTMLButtonElement>();
    hero.querySelectorAll<HTMLButtonElement>('[data-cw-repo]').forEach((el) => {
      const id = el.dataset.cwRepo;
      if (id) starEls.set(id, el);
    });
    const starGeometry = stars.map((star) => ({
      id: star.repo.id,
      x: star.left / 100,
      y: star.top / 100,
    }));

    const state = {
      targetX: 0,
      targetY: 0,
      x: 0,
      y: 0,
      width: 0,
      height: 0,
      inside: false,
      energy: 0,
      raf: 0,
      visible: !document.hidden,
      paths: [] as string[],
      near: new Map<string, number>(),
    };

    const setNear = (id: string, value: number) => {
      const previous = state.near.get(id) ?? 0;
      if (Math.abs(previous - value) < 0.008) return;
      state.near.set(id, value);
      starEls.get(id)?.style.setProperty('--cw-near', value.toFixed(3));
    };

    const paintStars = () => {
      for (const star of starGeometry) {
        if (state.width === 0 || state.height === 0) {
          setNear(star.id, 0);
          continue;
        }
        const dx = state.x - star.x * state.width;
        const dy = state.y - star.y * state.height;
        const distance = Math.hypot(dx, dy);
        const closeness = Math.max(0, 1 - distance / STAR_RADIUS);
        setNear(star.id, closeness ** 1.7 * state.energy);
      }
    };

    const paintWaves = () => {
      const scale = Math.max(state.width / 1600, state.height / 900);
      const offsetX = (state.width - 1600 * scale) / 2;
      const offsetY = (state.height - 900 * scale) / 2;
      const pointerX = (state.x - offsetX) / Math.max(scale, 0.0001);
      const pointerY = (state.y - offsetY) / Math.max(scale, 0.0001);
      const active = state.energy > 0.004;

      for (let i = 0; i < waveEls.length; i += 1) {
        const next = active
          ? deformWave(WAVE_FIELD[i].points, pointerX, pointerY, state.energy)
          : basePaths[i];
        if (state.paths[i] !== next) {
          waveEls[i].setAttribute('d', next);
          state.paths[i] = next;
        }
      }

      if (glow) {
        const gate = Math.min(
          1,
          Math.max(0, (state.y / Math.max(state.height, 1) - 0.42) / 0.18),
        );
        glow.style.transform = `translate3d(${state.x - 310}px, ${state.y - 310}px, 0)`;
        glow.style.opacity = (state.energy * gate * 0.9).toFixed(3);
      }
    };

    const frame = () => {
      state.raf = 0;
      if (!state.visible) return;

      state.x += (state.targetX - state.x) * 0.18;
      state.y += (state.targetY - state.y) * 0.18;
      const targetEnergy = state.inside ? 1 : 0;
      state.energy += (targetEnergy - state.energy) * 0.1;
      if (!state.inside && state.energy < 0.008) state.energy = 0;

      paintStars();
      paintWaves();

      const steady =
        Math.abs(state.targetX - state.x) < 0.4 &&
        Math.abs(state.targetY - state.y) < 0.4 &&
        Math.abs(targetEnergy - state.energy) < 0.01;
      if (!steady) state.raf = requestAnimationFrame(frame);
    };

    const schedule = () => {
      if (state.raf || !state.visible || reduceQuery.matches) return;
      state.raf = requestAnimationFrame(frame);
    };

    const handleMove = (event: PointerEvent) => {
      if (event.pointerType === 'touch' || reduceQuery.matches) return;
      const rect = hero.getBoundingClientRect();
      state.width = rect.width;
      state.height = rect.height;
      state.targetX = event.clientX - rect.left;
      state.targetY = event.clientY - rect.top;
      if (!state.inside) {
        state.inside = true;
        if (state.energy === 0) {
          state.x = state.targetX;
          state.y = state.targetY;
        }
      }
      schedule();
    };

    const handleLeave = () => {
      state.inside = false;
      schedule();
    };

    const measure = () => {
      const rect = hero.getBoundingClientRect();
      state.width = rect.width;
      state.height = rect.height;
    };

    const handleVisibility = () => {
      state.visible = !document.hidden;
      hero.classList.toggle('is-paused', !state.visible);
      if (state.visible) {
        if (!reduceQuery.matches) arcSvg?.unpauseAnimations();
        schedule();
      } else {
        arcSvg?.pauseAnimations();
      }
    };

    const handleMotionPreference = () => {
      if (!reduceQuery.matches) {
        if (!document.hidden) arcSvg?.unpauseAnimations();
        if (state.inside) schedule();
        return;
      }
      arcSvg?.pauseAnimations();
      if (state.raf) cancelAnimationFrame(state.raf);
      state.raf = 0;
      state.inside = false;
      state.energy = 0;
      state.x = state.targetX;
      state.y = state.targetY;
      paintStars();
      paintWaves();
    };

    measure();
    hero.classList.toggle('is-paused', document.hidden);
    hero.addEventListener('pointermove', handleMove, { passive: true });
    hero.addEventListener('pointerleave', handleLeave);
    hero.addEventListener('pointercancel', handleLeave);
    document.addEventListener('visibilitychange', handleVisibility);
    reduceQuery.addEventListener('change', handleMotionPreference);
    const observer = new ResizeObserver(measure);
    observer.observe(hero);

    return () => {
      if (state.raf) cancelAnimationFrame(state.raf);
      hero.removeEventListener('pointermove', handleMove);
      hero.removeEventListener('pointerleave', handleLeave);
      hero.removeEventListener('pointercancel', handleLeave);
      document.removeEventListener('visibilitychange', handleVisibility);
      reduceQuery.removeEventListener('change', handleMotionPreference);
      observer.disconnect();
      hero.classList.remove('is-paused');
    };
  }, [stars]);

  return (
    <section className="cw-hero" ref={heroRef}>
      <div className="cw-backdrop" aria-hidden="true">
        <svg viewBox="0 0 1600 900" preserveAspectRatio="xMidYMid slice">
          <defs>
            <radialGradient id="cw-amb-olive" cx="50%" cy="36%" r="52%">
              <stop offset="0%" stopColor="#757F6C" stopOpacity="0.12" />
              <stop offset="55%" stopColor="#757F6C" stopOpacity="0.04" />
              <stop offset="100%" stopColor="#080907" stopOpacity="0" />
            </radialGradient>
            <radialGradient id="cw-amb-bronze" cx="64%" cy="76%" r="46%">
              <stop offset="0%" stopColor="#B9915E" stopOpacity="0.09" />
              <stop offset="100%" stopColor="#080907" stopOpacity="0" />
            </radialGradient>
            <radialGradient id="cw-amb-sage" cx="34%" cy="80%" r="42%">
              <stop offset="0%" stopColor="#8C806F" stopOpacity="0.07" />
              <stop offset="100%" stopColor="#080907" stopOpacity="0" />
            </radialGradient>

            <linearGradient id="cw-line-sage" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#757F6C" stopOpacity="0.05" />
              <stop offset="42%" stopColor="#8C806F" stopOpacity="0.62" />
              <stop offset="100%" stopColor="#757F6C" stopOpacity="0.05" />
            </linearGradient>
            <linearGradient id="cw-line-bronze" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#8C806F" stopOpacity="0.05" />
              <stop offset="55%" stopColor="#B9915E" stopOpacity="0.68" />
              <stop offset="100%" stopColor="#8C806F" stopOpacity="0.05" />
            </linearGradient>
            <linearGradient id="cw-line-taupe" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#B9915E" stopOpacity="0.05" />
              <stop offset="48%" stopColor="#8C806F" stopOpacity="0.56" />
              <stop offset="100%" stopColor="#B9915E" stopOpacity="0.05" />
            </linearGradient>

            <radialGradient id="cw-shade-bronze" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stopColor="#B9915E" stopOpacity="0.07" />
              <stop offset="100%" stopColor="#B9915E" stopOpacity="0" />
            </radialGradient>
            <radialGradient id="cw-shade-olive" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stopColor="#757F6C" stopOpacity="0.06" />
              <stop offset="100%" stopColor="#757F6C" stopOpacity="0" />
            </radialGradient>
          </defs>

          {/* ambient light */}
          <rect width="1600" height="900" fill="url(#cw-amb-olive)" />
          <rect width="1600" height="900" fill="url(#cw-amb-sage)" />
          <rect width="1600" height="900" fill="url(#cw-amb-bronze)" />

          {/* particle field, a few of them twinkle */}
          {Array.from({ length: 70 }).map((_, i) => {
            const x = (i * 97) % 1600;
            const y = (i * 53 + 17) % 900;
            const twinkles = i % 5 === 0;
            return (
              <circle
                key={i}
                className={twinkles ? 'cw-particle is-twinkling' : 'cw-particle'}
                cx={x}
                cy={y}
                r={i % 11 === 0 ? 1.2 : 0.8}
                fill={i % 13 === 0 ? '#B9915E' : '#8C806F'}
                opacity={i % 11 === 0 ? 0.5 : 0.28}
                style={
                  twinkles
                    ? {
                        animationDuration: `${8 + (i % 5) * 3.4}s`,
                        animationDelay: `${-(i % 17) * 1.6}s`,
                      }
                    : undefined
                }
              />
            );
          })}

          {/* atmospheric shading beneath selected curves */}
          <ellipse cx="1130" cy="862" rx="520" ry="150" fill="url(#cw-shade-bronze)" />
          <ellipse cx="360" cy="872" rx="480" ry="140" fill="url(#cw-shade-olive)" />

          {/* flowing silk / topographic contour lines */}
          <g className="cw-waves">
            {WAVE_FIELD.map((wave, i) => (
              <path
                key={i}
                data-cw-wave
                className={`cw-wave-path${i % 3 === 0 ? ' is-drifting' : ''}`}
                d={buildWavePath(wave.points)}
                fill="none"
                stroke={`url(#cw-line-${wave.tone})`}
                strokeWidth={wave.width}
                opacity={wave.opacity}
                strokeLinecap="round"
                style={{
                  animationDuration: `${wave.drift}s`,
                  animationDelay: `${-i * 1.7}s`,
                }}
              />
            ))}
          </g>
        </svg>
      </div>

      <div className="cw-wave-glow" data-cw-wave-glow aria-hidden="true" />

      <div className="cw-orbit">
        <svg
          className="cw-arc-svg"
          viewBox="0 0 100 100"
          preserveAspectRatio="none"
          aria-hidden="true"
          focusable="false"
        >
          <defs>
            <linearGradient id="cw-arc-grad" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopColor="#757F6C" stopOpacity="0.45" />
              <stop offset="50%" stopColor="#B9915E" stopOpacity="0.7" />
              <stop offset="100%" stopColor="#8C806F" stopOpacity="0.45" />
            </linearGradient>
            <radialGradient id="cw-light-glow">
              <stop offset="0%" stopColor="#F1DFC0" stopOpacity="0.5" />
              <stop offset="55%" stopColor="#E6D3AE" stopOpacity="0.16" />
              <stop offset="100%" stopColor="#E6D3AE" stopOpacity="0" />
            </radialGradient>
          </defs>
          <ellipse
            className="cw-arc-line"
            cx={shape.cx}
            cy={shape.cy}
            rx={shape.rx}
            ry={shape.ry}
            pathLength={1000}
            vectorEffect="non-scaling-stroke"
            fill="none"
            stroke="url(#cw-arc-grad)"
          />
          <g className="cw-arc-light">
            <ellipse rx="0.62" ry="0.95" fill="url(#cw-light-glow)" />
            <ellipse rx="0.16" ry="0.26" fill="#F4E7CC" />
            <animateMotion dur="52s" repeatCount="indefinite" path={orbitMotionPath(shape)} />
          </g>

          {stars.map((star) => (
            <path
              key={`arc-${star.repo.id}`}
              d={arcSegmentPath(star.angle, 6, shape)}
              className={`cw-arc-seg${selectedRepo?.id === star.repo.id ? ' is-selected' : ''}${
                hoveredRepoId === star.repo.id ? ' is-hovered' : ''
              }`}
              fill="none"
              stroke="#E2C79B"
              strokeWidth="1.7"
              strokeLinecap="round"
              vectorEffect="non-scaling-stroke"
            />
          ))}
        </svg>

        {ORBIT_DUST.map((dust) => {
          const point = orbitPoint(dust.angle, shape);
          return (
            <span
              key={dust.angle}
              className="cw-orbit-dust"
              aria-hidden="true"
              style={{
                left: `${point.left}%`,
                top: `${point.top}%`,
                width: dust.size * 2,
                height: dust.size * 2,
                opacity: dust.opacity,
              }}
            />
          );
        })}

        {stars.length > 0 && (
          <div className="cw-orbit-stars" role="group" aria-label="Repositories">
            {stars.map(({ repo, left, top }, index) => {
              const isSelected = selectedRepo?.id === repo.id;
              const branch = branchFromScope(repo.scope);
              const tipEdge = left < 20 ? ' is-tip-left' : left > 80 ? ' is-tip-right' : '';
              const tipSide = top < 24 ? ' is-tip-below' : '';
              return (
                <button
                  key={repo.id}
                  type="button"
                  data-cw-repo={repo.id}
                  className={`cw-repo-star${isSelected ? ' is-selected' : ''}${tipEdge}${tipSide}`}
                  style={{ left: `${left}%`, top: `${top}%` }}
                  aria-label={`Repository ${repo.name}${isSelected ? ', current repository' : ''}${
                    branch ? `, branch ${branch}` : ''
                  }`}
                  aria-describedby={`cw-repo-tip-${index}`}
                  onPointerEnter={() => setHoveredRepoId(repo.id)}
                  onPointerLeave={() =>
                    setHoveredRepoId((current) => (current === repo.id ? null : current))
                  }
                  onFocus={() => setHoveredRepoId(repo.id)}
                  onBlur={() =>
                    setHoveredRepoId((current) => (current === repo.id ? null : current))
                  }
                  onClick={() => onSelectRepo?.(repo)}
                >
                  <span className="cw-star-halo" aria-hidden="true" />
                  <span className="cw-star-ring" aria-hidden="true" />
                  <span className="cw-star-dot" aria-hidden="true" />
                  <span className="cw-star-tip" id={`cw-repo-tip-${index}`} role="tooltip">
                    <span className="cw-tip-head">
                      <GitBranch className="cw-tip-icon" aria-hidden="true" />
                      <span className="cw-tip-kind">Repository</span>
                      {isSelected && <span className="cw-tip-current">Current</span>}
                    </span>
                    <span className="cw-tip-name">{repo.name}</span>
                    {branch && <span className="cw-tip-branch">branch {branch}</span>}
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </div>

      <div className="cw-hero-content">
        <div className="cw-eyebrow">
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
            <circle cx="3" cy="6" r="1.6" fill="#B9915E" />
            <circle cx="9" cy="6" r="1.6" fill="#757F6C" />
            <path d="M4.6 6h2.8" stroke="#8C806F" strokeWidth="1" />
          </svg>
          <span>Code Archeology &amp; Temporal Decision Provenance</span>
        </div>

        <div className="cw-hero-mark flex items-center justify-center">Cw.</div>

        <h1 className="cw-hero-title">
          Code<span className="cw-why">Why</span>
        </h1>

        <p className="cw-tagline">
          Every line has a history. Find the reasoning, not just the code.
        </p>

        <button
          type="button"
          onClick={() => onNavigateToWorkspace?.()}
          className="cw-cta"
        >
          <span>Start investigation</span>
          <ArrowRight className="h-4 w-4 cw-arrow" />
        </button>
      </div>
    </section>
  );
};
