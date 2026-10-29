import React from 'react';
import { 
  Quote, 
  History, 
  ShieldCheck, 
  GitBranch, 
  Layers,
  CheckCircle2,
  XCircle,
} from 'lucide-react';

export const PillarsSection: React.FC = () => {
  const pillars = [
    {
      icon: History,
      color: 'violet',
      badgeClass: 'badge-violet',
      borderClass: 'stat-card-violet',
      tag: 'BEYOND GIT BLAME',
      title: 'Excavate "Why", Not Just "Who"',
      description:
        'Traditional git blame tells you who modified a line and when, but leaves the rationale completely invisible. CodeWhy unearths original pull request debates, architecture decision records (ADRs), and architectural trade-offs.',
      contrast: {
        gitBlame: 'git blame: author=alice date=2023-04-12 commit=8f9a2',
        codeWhy: 'CodeWhy: "Preserve explicit port 0 in connection_from_url and HTTP/2 authority by using explicit None check..."',
      },
    },
    {
      icon: Quote,
      color: 'emerald',
      badgeClass: 'badge-emerald',
      borderClass: 'stat-card-emerald',
      tag: 'ZERO HALLUCINATIONS',
      title: 'Verbatim Quote Verification',
      description:
        'Generic models invent plausible-sounding justifications for legacy patterns. CodeWhy strictly validates every quote character-by-character against original PR threads, commits, and review comments before citing it.',
      contrast: {
        gitBlame: 'Generic AI: "Configured for high-throughput concurrency..." (Unverified assumption)',
        codeWhy: 'CodeWhy: Exact character-verified quote linked directly to PR #3456.',
      },
    },
    {
      icon: GitBranch,
      color: 'amber',
      badgeClass: 'badge-amber',
      borderClass: 'stat-card-amber',
      tag: 'TEMPORAL STATE MACHINE',
      title: 'Reversals & Supersession Tracking',
      description:
        'Software evolves. CodeWhy understands the timeline of changes: when an old decision was superseded, reverted, or revived through multi-hop Git lineage so you never rely on obsolete assumptions.',
      contrast: {
        gitBlame: 'Static search: Shows outdated commit from 2021 as active truth.',
        codeWhy: 'CodeWhy: Marks decision as SUPERSEDED by PR #3466 (reverting PR #3456).',
      },
    },
    {
      icon: ShieldCheck,
      color: 'rose',
      badgeClass: 'badge-rose',
      borderClass: 'stat-card-rose',
      tag: 'PRINCIPLED REFUSAL',
      title: '4-Gate Refusal Pipeline',
      description:
        'If historical reasoning was never recorded or evidence is contradictory, CodeWhy refuses honestly through automated verification gates rather than fabricating speculative explanations.',
      contrast: {
        gitBlame: 'Naive RAG: Gives speculative low-confidence answer to avoid refusal.',
        codeWhy: 'CodeWhy: Refusal code "no_decision_path" with verified historical evidence gaps.',
      },
    },
  ];

  return (
    <section
      className="py-16 px-4 sm:px-6 lg:px-8 border-b"
      style={{
        backgroundColor: 'var(--canvas)',
        borderColor: 'var(--border)',
      }}
    >
      <div className="max-w-6xl mx-auto">
        
        {/* Section Header */}
        <div className="text-center max-w-2xl mx-auto mb-12">
          <div
            className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-mono font-medium mb-3 border"
            style={{
              backgroundColor: 'var(--surface-raised)',
              borderColor: 'var(--border)',
              color: 'var(--text-muted)',
            }}
          >
            <Layers className="w-3.5 h-3.5 text-violet-500" />
            <span>ARCHITECTURAL PRINCIPLES</span>
          </div>
          <h2 className="text-3xl sm:text-4xl font-extrabold tracking-tight font-sans" style={{ color: 'var(--text)' }}>
            Why Code Archeology Matters
          </h2>
          <p className="mt-3 text-sm sm:text-base leading-relaxed" style={{ color: 'var(--text-muted)' }}>
            Engineering teams lose institutional memory as people rotate. CodeWhy turns Git repository archives into permanent, decision-level knowledge.
          </p>
        </div>

        {/* Pillars Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
          {pillars.map((pillar, idx) => {
            const Icon = pillar.icon;
            return (
              <div
                key={idx}
                className={`card-3d ${pillar.borderClass} rounded-xl p-6 border flex flex-col justify-between`}
                style={{
                  backgroundColor: 'var(--surface)',
                  borderColor: 'var(--border)',
                }}
              >
                <div>
                  <div className="flex items-center justify-between mb-3.5">
                    <span className={`text-[10px] font-mono tracking-wider font-semibold px-2 py-0.5 rounded-md ${pillar.badgeClass}`}>
                      {pillar.tag}
                    </span>
                    <div
                      className="p-2 rounded-lg"
                      style={{
                        backgroundColor: 'var(--surface-raised)',
                        color:
                          pillar.color === 'violet' ? 'var(--violet)' :
                          pillar.color === 'emerald' ? 'var(--emerald)' :
                          pillar.color === 'amber' ? 'var(--amber)' : 'var(--rose)',
                      }}
                    >
                      <Icon className="w-4 h-4" />
                    </div>
                  </div>

                  <h3 className="text-lg font-bold font-sans mb-2" style={{ color: 'var(--text)' }}>
                    {pillar.title}
                  </h3>

                  <p className="text-xs sm:text-sm leading-relaxed mb-4" style={{ color: 'var(--text-muted)' }}>
                    {pillar.description}
                  </p>
                </div>

                {/* Contrast Callout */}
                <div
                  className="rounded-lg p-3 text-xs font-mono border space-y-2"
                  style={{
                    backgroundColor: 'var(--surface-raised)',
                    borderColor: 'var(--border)',
                  }}
                >
                  <div className="flex items-start gap-2 text-rose-500/90 dark:text-rose-400">
                    <XCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                    <span className="line-through opacity-75">{pillar.contrast.gitBlame}</span>
                  </div>
                  <div className="flex items-start gap-2 text-emerald-600 dark:text-emerald-400 font-medium">
                    <CheckCircle2 className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                    <span>{pillar.contrast.codeWhy}</span>
                  </div>
                </div>

              </div>
            );
          })}
        </div>

      </div>
    </section>
  );
};
