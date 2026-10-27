import React from 'react';
import { 
  ShieldCheck, 
  Layers, 
  Quote, 
  CheckCircle2,
  Sparkles,
  Database,
  Filter,
  Search,
  Cpu,
  ArrowRight,
} from 'lucide-react';
import { Logo } from './Logo';

interface HeroProps {
  onNavigateToWorkspace?: (initialQuestion?: string) => void;
}

const PIPELINE_STEPS = [
  {
    num: '01',
    title: 'Target Ingestion',
    desc: 'Clones repository history and builds local resumable SQLite cache with SHA-256 deduplication.',
    badge: 'Git + SQLite',
    icon: Database,
    color: 'var(--evidence-emerald)',
  },
  {
    num: '02',
    title: 'Noise Elimination',
    desc: '8 heuristic detectors discard bot bumps, lint-only PRs, and mechanical merges.',
    badge: 'Noise Filter',
    icon: Filter,
    color: 'var(--primary-container)',
  },
  {
    num: '03',
    title: 'AST Entity Mapping',
    desc: 'Extracts Python AST modules, constants, and classes with full historical change paths.',
    badge: 'AST Parser',
    icon: Search,
    color: 'var(--entity-cyan)',
  },
  {
    num: '04',
    title: 'Verbatim Quote Gate',
    desc: 'Mines PR descriptions, code reviews, and ADRs with mandatory character-level quote matching.',
    badge: 'Substring Gate',
    icon: Cpu,
    color: 'var(--rationale-amber)',
  },
  {
    num: '05',
    title: 'Lineage Graph',
    desc: 'Indexes supersession chains (REVERTS, SUPERSEDES, RELIES_ON) into a knowledge property graph.',
    badge: 'Knowledge Graph',
    icon: ShieldCheck,
    color: 'var(--entity-cyan)',
  },
];

export const Hero: React.FC<HeroProps> = ({
  onNavigateToWorkspace,
}) => {
  return (
    <>
      {/* ── Hero Section ── */}
      <section
        className="relative px-4 sm:px-6 lg:px-8 py-16 sm:py-20 text-center"
        style={{
          background: 'linear-gradient(180deg, var(--surface-lowest) 0%, var(--canvas) 60%, var(--surface) 100%)',
          borderBottom: '1px solid var(--border)',
        }}
      >
        {/* Radial glow */}
        <div
          style={{
            position: 'absolute',
            top: 0,
            left: '50%',
            transform: 'translateX(-50%)',
            width: '800px',
            height: '500px',
            background: 'radial-gradient(ellipse at center top, rgba(6,182,212,0.07) 0%, transparent 65%)',
            pointerEvents: 'none',
          }}
        />

        <div className="max-w-4xl mx-auto flex flex-col items-center relative">

          {/* Top pill badge */}
          <div
            className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full text-xs font-mono mb-8"
            style={{
              background: 'var(--cyan-soft)',
              border: '1px solid var(--cyan-border)',
              color: 'var(--entity-cyan)',
              letterSpacing: '0.08em',
            }}
          >
            <Sparkles className="w-3 h-3" />
            <span style={{ textTransform: 'uppercase', fontWeight: 500 }}>
              Code Archeology &amp; Temporal Decision Provenance
            </span>
          </div>

          {/* CW Logo icon */}
          <div className="mb-6">
            <Logo size="xl" showText={false} showTagline={false} />
          </div>

          {/* CodeWhy wordmark */}
          <h1
            style={{
              fontFamily: "'Inter', sans-serif",
              fontWeight: 800,
              fontSize: 'clamp(3rem, 8vw, 5.5rem)',
              letterSpacing: '-0.03em',
              lineHeight: 1.05,
              margin: '0 0 20px',
            }}
          >
            <span style={{ color: 'var(--text)' }}>Code</span>
            <span
              style={{
                background: 'var(--brand-gradient)',
                WebkitBackgroundClip: 'text',
                WebkitTextFillColor: 'transparent',
                backgroundClip: 'text',
              }}
            >
              Why
            </span>
          </h1>

          {/* Italic quote tagline */}
          <p
            style={{
              fontFamily: "'Inter', sans-serif",
              fontSize: 'clamp(1rem, 2.5vw, 1.35rem)',
              fontStyle: 'italic',
              fontWeight: 400,
              color: 'var(--text-muted)',
              maxWidth: '620px',
              lineHeight: 1.6,
              margin: '0 0 40px',
            }}
          >
            "Every line has a history.{' '}
            <span style={{ color: 'var(--text)', fontWeight: 500 }}>
              Find the reasoning, not just the code.
            </span>"
          </p>

          {/* Start Investigating CTA */}
          <button
            type="button"
            onClick={() => onNavigateToWorkspace && onNavigateToWorkspace()}
            className="cursor-pointer inline-flex items-center gap-2"
            style={{
              padding: '11px 28px',
              borderRadius: '10px',
              background: 'var(--brand-gradient)',
              color: 'var(--surface-lowest)',
              fontWeight: 700,
              fontSize: '14px',
              fontFamily: "'Inter', sans-serif",
              border: 'none',
              letterSpacing: '0.01em',
              boxShadow: '0 0 24px var(--accent-glow)',
            }}
          >
            <span>Start Investigating</span>
            <ArrowRight className="w-4 h-4" />
          </button>

          {/* 3 Guarantee Cards */}
          <div className="mt-16 grid grid-cols-1 md:grid-cols-3 gap-4 w-full text-left">

            <div
              className="p-5 rounded-xl flex flex-col justify-between transition-all"
              style={{ background: 'var(--surface-card)', border: '1px solid var(--border)' }}
              onMouseEnter={e => (e.currentTarget as HTMLDivElement).style.borderColor = 'color-mix(in srgb, var(--primary-container) 40%, transparent)'}
              onMouseLeave={e => (e.currentTarget as HTMLDivElement).style.borderColor = 'var(--border)'}
            >
              <div>
                <div className="w-8 h-8 rounded-lg flex items-center justify-center mb-3.5"
                  style={{ background: 'var(--violet-soft)', border: '1px solid var(--violet-border)' }}>
                  <Layers className="w-4 h-4" style={{ color: 'var(--primary-container)' }} />
                </div>
                <h3 className="text-sm font-semibold mb-1.5" style={{ color: 'var(--text)' }}>
                  Excavate Why, Not Just Who
                </h3>
                <p className="text-xs leading-relaxed" style={{ color: 'var(--text-muted)' }}>
                  Git blame tells you who modified a line. CodeWhy excavates the original PR debates, trade-offs, and architecture decisions that explain <i>why</i>.
                </p>
              </div>
              <div className="mt-4 pt-3 text-[11px] font-mono" style={{ borderTop: '1px solid var(--border)', color: 'var(--primary-container)' }}>
                PR &amp; ADR Archeology
              </div>
            </div>

            <div
              className="p-5 rounded-xl flex flex-col justify-between transition-all"
              style={{ background: 'var(--surface-card)', border: '1px solid var(--border)' }}
              onMouseEnter={e => (e.currentTarget as HTMLDivElement).style.borderColor = 'color-mix(in srgb, var(--evidence-emerald) 40%, transparent)'}
              onMouseLeave={e => (e.currentTarget as HTMLDivElement).style.borderColor = 'var(--border)'}
            >
              <div>
                <div className="w-8 h-8 rounded-lg flex items-center justify-center mb-3.5"
                  style={{ background: 'var(--emerald-soft)', border: '1px solid var(--emerald-border)' }}>
                  <Quote className="w-4 h-4" style={{ color: 'var(--evidence-emerald)' }} />
                </div>
                <h3 className="text-sm font-semibold mb-1.5" style={{ color: 'var(--text)' }}>
                  100% Verbatim Quotes
                </h3>
                <p className="text-xs leading-relaxed" style={{ color: 'var(--text-muted)' }}>
                  No generic AI speculation. Every citation is validated character-by-character against actual commit messages and pull request review threads.
                </p>
              </div>
              <div className="mt-4 pt-3 text-[11px] font-mono flex items-center gap-1.5" style={{ borderTop: '1px solid var(--border)', color: 'var(--evidence-emerald)' }}>
                <CheckCircle2 className="w-3 h-3" />
                <span>Zero Hallucinations</span>
              </div>
            </div>

            <div
              className="p-5 rounded-xl flex flex-col justify-between transition-all"
              style={{ background: 'var(--surface-card)', border: '1px solid var(--border)' }}
              onMouseEnter={e => (e.currentTarget as HTMLDivElement).style.borderColor = 'color-mix(in srgb, var(--primary) 40%, transparent)'}
              onMouseLeave={e => (e.currentTarget as HTMLDivElement).style.borderColor = 'var(--border)'}
            >
              <div>
                <div className="w-8 h-8 rounded-lg flex items-center justify-center mb-3.5"
                  style={{ background: 'var(--accent-soft)', border: '1px solid var(--accent-glow)' }}>
                  <ShieldCheck className="w-4 h-4" style={{ color: 'var(--primary)' }} />
                </div>
                <h3 className="text-sm font-semibold mb-1.5" style={{ color: 'var(--text)' }}>
                  Principled Refusal Gates
                </h3>
                <p className="text-xs leading-relaxed" style={{ color: 'var(--text-muted)' }}>
                  If reasoning was never recorded or evidence is contradictory, CodeWhy refuses honestly through 4 verification gates instead of guessing.
                </p>
              </div>
              <div className="mt-4 pt-3 text-[11px] font-mono" style={{ borderTop: '1px solid var(--border)', color: 'var(--primary)' }}>
                4-Gate Verification
              </div>
            </div>

          </div>
        </div>
      </section>

      {/* ── Archeology Pipeline Section ── */}
      <section
        className="py-16 px-4 sm:px-6 lg:px-8"
        style={{ background: 'var(--surface)', borderBottom: '1px solid var(--border)' }}
      >
        <div className="max-w-6xl mx-auto">

          {/* Section header */}
          <div className="text-center max-w-2xl mx-auto mb-12">
            <div
              className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-mono mb-4"
              style={{
                background: 'var(--accent-soft)',
                border: '1px solid var(--accent-glow)',
                color: 'var(--primary)',
                letterSpacing: '0.08em',
              }}
            >
              <Layers className="w-3 h-3" />
              <span style={{ textTransform: 'uppercase' }}>Pipeline Architecture</span>
            </div>
            <h2
              style={{
                fontFamily: "'Inter', sans-serif",
                fontWeight: 700,
                fontSize: 'clamp(1.5rem, 3vw, 2rem)',
                color: 'var(--text)',
                letterSpacing: '-0.02em',
                margin: '0 0 12px',
              }}
            >
              The Code Archeology Pipeline
            </h2>
            <p style={{ fontSize: '14px', color: 'var(--text-muted)', lineHeight: 1.6, margin: 0 }}>
              From raw Git commits to validated architectural provenance through a zero-hallucination extraction flow.
            </p>
          </div>

          {/* Steps */}
          <div className="grid grid-cols-1 md:grid-cols-5 gap-3">
            {PIPELINE_STEPS.map((step, idx) => {
              const Icon = step.icon;
              return (
                <div
                  key={idx}
                  className="rounded-xl p-4 flex flex-col justify-between transition-all"
                  style={{ background: 'var(--surface-card)', border: '1px solid var(--border)' }}
                  onMouseEnter={e => {
                    (e.currentTarget as HTMLDivElement).style.borderColor = `color-mix(in srgb, ${step.color} 35%, transparent)`;
                    (e.currentTarget as HTMLDivElement).style.boxShadow = `0 0 16px color-mix(in srgb, ${step.color} 12%, transparent)`;
                  }}
                  onMouseLeave={e => {
                    (e.currentTarget as HTMLDivElement).style.borderColor = 'var(--border)';
                    (e.currentTarget as HTMLDivElement).style.boxShadow = 'none';
                  }}
                >
                  <div>
                    <div className="flex items-center justify-between mb-3">
                      <span
                        className="font-mono text-[10px] font-bold px-2 py-0.5 rounded"
                        style={{
                          color: step.color,
                          background: `color-mix(in srgb, ${step.color} 12%, transparent)`,
                          border: `1px solid color-mix(in srgb, ${step.color} 30%, transparent)`,
                        }}
                      >
                        STAGE {step.num}
                      </span>
                      <div
                        className="p-1.5 rounded-lg"
                        style={{
                          background: `color-mix(in srgb, ${step.color} 12%, transparent)`,
                          border: `1px solid color-mix(in srgb, ${step.color} 25%, transparent)`,
                        }}
                      >
                        <Icon className="w-3.5 h-3.5" style={{ color: step.color }} />
                      </div>
                    </div>

                    <h3 style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text)', marginBottom: '6px', fontFamily: "'Inter', sans-serif" }}>
                      {step.title}
                    </h3>
                    <p style={{ fontSize: '11px', color: 'var(--text-muted)', lineHeight: 1.6 }}>
                      {step.desc}
                    </p>
                  </div>

                  <div
                    className="pt-2.5 mt-3 flex items-center justify-between"
                    style={{ borderTop: '1px solid var(--border)' }}
                  >
                    <span style={{ fontSize: '10px', fontFamily: 'monospace', color: step.color, textTransform: 'uppercase' }}>
                      {step.badge}
                    </span>
                    {idx < PIPELINE_STEPS.length - 1 && (
                      <ArrowRight className="w-3.5 h-3.5 hidden md:block" style={{ color: 'var(--text-subtle)' }} />
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </section>
    </>
  );
};
