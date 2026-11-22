import React, { useState, useEffect } from 'react';
import type { Repository, Decision, DecisionListItem, DecisionState, QuestionContext } from '../types';
import { fetchRepositoryDecisionHistory, fetchRepositoryDecisions } from '../services/api';
import { DecisionDrawer } from './DecisionDrawer';
import {
  Layers,
  Check,
  ArrowRight,
  X,
  HelpCircle,
  Calendar,
  GitPullRequest,
  Tag,
  ExternalLink,
  Search,
  Filter,
  AlertCircle,
  Loader2,
  AlertTriangle,
  GitBranch,
} from 'lucide-react';

function entityDisplayName(ent: string): string {
  const colon = ent.lastIndexOf(':');
  if (colon >= 0 && colon < ent.length - 1) {
    return ent.slice(colon + 1);
  }
  return ent;
}

function isVisibleEntity(ent: string): boolean {
  return Boolean(entityDisplayName(ent).trim());
}

interface DecisionHistoryViewProps {
  selectedRepo: Repository | null;
  questionContext: QuestionContext | null;
  onAskQuestion: () => void;
}

export const DecisionHistoryView: React.FC<DecisionHistoryViewProps> = ({
  selectedRepo,
  questionContext,
  onAskQuestion,
}) => {
  const [allDecisions, setAllDecisions] = useState<DecisionListItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [stateFilter, setStateFilter] = useState<'ALL' | DecisionState>('ALL');
  const [entityQuery, setEntityQuery] = useState('');

  // Selected decision for the shared drawer
  const [selectedDecisionId, setSelectedDecisionId] = useState<string | null>(null);

  const repoId = selectedRepo?.id ?? '';
  const activeQuestion = repoId && questionContext?.repositoryId === repoId ? questionContext : null;

  useEffect(() => {
    let cancelled = false;
    setError(null);

    if (!repoId) {
      setAllDecisions([]);
      setIsLoading(false);
      return () => {
        cancelled = true;
      };
    }

    setIsLoading(true);

    const load = async (): Promise<DecisionListItem[]> => {
      // No question yet: fall back to the full repository history.
      if (!activeQuestion) {
        const data = await fetchRepositoryDecisionHistory(repoId);
        return data.items;
      }

      const entityId = activeQuestion.response.entity?.id;
      if (entityId) {
        const data = await fetchRepositoryDecisions(repoId, { entity_id: entityId, limit: 200 });
        return data.items;
      }

      return activeQuestion.response.decisions.map(
        (decision: Decision): DecisionListItem => ({
          id: decision.id,
          summary: decision.summary,
          state: decision.state,
          date: decision.effective_at,
          source_url: decision.source.url,
          entities: [],
          supersedes: decision.supersedes,
          superseded_by: decision.superseded_by,
          rule: decision.rule,
        })
      );
    };

    load()
      .then((items) => {
        if (!cancelled) setAllDecisions(items);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(
          err instanceof Error
            ? err.message
            : activeQuestion
              ? 'Failed to load question-related decision history'
              : 'Failed to load repository decision history'
        );
        setAllDecisions([]);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [repoId, activeQuestion]);

  const displayedDecisions = allDecisions.filter((d) => {
    if (stateFilter !== 'ALL' && d.state !== stateFilter) return false;
    if (!entityQuery.trim()) return true;
    const q = entityQuery.toLowerCase().trim();
    const matchesSummary = d.summary.toLowerCase().includes(q);
    const matchesEntity = d.entities.some((e) => e.toLowerCase().includes(q));
    const matchesId = d.id.toLowerCase().includes(q);
    return matchesSummary || matchesEntity || matchesId;
  });

  const stateCounts = allDecisions.reduce<Record<string, number>>((acc, d) => {
    acc[d.state] = (acc[d.state] || 0) + 1;
    return acc;
  }, {});

  const selectedDecisionItem = allDecisions.find((d) => d.id === selectedDecisionId);

  return (
    <div className="flex flex-col h-[calc(100vh-4rem)] w-full bg-[#191628] text-[#F7ECE1] overflow-y-auto">
      {/* Header Context Bar */}
      <div className="shrink-0 flex flex-wrap items-center justify-between gap-3 px-4 sm:px-6 py-2.5 border-b border-[#CAC4CE]/20 bg-[#242038]">
        <div className="flex items-center gap-2">
          <span className="text-xs font-mono text-[#CAC4CE]">
            Decision Lineage /
          </span>
          <span className="font-mono text-xs font-semibold text-[#F7ECE1] bg-[#161324] px-2 py-0.5 rounded border border-[#CAC4CE]/25 flex items-center gap-1.5">
            <GitBranch className="w-3.5 h-3.5 text-[#9067C6]" />
            {selectedRepo?.name || repoId}
          </span>
        </div>

        <div className="flex items-center gap-2 text-xs font-mono text-[#CAC4CE]">
          <span>
            {displayedDecisions.length} decisions
          </span>
        </div>
      </div>

      <div className="flex-1 p-4 sm:p-6 max-w-5xl mx-auto w-full space-y-4">
        {repoId && (
          <>
            {/* Scoped Question Header, or the repo-wide default */}
            {activeQuestion ? (
              <div className="p-4 rounded-xl bg-[#242038] border border-[#CAC4CE]/20 space-y-2 shadow-sm">
                <span className="text-[10px] font-mono uppercase tracking-wider text-[#CAC4CE] font-semibold">
                  History Scoped by Question:
                </span>
                <p className="text-xs sm:text-sm font-sans font-medium text-[#F7ECE1] leading-snug">
                  "{activeQuestion.question}"
                </p>
                {activeQuestion.response.entity && (
                  <div className="flex items-center gap-2 pt-0.5 text-xs font-mono text-[#CAC4CE]">
                    <span>Target Entity:</span>
                    <span className="px-2 py-0.5 rounded bg-[#161324] border border-[#CAC4CE]/25 text-[#C5B0E6] font-mono text-[11px]">
                      {activeQuestion.response.entity.label}
                    </span>
                  </div>
                )}
              </div>
            ) : (
              <div className="p-3.5 rounded-xl bg-[#242038] border border-[#CAC4CE]/20 text-xs font-mono text-[#CAC4CE] flex items-start gap-2.5 shadow-sm">
                <Layers className="w-4 h-4 text-[#9067C6] shrink-0 mt-0.5" />
                <div className="space-y-1.5">
                  <p className="leading-relaxed">
                    Showing every decision recorded for{' '}
                    <span className="text-[#F7ECE1]">{selectedRepo?.name || repoId}</span>. Ask a question in the
                    Workspace to narrow the history to one entity.
                  </p>
                  <button
                    type="button"
                    onClick={onAskQuestion}
                    className="text-[#C5B0E6] hover:text-[#F7ECE1] transition-colors cursor-pointer"
                  >
                    Ask about this repository →
                  </button>
                </div>
              </div>
            )}

            {/* Filters Bar */}
            <div className="flex flex-wrap items-center justify-between gap-3">
              {/* State Filter Buttons */}
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className="mr-1 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-[#CAC4CE]">
                  <Filter className="w-3.5 h-3.5 text-[#9067C6]" /> State:
                </span>
                <div
                  className="inline-flex items-center p-1 rounded-lg bg-[#242038] border border-[#CAC4CE]/20 gap-1"
                  role="group"
                  aria-label="Filter decisions by state"
                >
                  {(['ALL', 'ACTIVE', 'SUPERSEDED', 'REJECTED', 'UNRESOLVED'] as const).map((st) => {
                    const isActive = stateFilter === st;
                    return (
                      <button
                        key={st}
                        type="button"
                        onClick={() => setStateFilter(st)}
                        aria-pressed={isActive}
                        data-state-filter={st}
                        className={`filter-segment px-2.5 py-1 rounded-md text-xs font-mono transition-all flex items-center gap-1.5 cursor-pointer ${
                          isActive
                            ? 'bg-[#9067C6] text-white border border-[#9067C6] font-medium shadow-sm'
                            : 'text-[#CAC4CE] hover:text-[#F7ECE1] hover:bg-[#322D4D] border border-transparent'
                        }`}
                      >
                        <span>{st === 'ALL' ? 'All' : st}</span>
                        {st !== 'ALL' && stateCounts[st] !== undefined && (
                          <span
                            className={`filter-segment-count text-[10px] px-1.5 py-0.2 rounded-full ${
                              isActive
                                ? 'bg-white/20 text-white font-semibold'
                                : 'bg-[#161324] text-[#CAC4CE]'
                            }`}
                          >
                            {stateCounts[st]}
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Entity Filter Form */}
              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[#CAC4CE]" />
                <input
                  type="text"
                  value={entityQuery}
                  onChange={(e) => setEntityQuery(e.target.value)}
                  placeholder="Filter decisions"
                  className="pl-8 pr-3 py-1.5 bg-[#161324] border border-[#CAC4CE]/25 rounded-lg text-xs font-mono text-[#F7ECE1] placeholder:text-[#CAC4CE]/65 focus:outline-none focus:border-[#9067C6] focus:ring-1 focus:ring-[#9067C6]/35 w-48 sm:w-56 transition-all"
                />
              </div>
            </div>

            {/* Invariant Rule Callout */}
            <div className="p-3.5 rounded-xl bg-[#242038] border border-[#9067C6]/35 text-xs font-mono text-[#CAC4CE] flex items-start gap-2.5 shadow-sm">
              <AlertTriangle className="w-4 h-4 text-[#9067C6] shrink-0 mt-0.5" />
              <p className="leading-relaxed">
                <strong className="text-[#F7ECE1] font-medium">Supersession Rule:</strong> A newer decision does not automatically supersede an older decision.
                It is marked superseded only when corroborated by a documented lineage rule (e.g. revert commit or config key change).
              </p>
            </div>
          </>
        )}

        {/* Loading State */}
        {isLoading && (
          <div className="py-16 flex flex-col items-center justify-center text-[#CAC4CE] gap-2">
            <Loader2 className="w-6 h-6 animate-spin text-[#9067C6]" />
            <p className="text-xs font-mono">Fetching chronological decision records...</p>
          </div>
        )}

        {/* Error State */}
        {!isLoading && error && (
          <div className="p-4 rounded-xl bg-[#242038] border border-[#f85149]/45 text-[#f85149] space-y-1">
            <div className="flex items-center gap-2 font-medium text-xs">
              <AlertCircle className="w-4 h-4 text-[#f85149]" />
              <span>Failed to load decisions</span>
            </div>
            <p className="text-xs font-mono text-[#CAC4CE]">{error}</p>
          </div>
        )}

        {/* Empty State */}
        {!isLoading && !error && displayedDecisions.length === 0 && (
          <div className="p-8 rounded-xl bg-[#242038] border border-[#CAC4CE]/20 text-center space-y-2">
            <Layers className="w-6 h-6 text-[#8D86C9] mx-auto" />
            <h3 className="text-sm font-semibold text-[#F7ECE1]">
              {allDecisions.length === 0 ? 'No decisions recorded' : 'No decisions match filters'}
            </h3>
            <p className="text-xs font-mono text-[#CAC4CE]">
              {allDecisions.length === 0
                ? 'This repository has no recorded decisions yet.'
                : 'No decisions match the current state or entity filter for this repository.'}
            </p>
          </div>
        )}

        {/* Chronological Decisions List */}
        {!isLoading && !error && displayedDecisions.length > 0 && (
          <div className="relative pl-6 space-y-3">
            {/* Visual Spine */}
            <div className="absolute left-2.5 top-4 bottom-4 w-px bg-[#CAC4CE]/20 pointer-events-none" />

            {displayedDecisions.map((decision) => {
              const renderStateConfig = () => {
                switch (decision.state) {
                  case 'ACTIVE':
                    return {
                      containerClass: 'bg-[#242038] border border-[#3fb950]/35 hover:border-[#3fb950]/70 status-card-active',
                      badgeClass: 'bg-[#3fb950]/15 text-[#3fb950] border border-[#3fb950]/35 status-badge-active',
                      icon: <Check className="w-3.5 h-3.5 text-[#3fb950] stroke-[2.5] status-icon-active" />,
                      label: 'Active',
                      summaryClass: 'text-[#F7ECE1] font-medium',
                      dotClass: 'bg-[#3fb950] status-dot-active',
                    };
                  case 'SUPERSEDED':
                    return {
                      containerClass: 'bg-[#242038]/85 border border-[#CAC4CE]/20 hover:border-[#9067C6]/50 status-card-superseded',
                      badgeClass: 'bg-[#CAC4CE]/15 text-[#CAC4CE] border border-[#CAC4CE]/35 status-badge-superseded',
                      icon: <ArrowRight className="w-3.5 h-3.5 text-[#CAC4CE] status-icon-superseded" />,
                      label: 'Superseded',
                      summaryClass: 'text-[#CAC4CE] line-through decoration-[#CAC4CE]/60',
                      dotClass: 'bg-[#CAC4CE] status-dot-superseded',
                    };
                  case 'REJECTED':
                    return {
                      containerClass: 'bg-[#242038] border border-[#f85149]/35 hover:border-[#f85149]/70 status-card-rejected',
                      badgeClass: 'bg-[#f85149]/15 text-[#f85149] border border-[#f85149]/35 status-badge-rejected',
                      icon: <X className="w-3.5 h-3.5 text-[#f85149] stroke-[2.5] status-icon-rejected" />,
                      label: 'Rejected',
                      summaryClass: 'text-[#F7ECE1]',
                      dotClass: 'bg-[#f85149] status-dot-rejected',
                    };
                  case 'UNRESOLVED':
                    return {
                      containerClass: 'bg-[#242038] border border-[#e3b341]/35 hover:border-[#e3b341]/70 status-card-unresolved',
                      badgeClass: 'bg-[#e3b341]/15 text-[#e3b341] border border-[#e3b341]/35 status-badge-unresolved',
                      icon: <HelpCircle className="w-3.5 h-3.5 text-[#e3b341] status-icon-unresolved" />,
                      label: 'Needs Review',
                      summaryClass: 'text-[#F7ECE1]',
                      dotClass: 'bg-[#e3b341] status-dot-unresolved',
                    };
                  default:
                    return {
                      containerClass: 'bg-[#242038] border border-[#CAC4CE]/20',
                      badgeClass: 'bg-[#161324] text-[#CAC4CE] border border-[#CAC4CE]/25',
                      icon: <Layers className="w-3.5 h-3.5 text-[#8D86C9]" />,
                      label: decision.state,
                      summaryClass: 'text-[#F7ECE1]',
                      dotClass: 'bg-[#8D86C9]',
                    };
                }
              };

              const style = renderStateConfig();
              const visibleEntities = decision.entities;

              return (
                <div key={decision.id} className="relative group">
                  {/* Spine Node Dot */}
                  <div
                    className={`absolute -left-6 top-4 w-2.5 h-2.5 rounded-full ${style.dotClass} border border-[#191628] z-10`}
                  />

                  {/* Decision Row Card */}
                  <div
                    onClick={() => setSelectedDecisionId(decision.id)}
                    className={`rounded-xl p-4 transition-all cursor-pointer shadow-sm ${style.containerClass}`}
                  >
                    {/* Header Row: State Badge, ID, Date, and Source Link */}
                    <div className="flex flex-wrap items-center justify-between gap-2.5 mb-2">
                      <div className="flex items-center gap-2">
                        <span
                          className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-mono font-medium ${style.badgeClass}`}
                        >
                          {style.icon}
                          <span>{style.label}</span>
                        </span>

                        {decision.rule && (
                          <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-[#161324] text-[#CAC4CE] border border-[#CAC4CE]/25">
                            Rule: {decision.rule}
                          </span>
                        )}
                      </div>

                      <div className="flex items-center gap-2.5 text-xs font-mono text-[#CAC4CE]">
                        <span className="flex items-center gap-1 text-[#CAC4CE]">
                          <Calendar className="w-3.5 h-3.5 text-[#8D86C9]" />
                          <span>{decision.date ? new Date(decision.date).toLocaleDateString() : 'date unknown'}</span>
                        </span>

                        {decision.source_url && (
                          <a
                            href={decision.source_url}
                            target="_blank"
                            rel="noreferrer"
                            onClick={(e) => e.stopPropagation()}
                            className="inline-flex items-center gap-1 text-[#C5B0E6] hover:text-[#F7ECE1] hover:underline"
                            title="Open original pull request"
                          >
                            <GitPullRequest className="w-3.5 h-3.5" />
                            <span>PR</span>
                            <ExternalLink className="w-3 h-3" />
                          </a>
                        )}
                      </div>
                    </div>

                    {/* Summary */}
                    <p className={`text-xs sm:text-sm leading-relaxed ${style.summaryClass}`}>
                      {decision.summary}
                    </p>

                    {/* Lineage & Entities Footer */}
                    <div className="mt-2.5 pt-2 border-t border-[#CAC4CE]/15 flex flex-wrap items-center justify-between gap-2 text-xs font-mono">
                      {/* Linked Entities */}
                      <div className="flex flex-wrap items-center gap-1.5">
                        {visibleEntities.length > 0 && (
                          <>
                            <Tag className="w-3 h-3 text-[#8D86C9]" />
                            {visibleEntities.map((ent) => (
                              <span
                                key={ent}
                                className="px-2 py-0.5 rounded bg-[#161324] text-[#C5B0E6] border border-[#CAC4CE]/20 text-[11px]"
                              >
                                {entityDisplayName(ent)}
                              </span>
                            ))}
                          </>
                        )}
                      </div>

                      {/* Supersession Links */}
                      <div className="flex items-center gap-3">
                        {decision.supersedes && decision.supersedes.length > 0 && (
                          <span className="text-[#CAC4CE] text-[11px]">
                            Supersedes {decision.supersedes.length} earlier{' '}
                            {decision.supersedes.length === 1 ? 'decision' : 'decisions'}
                          </span>
                        )}

                        {decision.superseded_by && decision.superseded_by.length > 0 && (
                          <span className="text-[#C5B0E6] text-[11px] flex items-center gap-1">
                            <ArrowRight className="w-3 h-3" />
                            <span>Replaced</span>
                          </span>
                        )}

                        <span className="text-[#C5B0E6] hover:text-[#F7ECE1] font-medium flex items-center gap-1 transition-colors">
                          <span>Details</span>
                          <ArrowRight className="w-3 h-3" />
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Shared Decision Detail Drawer */}
      <DecisionDrawer
        decisionId={selectedDecisionId}
        onClose={() => setSelectedDecisionId(null)}
        onSelectDecision={(id) => setSelectedDecisionId(id)}
        linkedEntities={selectedDecisionItem?.entities}
      />
    </div>
  );
};
