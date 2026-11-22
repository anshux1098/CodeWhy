import React, { useState } from 'react';
import type { Citation, WhoToAsk } from '../types';
import {
  Quote,
  ExternalLink,
  Copy,
  CheckCheck,
  UserCheck,
  AlertTriangle,
  FileSearch,
  BookOpen,
} from 'lucide-react';

interface ContextualEvidenceMarginProps {
  citations: Citation[];
  evidenceGaps: string[];
  whoToAsk: WhoToAsk[];
  selectedCitationId: string | null;
  onSelectCitation: (citationId: string | null) => void;
  onOpenDecision?: (decisionId: string) => void;
}

export const ContextualEvidenceMargin: React.FC<ContextualEvidenceMarginProps> = ({
  citations,
  evidenceGaps,
  whoToAsk,
  selectedCitationId,
  onSelectCitation,
  onOpenDecision,
}) => {
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const handleCopyQuote = async (c: Citation) => {
    try {
      if (!navigator.clipboard?.writeText) return;
      await navigator.clipboard.writeText(`"${c.quote}" — ${c.source_url}`);
      setCopiedId(c.id);
      setTimeout(() => setCopiedId(null), 2000);
    } catch {
      // Clipboard blocked; leave state unchanged
    }
  };

  return (
    <div className="flex flex-col h-full bg-[#191628] border-l border-[#CAC4CE]/20 w-full overflow-y-auto">
      {/* Header */}
      <div className="p-3.5 border-b border-[#CAC4CE]/20 bg-[#242038] sticky top-0 z-10">
        <div className="flex items-center gap-2">
          <div className="p-1.5 rounded-lg bg-[#161324] text-[#9067C6] border border-[#CAC4CE]/20">
            <BookOpen className="w-3.5 h-3.5" />
          </div>
          <div>
            <h2 className="text-xs font-mono font-semibold uppercase tracking-wider text-[#F7ECE1]">
              Evidence Receipts
            </h2>
            <span className="text-[11px] font-mono text-[#CAC4CE]">
              {citations.length} verified quotes {evidenceGaps.length > 0 ? `• ${evidenceGaps.length} gaps` : ''}
            </span>
          </div>
        </div>
      </div>

      <div className="p-3.5 space-y-5">
        {/* Evidence Receipts Section */}
        <div className="space-y-2.5">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-mono uppercase tracking-wider text-[#CAC4CE] font-semibold flex items-center gap-1.5">
              <Quote className="w-3.5 h-3.5 text-[#9067C6]" />
              Verified Quotes ({citations.length})
            </span>
            {selectedCitationId && (
              <button
                onClick={() => onSelectCitation(null)}
                className="text-[10px] font-mono text-[#8D86C9] hover:text-[#F7ECE1] hover:underline cursor-pointer"
              >
                Clear focus
              </button>
            )}
          </div>

          {citations.length === 0 ? (
            <div className="p-4 rounded-lg bg-[#242038] border border-[#CAC4CE]/20 text-center space-y-1.5">
              <FileSearch className="w-5 h-5 text-[#CAC4CE]/70 mx-auto" />
              <p className="text-xs font-mono text-[#CAC4CE]">
                No direct citations verified in this response.
              </p>
            </div>
          ) : (
            <div className="space-y-2.5">
              {citations.map((c) => {
                const isSelected = selectedCitationId === c.id;
                return (
                  <div
                    key={c.id}
                    id={`receipt-${c.id}`}
                    onClick={() => onSelectCitation(isSelected ? null : c.id)}
                    className={`rounded-lg p-3 transition-colors cursor-pointer border ${
                      isSelected
                        ? 'bg-[#2C2744] border-[#9067C6] ring-1 ring-[#9067C6]/50'
                        : 'bg-[#242038] border-[#CAC4CE]/20 hover:border-[#9067C6]/60'
                    }`}
                  >
                    {/* Top Row: Citation ID badge & Source */}
                    <div className="flex items-center justify-between text-[11px] font-mono mb-2">
                      <div className="flex items-center gap-1.5">
                        <span className="px-1.5 py-0.5 rounded bg-[#161324] text-[#C5B0E6] font-semibold border border-[#CAC4CE]/25">
                          {c.id}
                        </span>
                        {c.decision_id && (
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              onOpenDecision?.(c.decision_id);
                            }}
                            className="text-[#CAC4CE] hover:text-[#F7ECE1] hover:underline cursor-pointer"
                            title="Open governing decision"
                          >
                            {c.decision_id}
                          </button>
                        )}
                      </div>

                      <div className="flex items-center gap-1.5">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            handleCopyQuote(c);
                          }}
                          className="text-[#CAC4CE] hover:text-[#F7ECE1] p-1 rounded hover:bg-[#322D4D] transition-colors cursor-pointer"
                          title="Copy quote"
                        >
                          {copiedId === c.id ? (
                            <CheckCheck className="w-3.5 h-3.5 text-[#3fb950]" />
                          ) : (
                            <Copy className="w-3.5 h-3.5" />
                          )}
                        </button>
                        {c.source_url && (
                          <a
                            href={c.source_url}
                            target="_blank"
                            rel="noreferrer"
                            onClick={(e) => e.stopPropagation()}
                            className="text-[#CAC4CE] hover:text-[#F7ECE1] p-1 rounded hover:bg-[#322D4D] transition-colors"
                            title="Open original source URL"
                          >
                            <ExternalLink className="w-3.5 h-3.5" />
                          </a>
                        )}
                      </div>
                    </div>

                    {/* Verbatim Quoted Text */}
                    <div className="quote-text text-xs text-[#F7ECE1] leading-relaxed border-l-2 border-[#9067C6] pl-2.5 py-1.5 bg-[#161324] rounded-r">
                      "{c.quote}"
                    </div>

                    {/* Metadata Footer: Author & Timestamp */}
                    <div className="mt-2 flex items-center justify-between text-[10px] font-mono text-[#CAC4CE] pt-1.5 border-t border-[#CAC4CE]/15">
                      <span>{c.author ? `@${c.author}` : 'Anonymous contributor'}</span>
                      {c.timestamp && (
                        <span>{new Date(c.timestamp).toLocaleDateString()}</span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Evidence Gaps Section */}
        {evidenceGaps.length > 0 && (
          <div className="space-y-2">
            <span className="text-[11px] font-mono uppercase tracking-wider text-[#e3b341] font-semibold flex items-center gap-1.5">
              <AlertTriangle className="w-3.5 h-3.5" />
              Evidence Gaps ({evidenceGaps.length})
            </span>
            <div className="p-3 rounded-lg bg-[#242038] border border-[#e3b341]/35 space-y-1.5">
              <p className="text-[11px] font-mono text-[#e3b341]">
                Missing historical records:
              </p>
              <ul className="space-y-1 text-xs font-mono text-[#CAC4CE]">
                {evidenceGaps.map((gap, i) => (
                  <li key={`${i}-${gap.slice(0, 24)}`} className="flex items-start gap-2">
                    <span className="text-[#e3b341] select-none">•</span>
                    <span className="leading-relaxed">{gap}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}

        {/* "Who to ask" — ONLY when returned by the backend */}
        {whoToAsk && whoToAsk.length > 0 && (
          <div className="space-y-2">
            <span className="text-[11px] font-mono uppercase tracking-wider text-[#8D86C9] font-semibold flex items-center gap-1.5">
              <UserCheck className="w-3.5 h-3.5" />
              Contributors to Ask ({whoToAsk.length})
            </span>
            <div className="p-2.5 rounded-lg bg-[#242038] border border-[#CAC4CE]/20 space-y-2">
              <div className="space-y-1.5">
                {whoToAsk.map((person) => (
                  <div
                    key={`${person.login}-${person.reason}`}
                    className="flex items-center justify-between p-2 rounded-md bg-[#161324] border border-[#CAC4CE]/20 text-xs font-mono"
                  >
                    <div className="flex items-center gap-2">
                      <div className="w-5 h-5 rounded-full bg-[#242038] text-[#C5B0E6] border border-[#9067C6]/45 flex items-center justify-center font-bold text-[10px]">
                        {person.login.charAt(0).toUpperCase()}
                      </div>
                      <span className="font-medium text-[#F7ECE1]">@{person.login}</span>
                    </div>

                    <div className="flex items-center gap-2">
                      <span className="px-1.5 py-0.5 rounded text-[10px] bg-[#242038] text-[#CAC4CE] border border-[#CAC4CE]/20 capitalize">
                        {person.reason.replace(/_/g, ' ')}
                      </span>
                      <span
                        className={`w-2 h-2 rounded-full ${
                          person.active ? 'bg-[#3fb950]' : 'bg-[#CAC4CE]/50'
                        }`}
                        title={person.active ? 'Active contributor' : 'Inactive'}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
