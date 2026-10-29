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

  const handleCopyQuote = (c: Citation) => {
    navigator.clipboard.writeText(`"${c.quote}" — ${c.source_url}`);
    setCopiedId(c.id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  return (
    <div className="flex flex-col h-full bg-[#0B0C09] border-l border-[#292A23] w-full overflow-y-auto">
      {/* Header */}
      <div className="p-3.5 border-b border-[#292A23] bg-[#0B0C09] sticky top-0 z-10">
        <div className="flex items-center gap-2">
          <div className="p-1 rounded bg-[#12130F] text-[#757F6C] border border-[#292A23]">
            <BookOpen className="w-3.5 h-3.5" />
          </div>
          <div>
            <h2 className="text-xs font-mono font-semibold uppercase tracking-wider text-[#F5F3ED]">
              Evidence Receipts
            </h2>
            <span className="text-[11px] font-mono text-[#A5A69D]">
              {citations.length} verified quotes {evidenceGaps.length > 0 ? `• ${evidenceGaps.length} gaps` : ''}
            </span>
          </div>
        </div>
      </div>

      <div className="p-3.5 space-y-5">
        {/* Evidence Receipts Section */}
        <div className="space-y-2.5">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-mono uppercase tracking-wider text-[#A5A69D] font-semibold flex items-center gap-1.5">
              <Quote className="w-3.5 h-3.5 text-[#B9915E]" />
              Verified Quotes ({citations.length})
            </span>
            {selectedCitationId && (
              <button
                onClick={() => onSelectCitation(null)}
                className="text-[10px] font-mono text-[#B9915E] hover:underline cursor-pointer"
              >
                Clear focus
              </button>
            )}
          </div>

          {citations.length === 0 ? (
            <div className="p-4 rounded-lg bg-[#12130F] border border-[#292A23] text-center space-y-1.5">
              <FileSearch className="w-5 h-5 text-[#A5A69D]/60 mx-auto" />
              <p className="text-xs font-mono text-[#A5A69D]">
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
                        ? 'bg-[#181914] border-[#B9915E] ring-1 ring-[#B9915E]/50'
                        : 'bg-[#12130F] border-[#292A23] hover:border-[#292A23]/80'
                    }`}
                  >
                    {/* Top Row: Citation ID badge & Source */}
                    <div className="flex items-center justify-between text-[11px] font-mono mb-2">
                      <div className="flex items-center gap-1.5">
                        <span className="px-1.5 py-0.2 rounded bg-[#080907] text-[#B9915E] font-semibold border border-[#292A23]">
                          {c.id}
                        </span>
                        {c.decision_id && (
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              onOpenDecision?.(c.decision_id);
                            }}
                            className="text-[#A5A69D] hover:text-[#B9915E] hover:underline"
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
                          className="text-[#A5A69D] hover:text-[#F5F3ED] p-1 rounded hover:bg-[#181914] transition-colors"
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
                            className="text-[#A5A69D] hover:text-[#B9915E] p-1 rounded hover:bg-[#181914] transition-colors"
                            title="Open original source URL"
                          >
                            <ExternalLink className="w-3.5 h-3.5" />
                          </a>
                        )}
                      </div>
                    </div>

                    {/* Verbatim Quoted Text */}
                    <div className="quote-text text-xs text-[#F5F3ED] leading-relaxed border-l-2 border-[#757F6C] pl-2.5 py-1 bg-[#080907] rounded-r">
                      "{c.quote}"
                    </div>

                    {/* Metadata Footer: Author & Timestamp */}
                    <div className="mt-2 flex items-center justify-between text-[10px] font-mono text-[#A5A69D] pt-1.5 border-t border-[#292A23]">
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
            <span className="text-[11px] font-mono uppercase tracking-wider text-[#d29922] font-semibold flex items-center gap-1.5">
              <AlertTriangle className="w-3.5 h-3.5" />
              Evidence Gaps ({evidenceGaps.length})
            </span>
            <div className="p-3 rounded-lg bg-[#12130F] border border-[#d29922]/30 space-y-1.5">
              <p className="text-[11px] font-mono text-[#d29922]">
                Missing historical records:
              </p>
              <ul className="space-y-1 text-xs font-mono text-[#A5A69D]">
                {evidenceGaps.map((gap, i) => (
                  <li key={i} className="flex items-start gap-2">
                    <span className="text-[#d29922] select-none">•</span>
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
            <span className="text-[11px] font-mono uppercase tracking-wider text-[#757F6C] font-semibold flex items-center gap-1.5">
              <UserCheck className="w-3.5 h-3.5" />
              Contributors to Ask ({whoToAsk.length})
            </span>
            <div className="p-2.5 rounded-lg bg-[#12130F] border border-[#292A23] space-y-2">
              <div className="space-y-1.5">
                {whoToAsk.map((person, idx) => (
                  <div
                    key={idx}
                    className="flex items-center justify-between p-2 rounded-md bg-[#080907] border border-[#292A23] text-xs font-mono"
                  >
                    <div className="flex items-center gap-2">
                      <div className="w-5 h-5 rounded-full bg-[#181914] text-[#757F6C] border border-[#292A23] flex items-center justify-center font-bold text-[10px]">
                        {person.login.charAt(0).toUpperCase()}
                      </div>
                      <span className="font-medium text-[#F5F3ED]">@{person.login}</span>
                    </div>

                    <div className="flex items-center gap-2">
                      <span className="px-1.5 py-0.2 rounded text-[10px] bg-[#12130F] text-[#A5A69D] border border-[#292A23] capitalize">
                        {person.reason.replace(/_/g, ' ')}
                      </span>
                      <span
                        className={`w-2 h-2 rounded-full ${
                          person.active ? 'bg-[#2ea043]' : 'bg-[#A5A69D]/50'
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
