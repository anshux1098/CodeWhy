import React from 'react';
import { ArrowRight, Sparkles } from 'lucide-react';
import { Logo } from './Logo';

interface HeroProps {
  onNavigateToWorkspace?: (initialQuestion?: string) => void;
}

export const Hero: React.FC<HeroProps> = ({ onNavigateToWorkspace }) => (
  <section className="relative isolate flex min-h-[calc(100vh-4rem)] items-center justify-center overflow-hidden border-b border-[var(--border)] bg-[var(--canvas)] px-5 py-16 sm:px-8 lg:px-12">
    <div
      aria-hidden="true"
      className="pointer-events-none absolute left-1/2 top-0 -z-10 h-[560px] w-full max-w-5xl -translate-x-1/2"
      style={{
        background:
          'radial-gradient(circle at 50% 10%, rgba(240, 68, 43, 0.12) 0%, rgba(233, 147, 11, 0.05) 45%, transparent 70%)',
      }}
    />
    <div
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 -z-10 opacity-35"
      style={{
        backgroundImage: 'radial-gradient(var(--border-strong) 0.8px, transparent 0.8px)',
        backgroundSize: '24px 24px',
        maskImage: 'radial-gradient(ellipse at 50% 35%, black 20%, transparent 80%)',
      }}
    />

    <div className="mx-auto flex w-full max-w-4xl flex-col items-center text-center">
      <div className="mb-8 inline-flex max-w-full items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--surface)] px-4 py-2 text-xs font-semibold tracking-wider text-[var(--text-muted)] shadow-sm">
        <Sparkles className="h-3.5 w-3.5 shrink-0 text-[var(--primary)]" />
        <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-[var(--text-subtle)] sm:text-[11px]">
          Code archeology &amp; temporal decision provenance
        </span>
      </div>

      <div className="relative mb-6">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 scale-150 rounded-3xl opacity-50 blur-2xl"
          style={{
            background:
              'radial-gradient(circle, rgba(240, 68, 43, 0.24) 0%, rgba(233, 147, 11, 0.13) 50%, transparent 76%)',
          }}
        />
        <Logo size="xl" showText={false} showTagline={false} className="relative" />
      </div>

      <h1 className="text-balance text-6xl font-extrabold tracking-[-0.055em] sm:text-7xl lg:text-8xl">
        <span className="text-[var(--text)]">Code</span>
        <span className="bg-gradient-to-r from-[var(--primary)] via-[#ff6b4a] to-[var(--rationale-amber)] bg-clip-text text-transparent">
          Why
        </span>
      </h1>

      <p className="mt-6 max-w-3xl text-balance text-xl font-normal italic leading-relaxed text-[var(--text-muted)] sm:text-2xl">
        &ldquo;Every line has a history. Find the reasoning, not just the code.&rdquo;
      </p>

      <button
        type="button"
        onClick={() => onNavigateToWorkspace?.()}
        className="group mt-10 inline-flex cursor-pointer items-center gap-3 rounded-xl bg-[var(--primary)] px-7 py-3.5 text-base font-bold text-white shadow-[0_12px_30px_rgba(240,68,43,0.22)] transition hover:-translate-y-0.5 hover:bg-[var(--primary-container)]"
      >
        <span>Start investigation</span>
        <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
      </button>
    </div>
  </section>
);
