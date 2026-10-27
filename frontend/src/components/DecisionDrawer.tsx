import React, { useEffect, useState } from 'react';
import type { DecisionDetail, DecisionState } from '../types';
import { fetchDecisionDetail } from '../services/api';
import {
  X,
  Check,
  ArrowRight,
  HelpCircle,
  ExternalLink,
  Calendar,
  Clock,
  GitPullRequest,
  AlertCircle,
  Copy,
  CheckCheck,
  ShieldAlert,
  Loader2,
  Tag,
  Users,
  GitCommit,
  MessageSquare,
  FileText,
  AlertTriangle,
  Layers,
} from 'lucide-react';

interface DecisionDrawerProps {
  decisionId: string | null;
  onClose: () => void;
  onSelectDecision?: (decisionId: string) => void;
  onSelectCitation?: (citationId: string) => void;
  linkedEntities?: string[];
}

export const DecisionDrawer: React.FC<DecisionDrawerProps> = ({
  decisionId,
  onClose,
  onSelectDecision,
  onSelectCitation,
  linkedEntities,
}) => {
  const [detail, setDetail] = useState<DecisionDetail | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!decisionId) {
      setDetail(null);
      return;
    }

    let isMounted = true;
    setIsLoading(true);
    setError(null);

    fetchDecisionDetail(decisionId)
      .then((data) => {
        if (isMounted) {
          setDetail(data);
          setIsLoading(false);
        }
      })
      .catch((err) => {
        if (isMounted) {
          setError(err?.message || 'Failed to load decision detail');
          setIsLoading(false);
        }
      });

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);

    return () => {
      isMounted = false;
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [decisionId, onClose]);

  if (!decisionId) return null;

  const handleCopy = () => {
    if (!detail) return;
    const textToCopy = `Decision ${detail.id} (${detail.state}): ${detail.summary}\nRationale: ${detail.rationale || 'N/A'}`;
    navigator.clipboard.writeText(textToCopy);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const renderStateBadge = (state: DecisionState) => {
    switch (state) {
      case 'ACTIVE':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-mono font-medium bg-[#2ea043]/15 text-[#3fb950] border border-[#2ea043]/30 status-badge-active">
            <Check className="w-3.5 h-3.5 text-[#3fb950] stroke-[2.5] status-icon-active" />
            Active
          </span>
        );
      case 'SUPERSEDED':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-mono font-medium bg-[#efede5] text-[#77776e] border border-[#d7d2c6] status-badge-superseded">
            <ArrowRight className="w-3.5 h-3.5 text-[#77776e] status-icon-superseded" />
            Superseded
          </span>
        );
      case 'REJECTED':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-mono font-medium bg-[#da3633]/15 text-[#f85149] border border-[#da3633]/30 status-badge-rejected">
            <X className="w-3.5 h-3.5 text-[#f85149] stroke-[2.5] status-icon-rejected" />
            Rejected
          </span>
        );
      case 'UNRESOLVED':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-mono font-medium bg-[#d29922]/15 text-[#e3b341] border border-[#d29922]/30 status-badge-unresolved">
            <HelpCircle className="w-3.5 h-3.5 text-[#e3b341] status-icon-unresolved" />
            Needs Review
          </span>
        );
    }
  };

  const authors = detail?.citations
    ? Array.from(new Set(detail.citations.map((c) => c.author).filter((a): a is string => Boolean(a))))
    : [];

  return (
    <div className="fixed inset-0 z-50 overflow-hidden flex justify-end">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/60 transition-opacity"
        onClick={onClose}
      />

      {/* Drawer Container */}
      <div className="relative w-full max-w-lg bg-[#fffdf8] border-l border-[#d7d2c6] h-full shadow-2xl flex flex-col z-10">
        {/* Header */}
        <div className="sticky top-0 z-20 p-4 border-b border-[#d7d2c6] flex items-center justify-between bg-[#fffdf8]">
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded bg-[#efede5] text-[#617c50] border border-[#d7d2c6]">
              <Layers className="w-4 h-4" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-mono text-sm font-semibold text-[#292b25]">
                  Decision {decisionId}
                </span>
                {detail && renderStateBadge(detail.state)}
              </div>
              <span className="text-[11px] font-mono text-[#77776e]">
                Provenance Record
              </span>
            </div>
          </div>

          <div className="flex items-center gap-1.5">
            <button
              onClick={handleCopy}
              className="p-1.5 rounded bg-[#efede5] hover:bg-[#d7d2c6] text-[#51534b] hover:text-white transition-colors cursor-pointer"
              title="Copy decision summary"
            >
              {copied ? <CheckCheck className="w-4 h-4 text-[#3fb950]" /> : <Copy className="w-4 h-4 text-[#77776e]" />}
            </button>
            <button
              onClick={onClose}
              className="p-1.5 rounded bg-[#efede5] hover:bg-[#d7d2c6] text-[#77776e] hover:text-[#292b25] transition-colors cursor-pointer"
              title="Close drawer (Esc)"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Content Body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {isLoading && (
            <div className="py-16 flex flex-col items-center justify-center text-[#77776e] gap-2">
              <Loader2 className="w-6 h-6 animate-spin text-[#617c50]" />
              <p className="text-xs font-mono">Loading decision record...</p>
            </div>
          )}

          {error && (
            <div className="p-3.5 rounded bg-[#f5f3ed] border border-[#da3633]/40 text-[#f85149] space-y-1">
              <div className="flex items-center gap-2 font-medium text-xs">
                <AlertCircle className="w-4 h-4" />
                <span>Failed to load decision</span>
              </div>
              <p className="text-xs font-mono text-[#51534b]">{error}</p>
            </div>
          )}

          {detail && !isLoading && (
            <>
              {/* Summary */}
              <div className="space-y-1.5">
                <h3 className="text-xs font-mono uppercase tracking-wider text-[#77776e]">
                  Summary
                </h3>
                <p className="text-sm font-medium text-[#292b25] leading-relaxed bg-[#f5f3ed] p-3 rounded border border-[#d7d2c6]">
                  {detail.summary}
                </p>
              </div>

              {/* Rationale */}
              <div className="space-y-1.5">
                <h3 className="text-xs font-mono uppercase tracking-wider text-[#77776e]">
                  Rationale
                </h3>
                {detail.rationale ? (
                  <div className="quote-text p-3 rounded bg-[#f5f3ed] border border-[#d7d2c6] text-[#51534b] leading-relaxed border-l-2 border-l-[#54734f]">
                    "{detail.rationale}"
                  </div>
                ) : (
                  <div className="p-3 rounded bg-[#f5f3ed] border border-[#d7d2c6] text-[#77776e] text-xs italic">
                    No explicit quoted rationale recorded in the source artifact.
                  </div>
                )}
              </div>

              {/* Linked Entities */}
              {linkedEntities && linkedEntities.length > 0 && (
                <div className="space-y-1.5">
                  <h3 className="text-xs font-mono uppercase tracking-wider text-[#77776e] flex items-center gap-1.5">
                    <Tag className="w-3.5 h-3.5 text-[#617c50]" />
                    Linked Code Entities ({linkedEntities.length})
                  </h3>
                  <div className="flex flex-wrap gap-1.5">
                    {linkedEntities.map((ent) => {
                      const colon = ent.lastIndexOf(':');
                      const label = colon >= 0 && colon < ent.length - 1 ? ent.slice(colon + 1) : ent;
                      return (
                        <span
                          key={ent}
                          className="px-2 py-0.5 rounded bg-[#f5f3ed] border border-[#d7d2c6] text-[#617c50] font-mono text-xs"
                        >
                          {label}
                        </span>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Authors */}
              {authors.length > 0 && (
                <div className="space-y-1.5">
                  <h3 className="text-xs font-mono uppercase tracking-wider text-[#77776e] flex items-center gap-1.5">
                    <Users className="w-3.5 h-3.5 text-[#617c50]" />
                    Recorded Authors ({authors.length})
                  </h3>
                  <div className="flex flex-wrap gap-1.5">
                    {authors.map((author) => (
                      <span
                        key={author}
                        className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-[#f5f3ed] border border-[#d7d2c6] text-xs font-mono text-[#51534b]"
                      >
                        <span className="w-1.5 h-1.5 rounded-full bg-[#2ea043]" />
                        @{author}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Source Reference & Rule */}
              <div className="grid grid-cols-2 gap-2.5">
                <div className="p-2.5 rounded bg-[#f5f3ed] border border-[#d7d2c6] space-y-1">
                  <span className="text-[10px] font-mono text-[#77776e] uppercase">
                    Source Artifact
                  </span>
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-mono font-medium text-[#292b25] flex items-center gap-1.5">
                      {detail.source.type === 'Commit' ? (
                        <GitCommit className="w-3.5 h-3.5 text-[#77776e]" />
                      ) : detail.source.type === 'Issue' ? (
                        <MessageSquare className="w-3.5 h-3.5 text-[#77776e]" />
                      ) : detail.source.type === 'Document' ? (
                        <FileText className="w-3.5 h-3.5 text-[#77776e]" />
                      ) : (
                        <GitPullRequest className="w-3.5 h-3.5 text-[#a371f7]" />
                      )}
                      {detail.source.type} {detail.source.number ? `#${detail.source.number}` : ''}
                    </span>
                    {detail.source.url && (
                      <a
                        href={detail.source.url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-xs text-[#617c50] hover:underline"
                        title="Open Source Link"
                      >
                        <ExternalLink className="w-3.5 h-3.5" />
                      </a>
                    )}
                  </div>
                </div>

                <div className="p-2.5 rounded bg-[#f5f3ed] border border-[#d7d2c6] space-y-1">
                  <span className="text-[10px] font-mono text-[#77776e] uppercase">
                    Supersession Rule
                  </span>
                  <div className="text-xs font-mono font-medium text-[#51534b] truncate">
                    {detail.rule ? detail.rule : 'Direct ingest'}
                  </div>
                </div>
              </div>

              {/* Temporal Timeline */}
              <div className="p-3 rounded bg-[#f5f3ed] border border-[#d7d2c6] space-y-1.5">
                <span className="text-[10px] font-mono text-[#77776e] uppercase tracking-wider block">
                  Temporal Timeline
                </span>
                <div className="space-y-1 text-xs font-mono">
                  {detail.recorded_at && (
                    <div className="flex items-center justify-between text-[#51534b]">
                      <span className="text-[#77776e] flex items-center gap-1.5">
                        <Calendar className="w-3.5 h-3.5 text-[#929086]" /> Recorded:
                      </span>
                      <span>{new Date(detail.recorded_at).toLocaleDateString()}</span>
                    </div>
                  )}
                  {detail.effective_at && (
                    <div className="flex items-center justify-between text-[#51534b]">
                      <span className="text-[#77776e] flex items-center gap-1.5">
                        <Clock className="w-3.5 h-3.5 text-[#2ea043]" /> Effective:
                      </span>
                      <span>{new Date(detail.effective_at).toLocaleDateString()}</span>
                    </div>
                  )}
                  {detail.ended_at && (
                    <div className="flex items-center justify-between text-[#f85149]">
                      <span className="text-[#77776e] flex items-center gap-1.5">
                        <Clock className="w-3.5 h-3.5 text-[#da3633]" /> Ended:
                      </span>
                      <span>{new Date(detail.ended_at).toLocaleDateString()}</span>
                    </div>
                  )}
                </div>
              </div>

              {/* Supersession Relationships */}
              <div className="space-y-2">
                <h3 className="text-xs font-mono uppercase tracking-wider text-[#77776e]">
                  Supersession Lineage
                </h3>

                <div className="p-2.5 rounded bg-[#f5f3ed] border border-[#d7d2c6] text-[11px] font-mono text-[#77776e] flex items-start gap-2">
                  <AlertTriangle className="w-3.5 h-3.5 text-[#d29922] shrink-0 mt-0.5" />
                  <span>
                    Supersession is corroborated by actual state and lineage rules rather than timestamps alone.
                  </span>
                </div>

                <div className="space-y-1.5">
                  {detail.supersedes && detail.supersedes.length > 0 && (
                    <div className="p-2.5 rounded bg-[#f5f3ed] border border-[#d7d2c6] text-xs font-mono flex items-center justify-between">
                      <span className="text-[#77776e]">Supersedes:</span>
                      <div className="flex flex-wrap gap-1.5">
                        {detail.supersedes.map((id, index) => (
                          <button
                            key={id}
                            onClick={() => onSelectDecision?.(id)}
                            className="px-2 py-0.5 rounded bg-[#efede5] hover:bg-[#d7d2c6] text-[#617c50] border border-[#d7d2c6] transition-colors cursor-pointer"
                          >
                            Decision {index + 1}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}

                  {detail.superseded_by && detail.superseded_by.length > 0 && (
                    <div className="p-2.5 rounded bg-[#f5f3ed] border border-[#d7d2c6] text-xs font-mono flex items-center justify-between">
                      <span className="text-[#77776e]">Superseded by:</span>
                      <div className="flex flex-wrap gap-1.5">
                        {detail.superseded_by.map((id, index) => (
                          <button
                            key={id}
                            onClick={() => onSelectDecision?.(id)}
                            className="px-2 py-0.5 rounded bg-[#efede5] hover:bg-[#d7d2c6] text-[#e3b341] border border-[#d7d2c6] transition-colors cursor-pointer"
                          >
                            Decision {index + 1}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>

              {/* Citations Attached */}
              {detail.citations && detail.citations.length > 0 && (
                <div className="space-y-2">
                  <h3 className="text-xs font-mono uppercase tracking-wider text-[#77776e]">
                    Direct Verified Evidence ({detail.citations.length})
                  </h3>
                  <div className="space-y-2">
                    {detail.citations.map((c) => (
                      <div
                        key={c.id}
                        onClick={() => onSelectCitation?.(c.id)}
                        className="p-3 rounded bg-[#f5f3ed] border border-[#d7d2c6] hover:border-[#bdb8ab] transition-colors cursor-pointer"
                      >
                        <div className="flex items-center justify-between text-[11px] font-mono text-[#77776e] mb-1">
                          <span className="text-[#617c50] font-medium">{c.source_type}</span>
                          <span>{c.author ? `@${c.author}` : 'Anonymous'}</span>
                        </div>
                        <p className="quote-text text-xs text-[#51534b] leading-relaxed border-l-2 border-[#54734f] pl-2.5">
                          "{c.quote}"
                        </p>
                        {c.source_url && (
                          <div className="mt-2 text-right">
                            <a
                              href={c.source_url}
                              target="_blank"
                              rel="noreferrer"
                              onClick={(e) => e.stopPropagation()}
                              className="inline-flex items-center gap-1 text-[11px] font-mono text-[#617c50] hover:underline"
                            >
                              <span>View Source</span>
                              <ExternalLink className="w-3 h-3" />
                            </a>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Evidence Gaps */}
              {detail.evidence_gaps && detail.evidence_gaps.length > 0 && (
                <div className="space-y-1.5">
                  <h3 className="text-xs font-mono uppercase tracking-wider text-[#d29922] flex items-center gap-1.5">
                    <ShieldAlert className="w-3.5 h-3.5" />
                    Evidence Gaps ({detail.evidence_gaps.length})
                  </h3>
                  <ul className="space-y-1 bg-[#f5f3ed] border border-[#d29922]/30 p-2.5 rounded text-xs text-[#51534b] font-mono">
                    {detail.evidence_gaps.map((gap, i) => (
                      <li key={i} className="flex items-start gap-1.5">
                        <span className="text-[#d29922]">•</span>
                        <span>{gap}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
};
