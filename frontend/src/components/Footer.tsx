import React from 'react';
import { Logo } from './Logo';
import { ShieldCheck, GitBranch, Layers } from 'lucide-react';

export const Footer: React.FC = () => {
  return (
    <footer
      className="border-t py-10 px-4 sm:px-6 lg:px-8"
      style={{
        backgroundColor: 'var(--surface)',
        borderColor: 'var(--border)',
      }}
    >
      <div className="max-w-6xl mx-auto flex flex-col md:flex-row items-center justify-between gap-6">
        
        {/* Brand */}
        <div className="flex flex-col items-center md:items-start gap-1 text-center md:text-left">
          <Logo size="sm" />
          <p className="text-xs max-w-sm mt-1" style={{ color: 'var(--text-muted)' }}>
            Git decision archeology engine reconstructing historical rationale from commits, PRs, reviews, and ADRs.
          </p>
        </div>

        {/* Guarantees */}
        <div className="flex flex-wrap items-center justify-center gap-2.5 text-xs font-mono">
          <span className="badge-emerald flex items-center gap-1.5 px-3 py-1 rounded-lg">
            <ShieldCheck className="w-3.5 h-3.5 text-emerald-500" />
            Verbatim Quote Verification
          </span>
          <span className="badge-violet flex items-center gap-1.5 px-3 py-1 rounded-lg">
            <GitBranch className="w-3.5 h-3.5 text-violet-500" />
            Temporal Decision Lineage
          </span>
          <span className="badge-violet flex items-center gap-1.5 px-3 py-1 rounded-lg">
            <Layers className="w-3.5 h-3.5 text-[var(--primary)]" />
            Principled Refusal Gates
          </span>
        </div>

        {/* Links & Copyright */}
        <div className="text-xs font-mono text-center md:text-right" style={{ color: 'var(--text-muted)' }}>
          <p>© {new Date().getFullYear()} CodeWhy Engine</p>
          <p className="text-[11px] mt-0.5" style={{ color: 'var(--text-subtle)' }}>
            Grounded in Character-Verified Artifacts
          </p>
        </div>

      </div>
    </footer>
  );
};
