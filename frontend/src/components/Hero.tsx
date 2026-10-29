import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ArrowRight, Check, ExternalLink, GitBranch, X } from 'lucide-react';
import type { Repository } from '../types';
import { branchFromScope } from '../lib/repoBranch';
import {
  WAVE_FIELD,
  buildWavePath,
  deformWave,
  type WaveInfluence,
} from './landing/waves';
import {
  ORBIT_DUST,
  ORBIT_SHAPES,
  arcSegmentPath,
  orbitMotionPath,
  orbitPoint,
  starAngle,
  type OrbitLayout,
} from './landing/orbit';

interface HeroProps {
  onNavigateToWorkspace?: (initialQuestion?: string) => void;
  repositories?: Repository[];
  selectedRepo?: Repository | null;
  onSelectRepo?: (repo: Repository) => void;
}

const STAR_RADIUS = 180;
const PANEL_WIDTH = 304;
const PANEL_HEIGHT = 340;
const PANEL_MARGIN = 16;
const PANEL_GAP = 14;

interface PanelPosition {
  left: number;
  top: number;
}

/** Panel identity plus the selection it was opened against. */
interface PanelSelection {
  repoId: string;
  selectionAtOpen: string | null;
}

const formatDate = (value?: string | null): string | null => {
  if (!value) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  return match ? `${match[1]}-${match[2]}-${match[3]}` : null;
};

const ownerOf = (repo: Repository): string | null => {
  if (repo.owner) return repo.owner;
  const fullName = repo.full_name;
  if (!fullName) return null;
  const [namespace] = fullName.split('/');
  return namespace || null;
};

export const Hero: React.FC<HeroProps> = ({
  onNavigateToWorkspace,
  repositories = [],
  selectedRepo = null,
  onSelectRepo,
}) => {
  const heroRef = useRef<HTMLElement>(null);
  const [layout, setLayout] = useState<OrbitLayout>('wide');
  const [hoveredRepoId, setHoveredRepoId] = useState<string | null>(null);
  const [panelState, setPanelState] = useState<PanelSelection | null>(null);
  const [panelPos, setPanelPos] = useState<PanelPosition | null>(null);

  const panelRef = useRef<HTMLDivElement>(null);
  const panelTriggerRef = useRef<HTMLButtonElement | null>(null);

  const elapsedRef = useRef(0);
  const hoveredRef = useRef<string | null>(null);
  const selectedIdRef = useRef<string | null>(null);
  const panelOpenRef = useRef(false);
  const repaintRef = useRef<() => void>(() => {});

  const selectedRepoId = selectedRepo?.id ?? null;

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

  const stars = useMemo(
    () =>
      repositories.map((repo, index) => ({
        repo,
        index,
        start: orbitPoint(starAngle(index, repositories.length, 0), shape),
      })),
    [repositories, shape],
  );

  const closePanel = useCallback((restoreFocus = false) => {
    setPanelState(null);
    setPanelPos(null);
    if (restoreFocus) panelTriggerRef.current?.focus({ preventScroll: true });
  }, []);

  const openPanel = useCallback(
    (repo: Repository, trigger: HTMLButtonElement) => {
      const rect = trigger.getBoundingClientRect();
      const heroRect = heroRef.current?.getBoundingClientRect();
      const contentRect = heroRef.current
        ?.querySelector('.cw-hero-content')
        ?.getBoundingClientRect();

      const centerX = rect.left + rect.width / 2;
      const centerY = rect.top + rect.height / 2;
      const minLeft = (heroRect?.left ?? 0) + 10;
      const maxLeft = window.innerWidth - PANEL_WIDTH - PANEL_MARGIN;
      const minTop = (heroRect?.top ?? 0) + 12;
      const maxTop = window.innerHeight - PANEL_HEIGHT - PANEL_MARGIN;

      const clamp = (value: number, min: number, max: number) =>
        Math.max(min, Math.min(value, max));

      const candidates: PanelPosition[] = [
        { left: rect.right + PANEL_GAP, top: centerY - PANEL_HEIGHT / 2 },
        { left: rect.left - PANEL_GAP - PANEL_WIDTH, top: centerY - PANEL_HEIGHT / 2 },
        { left: centerX - PANEL_WIDTH / 2, top: rect.top - PANEL_GAP - PANEL_HEIGHT },
        { left: centerX - PANEL_WIDTH / 2, top: rect.bottom + PANEL_GAP },
      ].map((candidate) => ({
        left: clamp(candidate.left, minLeft, maxLeft),
        top: clamp(candidate.top, minTop, Math.max(minTop, maxTop)),
      }));

      const overlapsContent = (candidate: PanelPosition) => {
        if (!contentRect || contentRect.width === 0) return false;
        const pad = 12;
        const right = candidate.left + PANEL_WIDTH;
        const bottom = candidate.top + PANEL_HEIGHT;
        return !(
          right < contentRect.left - pad ||
          candidate.left > contentRect.right + pad ||
          bottom < contentRect.top - pad ||
          candidate.top > contentRect.bottom + pad
        );
      };

      const position = candidates.find((candidate) => !overlapsContent(candidate)) ?? candidates[0];

      panelTriggerRef.current = trigger;
      setPanelPos(position);
      setPanelState({ repoId: repo.id, selectionAtOpen: selectedRepoId });
    },
    [selectedRepoId],
  );

  const panelRepoId = panelState?.repoId ?? null;
  const panelRepo = useMemo(
    () => (panelRepoId ? repositories.find((repo) => repo.id === panelRepoId) ?? null : null),
    [repositories, panelRepoId],
  );

  // The panel closes itself the moment the app's real selection moves, without
  // an extra state-syncing effect.
  const openPanelRepo =
    panelState && panelRepo && panelState.selectionAtOpen === selectedRepoId ? panelRepo : null;

  const panelBranch = openPanelRepo ? branchFromScope(openPanelRepo.scope) : null;
  const panelOwner = openPanelRepo ? ownerOf(openPanelRepo) : null;
  const panelRebuilt = openPanelRepo ? formatDate(openPanelRepo.last_rebuilt_at) : null;

  // One pointer + orbit loop drives star positions, proximity, waves and glow.
  useEffect(() => {
    const hero = heroRef.current;
    if (!hero) return;

    const reduceQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    const waveEls = Array.from(hero.querySelectorAll<SVGPathElement>('[data-cw-wave]'));
    const basePaths = waveEls.map((el) => el.getAttribute('d') ?? '');
    const glow = hero.querySelector<HTMLElement>('[data-cw-wave-glow]');
    const arcSvg = hero.querySelector<SVGSVGElement>('.cw-arc-svg');
    const selectedSeg = hero.querySelector<SVGPathElement>('[data-cw-seg="selected"]');
    const hoveredSeg = hero.querySelector<SVGPathElement>('[data-cw-seg="hovered"]');
    const pauseArc = () => {
      if (typeof arcSvg?.pauseAnimations === 'function') arcSvg.pauseAnimations();
    };
    const unpauseArc = () => {
      if (typeof arcSvg?.unpauseAnimations === 'function') arcSvg.unpauseAnimations();
    };
    if (document.hidden || reduceQuery.matches) pauseArc();

    const starEls = new Map<string, HTMLButtonElement>();
    hero.querySelectorAll<HTMLButtonElement>('[data-cw-repo]').forEach((el) => {
      const id = el.dataset.cwRepo;
      if (id) starEls.set(id, el);
    });

    const particles = Array.from(hero.querySelectorAll<SVGCircleElement>('.cw-particle')).map(
      (el) => ({
        el,
        x: Number(el.getAttribute('cx') ?? 0),
        y: Number(el.getAttribute('cy') ?? 0),
        base: Number(el.getAttribute('opacity') ?? 0.3),
        painted: -1,
      }),
    );
    const dust = Array.from(hero.querySelectorAll<HTMLElement>('.cw-orbit-dust')).map((el) => ({
      el,
      angle: Number(el.dataset.cwDustAngle ?? 0),
      painted: -1,
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
      last: 0,
      elapsed: elapsedRef.current,
      paths: [] as string[],
      angles: new Map<string, number>(),
    };

    const setNear = (el: HTMLElement | SVGElement, value: number, key: 'near' | 'paint') => {
      const previous = Number(el.dataset[`cw${key === 'near' ? 'Near' : 'Paint'}`] ?? 0);
      if (Math.abs(previous - value) < 0.012) return;
      el.dataset[`cw${key === 'near' ? 'Near' : 'Paint'}`] = value.toFixed(3);
      if (key === 'near') el.style.setProperty('--cw-near', value.toFixed(3));
      else el.style.filter = value > 0.02 ? `brightness(${(1 + value * 1.5).toFixed(2)})` : '';
    };

    const placeStar = (el: HTMLButtonElement, left: number, top: number) => {
      if (!el.dataset.cwPlaced) {
        el.dataset.cwPlaced = '1';
        el.style.left = '0';
        el.style.top = '0';
      }
      const px = (left / 100) * state.width;
      const py = (top / 100) * state.height;
      el.style.transform = `translate3d(${px.toFixed(2)}px, ${py.toFixed(2)}px, 0) translate(-50%, -50%)`;
    };

    const setFlag = (el: HTMLElement, name: string, on: boolean) => {
      if (el.classList.contains(name) !== on) el.classList.toggle(name, on);
    };

    const paintStars = () => {
      for (const star of stars) {
        const angle = starAngle(star.index, stars.length, state.elapsed);
        const point = orbitPoint(angle, shape);
        state.angles.set(star.repo.id, angle);

        const el = starEls.get(star.repo.id);
        if (!el) continue;
        placeStar(el, point.left, point.top);
        setFlag(el, 'is-tip-left', point.left < 20);
        setFlag(el, 'is-tip-right', point.left > 80);
        setFlag(el, 'is-tip-below', point.top < 26);

        if (state.width > 0 && state.height > 0) {
          const dx = state.x - (point.left / 100) * state.width;
          const dy = state.y - (point.top / 100) * state.height;
          const closeness = Math.max(0, 1 - Math.hypot(dx, dy) / STAR_RADIUS);
          setNear(el, closeness ** 1.7 * state.energy, 'near');
        } else {
          setNear(el, 0, 'near');
        }
      }
    };

    const paintHighlights = () => {
      const selectedAngle = selectedIdRef.current
        ? state.angles.get(selectedIdRef.current)
        : undefined;
      if (selectedSeg) {
        selectedSeg.setAttribute(
          'd',
          selectedAngle === undefined ? '' : arcSegmentPath(selectedAngle, 6, shape),
        );
      }
      const hoveredAngle = hoveredRef.current ? state.angles.get(hoveredRef.current) : undefined;
      if (hoveredSeg) {
        hoveredSeg.setAttribute(
          'd',
          hoveredAngle === undefined ? '' : arcSegmentPath(hoveredAngle, 6, shape),
        );
      }
    };

    const toBackdrop = () => {
      const scale = Math.max(state.width / 1600, state.height / 900);
      const offsetX = (state.width - 1600 * scale) / 2;
      const offsetY = (state.height - 900 * scale) / 2;
      return { scale, offsetX, offsetY };
    };

    const paintWaves = () => {
      if (state.width === 0 || state.height === 0) return;
      const { scale, offsetX, offsetY } = toBackdrop();
      const influences: WaveInfluence[] = [];

      if (state.energy > 0.004) {
        influences.push({
          x: (state.x - offsetX) / Math.max(scale, 0.0001),
          y: (state.y - offsetY) / Math.max(scale, 0.0001),
          energy: state.energy,
          reach: 300,
        });
      }

      const hoveredAngle = hoveredRef.current ? state.angles.get(hoveredRef.current) : undefined;
      let focusPoint: { x: number; y: number } | null = null;
      if (hoveredAngle !== undefined) {
        const point = orbitPoint(hoveredAngle, shape);
        const px = (point.left / 100) * state.width;
        const py = (point.top / 100) * state.height;
        focusPoint = {
          x: (px - offsetX) / Math.max(scale, 0.0001),
          y: (py - offsetY) / Math.max(scale, 0.0001),
        };
        influences.push({ ...focusPoint, energy: 0.6, reach: 260 });
      }

      for (let i = 0; i < waveEls.length; i += 1) {
        const next =
          influences.length > 0
            ? deformWave(WAVE_FIELD[i].points, influences)
            : basePaths[i];
        if (state.paths[i] !== next) {
          waveEls[i].setAttribute('d', next);
          state.paths[i] = next;
        }
      }

      if (glow) {
        if (focusPoint) {
          const px = focusPoint.x * scale + offsetX;
          const py = focusPoint.y * scale + offsetY;
          glow.style.transform = `translate3d(${px - 310}px, ${py - 310}px, 0)`;
          glow.style.opacity = (0.34 + state.energy * 0.12).toFixed(3);
        } else {
          const gate = Math.min(
            1,
            Math.max(0, (state.y / Math.max(state.height, 1) - 0.42) / 0.18),
          );
          glow.style.transform = `translate3d(${state.x - 310}px, ${state.y - 310}px, 0)`;
          glow.style.opacity = (state.energy * gate * 0.9).toFixed(3);
        }
      }
    };

    const paintParticles = () => {
      if (state.width === 0 || state.height === 0 || state.energy <= 0.004) {
        for (const particle of particles) {
          if (particle.painted !== 0) {
            particle.el.style.filter = '';
            particle.painted = 0;
          }
        }
        return;
      }
      const { scale, offsetX, offsetY } = toBackdrop();
      const px = (state.x - offsetX) / Math.max(scale, 0.0001);
      const py = (state.y - offsetY) / Math.max(scale, 0.0001);
      for (const particle of particles) {
        const distance = Math.hypot(particle.x - px, particle.y - py);
        const near = Math.max(0, 1 - distance / 130) * state.energy;
        setNear(particle.el, near, 'paint');
      }
    };

    const paintDust = () => {
      if (state.width === 0 || state.height === 0) return;
      for (const item of dust) {
        const point = orbitPoint(item.angle, shape);
        const dx = state.x - (point.left / 100) * state.width;
        const dy = state.y - (point.top / 100) * state.height;
        const near = Math.max(0, 1 - Math.hypot(dx, dy) / 150) * state.energy;
        setNear(item.el, near, 'paint');
      }
    };

    const paintAll = () => {
      paintStars();
      paintHighlights();
      paintWaves();
      paintParticles();
      paintDust();
    };

    const orbiting = () =>
      !reduceQuery.matches && !panelOpenRef.current && !hoveredRef.current;

    const frame = (now: number) => {
      state.raf = 0;
      if (!state.visible) return;

      const dt = state.last ? Math.min(64, now - state.last) : 16;
      state.last = now;
      if (orbiting()) state.elapsed += dt;

      state.x += (state.targetX - state.x) * 0.18;
      state.y += (state.targetY - state.y) * 0.18;
      const targetEnergy = state.inside ? 1 : 0;
      state.energy += (targetEnergy - state.energy) * 0.1;
      if (!state.inside && state.energy < 0.008) state.energy = 0;

      paintAll();

      const steady =
        Math.abs(state.targetX - state.x) < 0.4 &&
        Math.abs(state.targetY - state.y) < 0.4 &&
        Math.abs(targetEnergy - state.energy) < 0.01;

      if (orbiting() || !steady) state.raf = requestAnimationFrame(frame);
    };

    const schedule = () => {
      if (state.raf || !state.visible) return;
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
      paintAll();
    };

    const handleVisibility = () => {
      state.visible = !document.hidden;
      hero.classList.toggle('is-paused', !state.visible);
      if (state.visible) {
        state.last = 0;
        if (!reduceQuery.matches) unpauseArc();
        schedule();
      } else {
        if (state.raf) cancelAnimationFrame(state.raf);
        state.raf = 0;
        pauseArc();
      }
    };

    const handleMotionPreference = () => {
      if (!reduceQuery.matches) {
        if (!document.hidden) unpauseArc();
        schedule();
        return;
      }
      pauseArc();
      if (state.raf) cancelAnimationFrame(state.raf);
      state.raf = 0;
      state.inside = false;
      state.energy = 0;
      state.x = state.targetX;
      state.y = state.targetY;
      paintAll();
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

    repaintRef.current = schedule;
    if (orbiting()) schedule();
    else paintAll();

    return () => {
      if (state.raf) cancelAnimationFrame(state.raf);
      elapsedRef.current = state.elapsed;
      repaintRef.current = () => {};
      hero.removeEventListener('pointermove', handleMove);
      hero.removeEventListener('pointerleave', handleLeave);
      hero.removeEventListener('pointercancel', handleLeave);
      document.removeEventListener('visibilitychange', handleVisibility);
      reduceQuery.removeEventListener('change', handleMotionPreference);
      observer.disconnect();
      hero.classList.remove('is-paused');
    };
  }, [stars, shape]);

  // Mirror interaction state into refs and repaint once (no React render per frame).
  useEffect(() => {
    hoveredRef.current = hoveredRepoId;
    panelOpenRef.current = panelRepoId !== null;
    repaintRef.current();
  }, [hoveredRepoId, panelRepoId]);

  useEffect(() => {
    selectedIdRef.current = selectedRepoId;
    repaintRef.current();
  }, [selectedRepoId]);

  // Dismiss the panel on Escape, outside press, or a viewport change.
  useEffect(() => {
    if (!panelRepoId) return;

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      closePanel(true);
    };
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (!target) return;
      if (panelRef.current?.contains(target)) return;
      if ((target as Element).closest?.('[data-cw-repo]')) return;
      closePanel(false);
    };
    const onResize = () => closePanel(false);

    document.addEventListener('keydown', onKeyDown);
    document.addEventListener('pointerdown', onPointerDown, true);
    window.addEventListener('resize', onResize);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.removeEventListener('pointerdown', onPointerDown, true);
      window.removeEventListener('resize', onResize);
    };
  }, [panelRepoId, closePanel]);

  // Move focus into the panel so keyboard users land on its content.
  useEffect(() => {
    if (!panelRepoId) return;
    panelRef.current?.focus({ preventScroll: true });
  }, [panelRepoId]);

  const handleSwitch = () => {
    if (!openPanelRepo) return;
    onSelectRepo?.(openPanelRepo);
    closePanel(true);
  };

  return (
    <section
      className={`cw-hero${panelRepoId ? ' is-panel-open' : ''}`}
      ref={heroRef}
    >
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
          <path
            data-cw-seg="selected"
            className={`cw-arc-seg${selectedRepoId ? ' is-selected' : ''}`}
            d=""
            fill="none"
            stroke="#B9915E"
            strokeWidth="1.7"
            strokeLinecap="round"
            vectorEffect="non-scaling-stroke"
          />
          <path
            data-cw-seg="hovered"
            className={`cw-arc-seg${hoveredRepoId ? ' is-hovered' : ''}`}
            d=""
            fill="none"
            stroke="#E2C79B"
            strokeWidth="1.7"
            strokeLinecap="round"
            vectorEffect="non-scaling-stroke"
          />
        </svg>

        {ORBIT_DUST.map((dust) => {
          const point = orbitPoint(dust.angle, shape);
          return (
            <span
              key={dust.angle}
              className="cw-orbit-dust"
              aria-hidden="true"
              data-cw-dust-angle={dust.angle}
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
            {stars.map(({ repo, start }, index) => {
              const isSelected = selectedRepoId === repo.id;
              const isOpen = panelRepoId === repo.id;
              const branch = branchFromScope(repo.scope);
              return (
                <button
                  key={repo.id}
                  type="button"
                  data-cw-repo={repo.id}
                  className={`cw-repo-star${isSelected ? ' is-selected' : ''}`}
                  style={{ left: `${start.left}%`, top: `${start.top}%` }}
                  aria-label={`Repository ${repo.name}, ${
                    isSelected ? 'current repository' : 'switch repository'
                  }${branch ? `, branch ${branch}` : ''}`}
                  aria-haspopup="dialog"
                  aria-expanded={isOpen}
                  aria-controls={isOpen ? 'cw-repo-panel' : undefined}
                  aria-describedby={`cw-repo-tip-${index}`}
                  onPointerEnter={() => setHoveredRepoId(repo.id)}
                  onPointerLeave={() =>
                    setHoveredRepoId((current) => (current === repo.id ? null : current))
                  }
                  onFocus={() => setHoveredRepoId(repo.id)}
                  onBlur={() =>
                    setHoveredRepoId((current) => (current === repo.id ? null : current))
                  }
                  onClick={(event) => {
                    if (isOpen) {
                      closePanel(true);
                      return;
                    }
                    openPanel(repo, event.currentTarget);
                  }}
                >
                  <span className="cw-star-halo" aria-hidden="true" />
                  <span className="cw-star-ring" aria-hidden="true" />
                  <span className="cw-star-dot" aria-hidden="true" />
                  <span className="cw-star-tip" id={`cw-repo-tip-${index}`} role="tooltip">
                    <span className="cw-tip-head">
                      <GitBranch className="cw-tip-icon" aria-hidden="true" />
                      <span className="cw-tip-kind">Repository</span>
                    </span>
                    <span className="cw-tip-name">{repo.name}</span>
                    <span className={`cw-tip-state${isSelected ? ' is-current' : ''}`}>
                      {isSelected ? 'Current repository' : 'Switch repository'}
                    </span>
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

      {openPanelRepo && panelPos && (
        <div
          ref={panelRef}
          id="cw-repo-panel"
          className="cw-repo-panel"
          role="dialog"
          aria-modal="false"
          aria-labelledby="cw-repo-panel-title"
          tabIndex={-1}
          style={
            {
              '--cw-panel-left': `${panelPos.left}px`,
              '--cw-panel-top': `${panelPos.top}px`,
            } as React.CSSProperties
          }
        >
          <button
            type="button"
            className="cw-panel-close"
            aria-label={`Close details for ${openPanelRepo.name}`}
            onClick={() => closePanel(true)}
          >
            <X className="h-3.5 w-3.5" aria-hidden="true" />
          </button>

          <p className="cw-panel-eyebrow">
            <GitBranch className="h-3 w-3" aria-hidden="true" />
            <span>Repository</span>
            {openPanelRepo.fixture && <span className="cw-panel-fixture">fixture</span>}
          </p>

          <h2 className="cw-panel-title" id="cw-repo-panel-title">
            {openPanelRepo.name}
          </h2>

          <dl className="cw-panel-meta">
            {panelOwner && (
              <>
                <dt>Owner</dt>
                <dd>{panelOwner}</dd>
              </>
            )}
            {panelBranch && (
              <>
                <dt>Branch</dt>
                <dd>{panelBranch}</dd>
              </>
            )}
            <dt>URL</dt>
            <dd>
              <a
                className="cw-panel-url"
                href={openPanelRepo.url}
                target="_blank"
                rel="noreferrer noopener"
              >
                <span>{openPanelRepo.url.replace(/^https?:\/\//, '')}</span>
                <ExternalLink className="h-3 w-3" aria-hidden="true" />
              </a>
            </dd>
          </dl>

          <div className="cw-panel-counts">
            <span>
              <strong>{openPanelRepo.counts.decisions}</strong> decisions
            </span>
            <span>
              <strong>{openPanelRepo.counts.entities}</strong> entities
            </span>
            <span>
              <strong>{openPanelRepo.counts.pull_requests}</strong> PRs
            </span>
            <span>
              <strong>{openPanelRepo.counts.commits}</strong> commits
            </span>
          </div>

          {(openPanelRepo.sources_analyzed != null || panelRebuilt) && (
            <p className="cw-panel-note">
              {openPanelRepo.sources_analyzed != null && (
                <span>{openPanelRepo.sources_analyzed} sources analyzed</span>
              )}
              {panelRebuilt && <span>Rebuilt {panelRebuilt}</span>}
            </p>
          )}

          <div className="cw-panel-actions">
            {selectedRepoId === openPanelRepo.id ? (
              <span className="cw-panel-selected">
                <Check className="h-3.5 w-3.5" aria-hidden="true" />
                Current repository
              </span>
            ) : (
              <button type="button" className="cw-panel-switch" onClick={handleSwitch}>
                Switch to repository
                <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
            )}
          </div>
        </div>
      )}
    </section>
  );
};
