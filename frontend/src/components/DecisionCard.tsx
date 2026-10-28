import React from 'react';
import type { Decision } from '../types';
import { 
  Check, 
  ArrowRight, 
  X, 
  HelpCircle, 
  ExternalLink, 
  Clock, 
  GitPullRequest,
  AlertCircle
} from 'lucide-react';

interface DecisionCardProps {
  decision: Decision;
  onNavigateToDecision?: (decisionId: string) => void;
}

export const DecisionCard: React.FC<DecisionCardProps> = ({
  decision,
  onNavigateToDecision,
}) => {
  const { state, summary, rationale, source, recorded_at, effective_at, ended_at, superseded_by } = decision;

  // Authentic Git-style state configuration
  const renderStateConfig = () => {
    switch (state) {
      case 'ACTIVE':
        return {
          containerClass: 'bg-[#fffdf8] border border-[#2ea043]/40 status-card-active',
          badgeClass: 'bg-[#2ea043]/15 text-[#3fb950] border border-[#2ea043]/40 status-badge-active',
          icon: <Check className="w-3.5 h-3.5 text-[#3fb950] stroke-[2.5] status-icon-active" />,
          label: 'Active',
          textClass: 'text-[#292b25] font-medium',
          rationaleClass: 'text-[#51534b]',
        };

      case 'SUPERSEDED':
        return {
          containerClass: 'bg-[#fffdf8]/70 border border-[#d7d2c6] opacity-80 hover:opacity-100 transition-opacity status-card-superseded',
          badgeClass: 'bg-[#efede5] text-[#77776e] border border-[#d7d2c6] status-badge-superseded',
          icon: <ArrowRight className="w-3.5 h-3.5 text-[#77776e] status-icon-superseded" />,
          label: 'Superseded',
          textClass: 'text-[#77776e] line-through decoration-[#929086]',
          rationaleClass: 'text-[#929086]',
        };

      case 'REJECTED':
        return {
          containerClass: 'bg-[#fffdf8] border border-[#da3633]/40 status-card-rejected',
          badgeClass: 'bg-[#da3633]/15 text-[#f85149] border border-[#da3633]/40 status-badge-rejected',
          icon: <X className="w-3.5 h-3.5 text-[#f85149] stroke-[2.5] status-icon-rejected" />,
          label: 'Rejected',
          textClass: 'text-[#292b25]',
          rationaleClass: 'text-[#77776e]',
        };

      case 'UNRESOLVED':
        return {
          containerClass: 'bg-[#fffdf8] border border-[#d29922]/40 status-card-unresolved',
          badgeClass: 'bg-[#d29922]/15 text-[#e3b341] border border-[#d29922]/40 status-badge-unresolved',
          icon: <HelpCircle className="w-3.5 h-3.5 text-[#e3b341] status-icon-unresolved" />,
          label: 'Needs Review',
          textClass: 'text-[#292b25]',
          rationaleClass: 'text-[#51534b]',
        };

      default:
        return {
          containerClass: 'bg-[#fffdf8] border border-[#d7d2c6]',
          badgeClass: 'bg-[#efede5] text-[#77776e] border border-[#d7d2c6]',
          icon: <AlertCircle className="w-3.5 h-3.5" />,
          label: state,
          textClass: 'text-[#292b25]',
          rationaleClass: 'text-[#77776e]',
        };
    }
  };

  const config = renderStateConfig();

  return (
    <div className={`workbench-card rounded-xl p-5 transition-all hover:-translate-y-0.5 hover:shadow-md ${config.containerClass}`}>
      {/* Top Bar: State Badge, ID, and Source Reference */}
      <div className="flex flex-wrap items-center justify-between gap-2.5 mb-2.5">
        <div className="flex items-center gap-2">
          <span
            className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-mono font-medium ${config.badgeClass}`}
          >
            {config.icon}
            <span>{config.label}</span>
          </span>

          <span className="text-xs font-mono text-[#77776e]">
            {decision.id}
          </span>
        </div>

        {/* Source Reference Link */}
        {source && (
          <div className="flex items-center gap-1.5 text-xs font-mono text-[#77776e]">
            <GitPullRequest className="w-3.5 h-3.5 text-[#a371f7]" />
            <span>{source.type}</span>
            {source.number && <span className="text-[#617c50]">#{source.number}</span>}
            {source.url && (
              <a
                href={source.url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-[#77776e] hover:text-[#617c50] transition-colors p-0.5"
                title="View original discussion"
              >
                <ExternalLink className="w-3.5 h-3.5" />
              </a>
            )}
          </div>
        )}
      </div>

      {/* Decision Summary */}
      <h4 className={`text-sm font-sans mb-1.5 ${config.textClass}`}>
        {summary}
      </h4>

      {/* Decision Rationale */}
      {rationale && (
        <p className={`text-xs leading-relaxed mb-3 ${config.rationaleClass}`}>
          {rationale}
        </p>
      )}

      {/* SUPERSEDED: Arrow to the Replacement */}
      {state === 'SUPERSEDED' && superseded_by && superseded_by.length > 0 && (
        <div className="mt-2.5 pt-2.5 border-t border-[#d7d2c6] flex items-center gap-2 text-xs font-mono bg-[#f5f3ed] p-2 rounded border border-[#d7d2c6]">
          <span className="text-[#77776e] font-medium flex items-center gap-1.5">
            <ArrowRight className="w-3.5 h-3.5 text-[#617c50]" />
            <span>Superseded by:</span>
          </span>
          <div className="flex flex-wrap items-center gap-1.5">
            {superseded_by.map((repId) => (
              <button
                key={repId}
                onClick={() => onNavigateToDecision?.(repId)}
                className="px-1.5 py-0.5 rounded bg-[#efede5] text-[#617c50] border border-[#d7d2c6] hover:bg-[#d7d2c6] transition-colors cursor-pointer"
                title="View superseding decision"
              >
                {repId} →
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Metadata Timestamps */}
      <div className="flex flex-wrap items-center gap-3 text-[11px] font-mono text-[#77776e] mt-2.5 pt-2 border-t border-[#d7d2c6]/60">
        {recorded_at && (
          <span className="flex items-center gap-1">
            <Clock className="w-3 h-3" />
            Recorded: {new Date(recorded_at).toLocaleDateString()}
          </span>
        )}
        {effective_at && (
          <span>Effective: {new Date(effective_at).toLocaleDateString()}</span>
        )}
        {ended_at && (
          <span className="text-[#f85149]">Ended: {new Date(ended_at).toLocaleDateString()}</span>
        )}
      </div>
    </div>
  );
};
