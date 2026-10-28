import React, { useState } from 'react';
import type { Decision, DecisionListItem, DecisionState } from '../types';
import {
  Check,
  ArrowRight,
  X,
  HelpCircle,
  GitPullRequest,
  Calendar,
  Layers,
} from 'lucide-react';

interface DecisionTimelineSpineProps {
  decisions: (Decision | DecisionListItem)[];
  activeDecisionId?: string | null;
  onSelectDecision: (decisionId: string) => void;
  title?: string;
  isLoading?: boolean;
}

export const DecisionTimelineSpine: React.FC<DecisionTimelineSpineProps> = ({
  decisions,
  activeDecisionId,
  onSelectDecision,
  title = 'Timeline Spine',
  isLoading = false,
}) => {
  const [filterState, setFilterState] = useState<'ALL' | DecisionState>('ALL');

  const filteredDecisions = decisions.filter((d) => {
    if (filterState === 'ALL') return true;
    return d.state === filterState;
  });

  const getDecisionDate = (d: Decision | DecisionListItem): string | null => {
    if ('effective_at' in d && d.effective_at) return d.effective_at;
    if ('recorded_at' in d && d.recorded_at) return d.recorded_at;
    if ('date' in d && d.date) return d.date;
    return null;
  };

  const getSourceNumber = (d: Decision | DecisionListItem): number | null => {
    if ('source' in d && d.source?.number) return d.source.number;
    return null;
  };

  const getSourceUrl = (d: Decision | DecisionListItem): string | null => {
    if ('source' in d && d.source?.url) return d.source.url;
    if ('source_url' in d && d.source_url) return d.source_url;
    return null;
  };

  return (
    <div className="flex flex-col h-full bg-[#fffdf8] border-r border-[#d7d2c6] w-full">
      {/* Header with Title & Filter Pills */}
      <div className="p-3.5 border-b border-[#d7d2c6] space-y-2.5 bg-[#fffdf8]">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="p-1 rounded bg-[#efede5] text-[#617c50] border border-[#d7d2c6]">
              <Layers className="w-3.5 h-3.5" />
            </div>
            <div>
              <h2 className="text-xs font-mono font-semibold uppercase tracking-wider text-[#292b25]">
                {title}
              </h2>
              <span className="text-[11px] font-mono text-[#77776e]">
                {filteredDecisions.length} of {decisions.length} recorded
              </span>
            </div>
          </div>
        </div>

        {/* State Filter Buttons */}
        <div className="filter-segment-group" role="group" aria-label="Filter decisions by state">
          {(['ALL', 'ACTIVE', 'SUPERSEDED', 'REJECTED', 'UNRESOLVED'] as const).map((st) => (
            <button
              key={st}
              type="button"
              onClick={() => setFilterState(st)}
              aria-pressed={filterState === st}
              data-state-filter={st}
              className="filter-segment cursor-pointer"
            >
              {st === 'ALL' ? 'All' : st}
            </button>
          ))}
        </div>
      </div>

      {/* Timeline Spine Scroll Area */}
      <div className="flex-1 overflow-y-auto p-3.5 space-y-3 relative">
        {/* Continuous Spine Line */}
        <div className="absolute left-6 top-3.5 bottom-3.5 w-px bg-[#d7d2c6] pointer-events-none" />

        {isLoading && (
          <div className="py-10 text-center text-xs font-mono text-[#77776e]">
            Loading timeline...
          </div>
        )}

        {!isLoading && filteredDecisions.length === 0 && (
          <div className="py-10 text-center text-xs font-mono text-[#77776e]">
            No decisions match state filter.
          </div>
        )}

        {!isLoading &&
          filteredDecisions.map((decision) => {
            const isSelected = activeDecisionId === decision.id;
            const dateStr = getDecisionDate(decision);
            const sourceNum = getSourceNumber(decision);
            const sourceUrl = getSourceUrl(decision);

            const renderCardStyle = () => {
              switch (decision.state) {
                case 'ACTIVE':
                  return {
                    container: 'bg-[#f5f3ed] border border-[#2ea043]/40 hover:border-[#2ea043]/70 status-card-active',
                    badge: 'bg-[#2ea043]/15 text-[#3fb950] border border-[#2ea043]/30 status-badge-active',
                    icon: <Check className="w-3 h-3 text-[#3fb950] stroke-[2.5] status-icon-active" />,
                    label: 'Active',
                    nodeDot: 'bg-[#2ea043] border border-[#fffdf8] status-dot-active',
                    summaryText: 'text-[#292b25] font-medium',
                  };
                case 'SUPERSEDED':
                  return {
                    container: 'bg-[#f5f3ed]/60 border border-[#d7d2c6] opacity-75 hover:opacity-100 status-card-superseded',
                    badge: 'bg-[#efede5] text-[#77776e] border border-[#d7d2c6] status-badge-superseded',
                    icon: <ArrowRight className="w-3 h-3 text-[#77776e] status-icon-superseded" />,
                    label: 'Superseded',
                    nodeDot: 'bg-[#929086] border border-[#fffdf8] status-dot-superseded',
                    summaryText: 'text-[#77776e] line-through decoration-[#bdb8ab]',
                  };
                case 'REJECTED':
                  return {
                    container: 'bg-[#f5f3ed] border border-[#da3633]/40 hover:border-[#da3633]/70 status-card-rejected',
                    badge: 'bg-[#da3633]/15 text-[#f85149] border border-[#da3633]/30 status-badge-rejected',
                    icon: <X className="w-3 h-3 text-[#f85149] stroke-[2.5] status-icon-rejected" />,
                    label: 'Rejected',
                    nodeDot: 'bg-[#da3633] border border-[#fffdf8] status-dot-rejected',
                    summaryText: 'text-[#292b25]',
                  };
                case 'UNRESOLVED':
                  return {
                    container: 'bg-[#f5f3ed] border border-[#d29922]/40 hover:border-[#d29922]/70 status-card-unresolved',
                    badge: 'bg-[#d29922]/15 text-[#e3b341] border border-[#d29922]/30 status-badge-unresolved',
                    icon: <HelpCircle className="w-3 h-3 text-[#e3b341] status-icon-unresolved" />,
                    label: 'Needs Review',
                    nodeDot: 'bg-[#d29922] border border-[#fffdf8] status-dot-unresolved',
                    summaryText: 'text-[#292b25]',
                  };
                default:
                  return {
                    container: 'bg-[#f5f3ed] border border-[#d7d2c6]',
                    badge: 'bg-[#efede5] text-[#77776e] border border-[#d7d2c6]',
                    icon: <Layers className="w-3 h-3" />,
                    label: decision.state,
                    nodeDot: 'bg-[#617c50] border border-[#fffdf8]',
                    summaryText: 'text-[#292b25]',
                  };
              }
            };

            const style = renderCardStyle();

            return (
              <div key={decision.id} className="relative pl-6 group">
                {/* Node Dot on the spine */}
                <div
                  className={`absolute left-[3px] top-3.5 w-2.5 h-2.5 rounded-full ${style.nodeDot} z-10`}
                />

                {/* Card Container */}
                <div
                  onClick={() => onSelectDecision(decision.id)}
                  className={`p-2.5 rounded-md transition-colors cursor-pointer ${style.container} ${
                    isSelected ? 'ring-1 ring-[#718d5e] border-[#718d5e]' : ''
                  }`}
                >
                  {/* Top Bar: State Badge, ID, and Date */}
                  <div className="flex items-center justify-between gap-2 mb-1">
                    <span
                      className={`inline-flex items-center gap-1 px-1.5 py-0.2 rounded text-[10px] font-mono font-medium ${style.badge}`}
                    >
                      {style.icon}
                      <span>{style.label}</span>
                    </span>

                    <span className="text-[10px] font-mono text-[#77776e]">
                      {decision.id}
                    </span>
                  </div>

                  {/* Summary */}
                  <p className={`text-xs leading-snug line-clamp-2 ${style.summaryText}`}>
                    {decision.summary}
                  </p>

                  {/* Superseded By Indicator */}
                  {decision.superseded_by && decision.superseded_by.length > 0 && (
                    <div className="mt-1.5 pt-1.5 border-t border-[#d7d2c6] flex items-center gap-1.5 text-[10px] font-mono text-[#77776e]">
                      <ArrowRight className="w-3 h-3 text-[#617c50]" />
                      <span>Replaced by:</span>
                      <span className="font-semibold text-[#617c50]">
                        {decision.superseded_by.join(', ')}
                      </span>
                    </div>
                  )}

                  {/* Footer: Date & Source PR */}
                  <div className="mt-1.5 flex items-center justify-between text-[10px] font-mono text-[#77776e] pt-1">
                    <div className="flex items-center gap-1">
                      {dateStr && (
                        <>
                          <Calendar className="w-3 h-3 text-[#929086]" />
                          <span>{new Date(dateStr).toLocaleDateString()}</span>
                        </>
                      )}
                    </div>

                    {sourceNum && (
                      sourceUrl ? (
                        <a
                          href={sourceUrl}
                          target="_blank"
                          rel="noreferrer"
                          onClick={(e) => e.stopPropagation()}
                          className="flex items-center gap-1 text-[#617c50] hover:underline"
                          title="Open source PR in new tab"
                        >
                          <GitPullRequest className="w-3 h-3" />
                          <span>#{sourceNum}</span>
                        </a>
                      ) : (
                        <span className="flex items-center gap-1 text-[#617c50]">
                          <GitPullRequest className="w-3 h-3" />
                          <span>#{sourceNum}</span>
                        </span>
                      )
                    )}
                  </div>
                </div>
              </div>
            );
          })}
      </div>
    </div>
  );
};
