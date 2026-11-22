import React from 'react';
import { Logo } from './Logo';
import { ShieldCheck, GitBranch, Layers } from 'lucide-react';

export const Footer: React.FC = () => {
  return (
    <footer className="border-t py-10 px-4 sm:px-6 lg:px-8 bg-[#242038] border-[#CAC4CE]/20 text-[#F7ECE1]">
      <div className="max-w-6xl mx-auto flex flex-col md:flex-row items-center justify-between gap-6">
        
        {/* Brand */}
        <div className="flex flex-col items-center md:items-start gap-1 text-center md:text-left">
          <Logo size="sm" variant="landing" />
          <p className="text-xs max-w-sm mt-1 text-[#CAC4CE]">
            Git decision archeology engine reconstructing historical rationale from commits, PRs, reviews, and ADRs.
          </p>
        </div>

        {/* Guarantees */}
        <div className="flex flex-wrap items-center justify-center gap-2.5 text-xs font-mono">
          <span className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#161324] border border-[#3fb950]/35 text-[#F7ECE1] shadow-sm">
            <ShieldCheck className="w-3.5 h-3.5 text-[#3fb950]" />
            <span>Verbatim Quote Verification</span>
          </span>
          <span className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#161324] border border-[#9067C6]/45 text-[#F7ECE1] shadow-sm">
            <GitBranch className="w-3.5 h-3.5 text-[#9067C6]" />
            <span>Temporal Decision Lineage</span>
          </span>
          <span className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#161324] border border-[#8D86C9]/45 text-[#F7ECE1] shadow-sm">
            <Layers className="w-3.5 h-3.5 text-[#8D86C9]" />
            <span>Principled Refusal Gates</span>
          </span>
        </div>

        {/* Links & Copyright */}
        <div className="text-xs font-mono text-center md:text-right text-[#CAC4CE]">
          <p className="text-[#F7ECE1] font-medium">© {new Date().getFullYear()} CodeWhy Engine</p>
          <p className="text-[11px] mt-0.5 text-[#CAC4CE]">
            Grounded in Character-Verified Artifacts
          </p>
        </div>

      </div>
    </footer>
  );
};
