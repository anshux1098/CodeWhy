import React from 'react';
import { 
  Cpu, 
  Search, 
  Database, 
  ShieldCheck, 
  ArrowRight,
  Filter,
  Layers
} from 'lucide-react';

export const ArcheologyWorkflow: React.FC = () => {
  const steps = [
    {
      num: '01',
      title: 'Target Ingestion',
      desc: 'Clones repository history and builds local resumable SQLite cache with SHA-256 deduplication.',
      badge: 'Git + SQLite',
      icon: Database,
    },
    {
      num: '02',
      title: 'Noise Elimination',
      desc: '8 heuristic detectors discard bot bumps, lint-only PRs, and mechanical merges while preserving reverts.',
      badge: 'Noise Filter',
      icon: Filter,
    },
    {
      num: '03',
      title: 'Entity Extraction',
      desc: 'Identifies code entities from the files each pull request changed, including modules, constants, and classes.',
      badge: 'AST Parser',
      icon: Search,
    },
    {
      num: '04',
      title: 'Verbatim Quote Gate',
      desc: 'Mines PR descriptions, code reviews, and ADRs with mandatory character-level quote matching.',
      badge: 'Substring Gate',
      icon: Cpu,
    },
    {
      num: '05',
      title: 'Lineage Graph',
      desc: 'Indexes supersession chains (REVERTS, SUPERSEDES, RELIES_ON) into Neo4j property graph.',
      badge: 'Knowledge Graph',
      icon: ShieldCheck,
    },
  ];

  return (
    <section className="py-16 px-4 sm:px-6 lg:px-8 border-b border-[#d7d2c6] bg-[#f5f3ed]">
      <div className="max-w-6xl mx-auto">
        
        {/* Header */}
        <div className="text-center max-w-2xl mx-auto mb-12">
          <div className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded bg-[#fffdf8] border border-[#d7d2c6] text-[#77776e] text-xs font-mono mb-3">
            <Layers className="w-3.5 h-3.5 text-[#617c50]" />
            <span>PIPELINE ARCHITECTURE</span>
          </div>
          <h2 className="text-2xl sm:text-3xl font-bold text-[#292b25] tracking-tight font-sans">
            The Code Archeology Pipeline
          </h2>
          <p className="mt-3 text-sm text-[#77776e]">
            From raw Git commits to validated architectural provenance through a zero-hallucination extraction flow.
          </p>
        </div>

        {/* Steps Grid */}
        <div className="grid grid-cols-1 md:grid-cols-5 gap-3">
          {steps.map((step, idx) => {
            const Icon = step.icon;
            return (
              <div
                key={idx}
                className="rounded-lg p-4 bg-[#fffdf8] border border-[#d7d2c6] hover:border-[#bdb8ab] transition-colors flex flex-col justify-between"
              >
                <div>
                  <div className="flex items-center justify-between mb-3">
                    <span className="font-mono text-[11px] font-semibold text-[#617c50] bg-[#54734f]/10 px-2 py-0.5 rounded border border-[#718d5e]/30">
                      STAGE {step.num}
                    </span>
                    <div className="p-1.5 rounded bg-[#efede5] border border-[#d7d2c6] text-[#77776e]">
                      <Icon className="w-3.5 h-3.5 text-[#51534b]" />
                    </div>
                  </div>

                  <h3 className="text-sm font-semibold text-[#292b25] font-sans mb-1.5">
                    {step.title}
                  </h3>

                  <p className="text-xs text-[#77776e] leading-relaxed mb-3">
                    {step.desc}
                  </p>
                </div>

                <div className="pt-2.5 border-t border-[#d7d2c6] flex items-center justify-between">
                  <span className="text-[10px] font-mono text-[#77776e] uppercase">
                    {step.badge}
                  </span>
                  {idx < steps.length - 1 && (
                    <ArrowRight className="w-3.5 h-3.5 text-[#929086] hidden md:block" />
                  )}
                </div>
              </div>
            );
          })}
        </div>

      </div>
    </section>
  );
};
