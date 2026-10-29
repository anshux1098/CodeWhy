import React from 'react';
import { Logo } from './Logo';
import { ShieldCheck, GitBranch, Layers } from 'lucide-react';

export const Footer: React.FC = () => {
  return (
    <footer className="border-t py-10 px-4 sm:px-6 lg:px-8 bg-[#080907] border-[#292A23] text-[#F5F3ED]">
      <div className="max-w-6xl mx-auto flex flex-col md:flex-row items-center justify-between gap-6">
        
        {/* Brand */}
        <div className="flex flex-col items-center md:items-start gap-1 text-center md:text-left">
          <Logo size="sm" variant="landing" />
          <p className="text-xs max-w-sm mt-1 text-[#A5A69D]">
            Git decision archeology engine reconstructing historical rationale from commits, PRs, reviews, and ADRs.
          </p>
        </div>

        {/* Guarantees */}
        <div className="flex flex-wrap items-center justify-center gap-2.5 text-xs font-mono">
          <span className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#757F6C]/15 border border-[#2ea043]/30 text-[#F5F3ED] shadow-sm">
            <ShieldCheck className="w-3.5 h-3.5 text-[#3fb950]" />
            <span>Verbatim Quote Verification</span>
          </span>
          <span className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#12130F] border border-[#B9915E]/30 text-[#F5F3ED] shadow-sm">
            <GitBranch className="w-3.5 h-3.5 text-[#B9915E]" />
            <span>Temporal Decision Lineage</span>
          </span>
          <span className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#12130F] border border-[#8C806F]/40 text-[#F5F3ED] shadow-sm">
            <Layers className="w-3.5 h-3.5 text-[#8C806F]" />
            <span>Principled Refusal Gates</span>
          </span>
        </div>

        {/* Links & Copyright */}
        <div className="text-xs font-mono text-center md:text-right text-[#A5A69D]">
          <p className="text-[#F5F3ED] font-medium">© {new Date().getFullYear()} CodeWhy Engine</p>
          <p className="text-[11px] mt-0.5 text-[#A5A69D]">
            Grounded in Character-Verified Artifacts
          </p>
        </div>

      </div>
    </footer>
  );
};
