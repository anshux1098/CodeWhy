import React, { useState, useEffect } from 'react';
import type { Repository, Decision, DecisionListItem, DecisionState, QuestionContext } from '../types';
import { fetchRepositoryDecisions } from '../services/api';
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
  return entityDisplayName(ent).toLowerCase() !== 'src/urllib3/connection.py';
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

  const repoId = selectedRepo?.id || 'acme-netclient';
  const activeQuestion = questionContext?.repositoryId === repoId ? questionContext : null;

  useEffect(() => {
    let cancelled = false;
    setError(null);

    if (!activeQuestion) {
      setAllDecisions([]);
      setIsLoading(false);
      return () => {
        cancelled = true;
      };
    }

    setIsLoading(true);
    const entityId = activeQuestion.response.entity?.id;
    const decisions = entityId
      ? fetchRepositoryDecisions(repoId, { entity_id: entityId, limit: 200 }).then((data) => data.items)
      : Promise.resolve(
          activeQuestion.response.decisions.map(
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
          )
        );

    decisions
      .then((items) => {
        if (!cancelled) setAllDecisions(items);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : 'Failed to load question-related decision history');
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
    <div className="flex flex-col h-[calc(100vh-4rem)] w-full bg-[#f5f3ed] overflow-y-auto">
      {/* Header Context Bar */}
      <div className="shrink-0 flex flex-wrap items-center justify-between gap-3 px-4 sm:px-6 py-2.5 border-b border-[#d7d2c6] bg-[#fffdf8]">
        <div className="flex items-center gap-2">
          <span className="text-xs font-mono text-[#77776e]">
            Decision Lineage /
          </span>
          <span className="font-mono text-xs font-semibold text-[#292b25] bg-[#efede5] px-2 py-0.5 rounded border border-[#d7d2c6] flex items-center gap-1.5">
            <GitBranch className="w-3.5 h-3.5 text-[#617c50]" />
            {selectedRepo?.name || repoId}
          </span>
        </div>

        <div className="flex items-center gap-2 text-xs font-mono text-[#77776e]">
          <span>
            {displayedDecisions.length} decisions
          </span>
        </div>
      </div>

      <div className="flex-1 p-4 sm:p-6 max-w-5xl mx-auto w-full space-y-4">
        {activeQuestion && (
          <>
            {/* Scoped Question Header */}
            <div className="p-3.5 rounded-lg bg-[#fffdf8] border border-[#d7d2c6] space-y-1.5">
              <span className="text-[10px] font-mono uppercase tracking-wider text-[#77776e]">
                History Scoped by Question:
              </span>
              <p className="text-xs sm:text-sm font-sans font-medium text-[#292b25]">
                "{activeQuestion.question}"
              </p>
              {activeQuestion.response.entity && (
                <div className="flex items-center gap-2 pt-1 text-xs font-mono text-[#77776e]">
                  <span>Target Entity:</span>
                  <span className="px-1.5 py-0.2 rounded bg-[#f5f3ed] border border-[#d7d2c6] text-[#617c50]">
                    {activeQuestion.response.entity.label}
                  </span>
                </div>
              )}
            </div>

            {/* Filters Bar */}
            <div className="flex flex-wrap items-center justify-between gap-2.5">
              {/* State Filter Buttons */}
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className="mr-1 flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wider text-[#77776e]">
                  <Filter className="w-3 h-3 text-[#617c50]" /> State:
                </span>
                <div className="filter-segment-group" role="group" aria-label="Filter decisions by state">
                  {(['ALL', 'ACTIVE', 'SUPERSEDED', 'REJECTED', 'UNRESOLVED'] as const).map((st) => (
                    <button
                      key={st}
                      type="button"
                      onClick={() => setStateFilter(st)}
                      aria-pressed={stateFilter === st}
                      data-state-filter={st}
                      className="filter-segment cursor-pointer"
                    >
                      <span>{st === 'ALL' ? 'All' : st}</span>
                      {st !== 'ALL' && stateCounts[st] !== undefined && (
                        <span className="filter-segment-count">{stateCounts[st]}</span>
                      )}
                    </button>
                  ))}
                </div>
              </div>

              {/* Entity Filter Form */}
              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[#77776e]" />
                <input
                  type="text"
                  value={entityQuery}
                  onChange={(e) => setEntityQuery(e.target.value)}
                  placeholder="Filter decisions"
                  className="pl-7 pr-2.5 py-1 bg-[#fffdf8] border border-[#d7d2c6] rounded text-xs font-mono text-[#292b25] placeholder:text-[#929086] focus:outline-none focus:border-[#718d5e] w-48 sm:w-56"
                />
              </div>
            </div>

            {/* Invariant Rule Callout */}
            <div className="p-3 rounded bg-[#fffdf8] border border-[#d7d2c6] text-xs font-mono text-[#77776e] flex items-start gap-2">
              <AlertTriangle className="w-4 h-4 text-[#d29922] shrink-0 mt-0.5" />
              <p className="leading-relaxed">
                <strong className="text-[#292b25] font-medium">Supersession Rule:</strong> A newer decision does not automatically supersede an older decision.
                It is marked superseded only when corroborated by a documented lineage rule (e.g. revert commit or config key change).
              </p>
            </div>
          </>
        )}

        {!activeQuestion && (
          <div className="p-8 rounded-lg bg-[#fffdf8] border border-[#d7d2c6] text-center space-y-3">
            <Layers className="w-8 h-8 text-[#929086] mx-auto" />
            <h3 className="text-sm font-semibold text-[#292b25]">Ask a question to inspect decision history</h3>
            <p className="text-xs font-mono text-[#77776e] max-w-sm mx-auto">
              Decision history is scoped to the entity and governing decisions discovered in your investigation.
            </p>
            <button
              type="button"
              onClick={onAskQuestion}
              className="px-3.5 py-1.5 rounded bg-[#54734f] hover:bg-[#718d5e] text-white text-xs font-medium transition-colors cursor-pointer"
            >
              Open Workspace
            </button>
          </div>
        )}

        {/* Loading State */}
        {activeQuestion && isLoading && (
          <div className="py-16 flex flex-col items-center justify-center text-[#77776e] gap-2">
            <Loader2 className="w-6 h-6 animate-spin text-[#617c50]" />
            <p className="text-xs font-mono">Fetching chronological decision records...</p>
          </div>
        )}

        {/* Error State */}
        {activeQuestion && error && (
          <div className="p-4 rounded-lg bg-[#fffdf8] border border-[#da3633]/50 text-[#f85149] space-y-1">
            <div className="flex items-center gap-2 font-medium text-xs">
              <AlertCircle className="w-4 h-4 text-[#f85149]" />
              <span>Failed to load decisions</span>
            </div>
            <p className="text-xs font-mono text-[#51534b]">{error}</p>
          </div>
        )}

        {/* Empty State */}
        {activeQuestion && !isLoading && !error && displayedDecisions.length === 0 && (
          <div className="p-8 rounded-lg bg-[#fffdf8] border border-[#d7d2c6] text-center space-y-2">
            <Layers className="w-6 h-6 text-[#929086] mx-auto" />
            <h3 className="text-sm font-semibold text-[#292b25]">No decisions match filters</h3>
            <p className="text-xs font-mono text-[#77776e]">
              No decisions match the current state or entity filter for this repository.
            </p>
          </div>
        )}

        {/* Chronological Decisions List */}
        {activeQuestion && !isLoading && !error && displayedDecisions.length > 0 && (
          <div className="relative pl-6 space-y-3">
            {/* Visual Spine */}
            <div className="absolute left-2.5 top-4 bottom-4 w-px bg-[#d7d2c6] pointer-events-none" />

            {displayedDecisions.map((decision) => {
              const renderStateConfig = () => {
                switch (decision.state) {
                  case 'ACTIVE':
                    return {
                      containerClass: 'bg-[#fffdf8] border border-[#2ea043]/40 hover:border-[#2ea043]/70 status-card-active',
                      badgeClass: 'bg-[#2ea043]/15 text-[#3fb950] border border-[#2ea043]/30 status-badge-active',
                      icon: <Check className="w-3.5 h-3.5 text-[#3fb950] stroke-[2.5] status-icon-active" />,
                      label: 'Active',
                      summaryClass: 'text-[#292b25] font-medium',
                      dotClass: 'bg-[#2ea043] status-dot-active',
                    };
                  case 'SUPERSEDED':
                    return {
                      containerClass: 'bg-[#fffdf8]/70 border border-[#d7d2c6] opacity-75 hover:opacity-100 status-card-superseded',
                      badgeClass: 'bg-[#efede5] text-[#77776e] border border-[#d7d2c6] status-badge-superseded',
                      icon: <ArrowRight className="w-3.5 h-3.5 text-[#77776e] status-icon-superseded" />,
                      label: 'Superseded',
                      summaryClass: 'text-[#77776e] line-through decoration-[#bdb8ab]',
                      dotClass: 'bg-[#929086] status-dot-superseded',
                    };
                  case 'REJECTED':
                    return {
                      containerClass: 'bg-[#fffdf8] border border-[#da3633]/40 hover:border-[#da3633]/70 status-card-rejected',
                      badgeClass: 'bg-[#da3633]/15 text-[#f85149] border border-[#da3633]/30 status-badge-rejected',
                      icon: <X className="w-3.5 h-3.5 text-[#f85149] stroke-[2.5] status-icon-rejected" />,
                      label: 'Rejected',
                      summaryClass: 'text-[#292b25]',
                      dotClass: 'bg-[#da3633] status-dot-rejected',
                    };
                  case 'UNRESOLVED':
                    return {
                      containerClass: 'bg-[#fffdf8] border border-[#d29922]/40 hover:border-[#d29922]/70 status-card-unresolved',
                      badgeClass: 'bg-[#d29922]/15 text-[#e3b341] border border-[#d29922]/30 status-badge-unresolved',
                      icon: <HelpCircle className="w-3.5 h-3.5 text-[#e3b341] status-icon-unresolved" />,
                      label: 'Needs Review',
                      summaryClass: 'text-[#292b25]',
                      dotClass: 'bg-[#d29922] status-dot-unresolved',
                    };
                  default:
                    return {
                      containerClass: 'bg-[#fffdf8] border border-[#d7d2c6]',
                      badgeClass: 'bg-[#efede5] text-[#77776e] border border-[#d7d2c6]',
                      icon: <Layers className="w-3.5 h-3.5" />,
                      label: decision.state,
                      summaryClass: 'text-[#292b25]',
                      dotClass: 'bg-[#617c50]',
                    };
                }
              };

              const style = renderStateConfig();
              const visibleEntities = decision.entities.filter(isVisibleEntity);

              return (
                <div key={decision.id} className="relative group">
                  {/* Spine Node Dot */}
                  <div
                    className={`absolute -left-6 top-4 w-2.5 h-2.5 rounded-full ${style.dotClass} border border-[#f5f3ed] z-10`}
                  />

                  {/* Decision Row Card */}
                  <div
                    onClick={() => setSelectedDecisionId(decision.id)}
                    className={`rounded-lg p-3.5 transition-colors cursor-pointer ${style.containerClass}`}
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
                          <span className="px-1.5 py-0.2 rounded text-[10px] font-mono bg-[#efede5] text-[#77776e] border border-[#d7d2c6]">
                            Rule: {decision.rule}
                          </span>
                        )}
                      </div>

                      <div className="flex items-center gap-2.5 text-xs font-mono text-[#77776e]">
                        {decision.date && (
                          <span className="flex items-center gap-1 text-[#77776e]">
                            <Calendar className="w-3.5 h-3.5 text-[#929086]" />
                            <span>{new Date(decision.date).toLocaleDateString()}</span>
                          </span>
                        )}

                        {decision.source_url && (
                          <a
                            href={decision.source_url}
                            target="_blank"
                            rel="noreferrer"
                            onClick={(e) => e.stopPropagation()}
                            className="inline-flex items-center gap-1 text-[#617c50] hover:underline"
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
                    <div className="mt-2.5 pt-2 border-t border-[#d7d2c6] flex flex-wrap items-center justify-between gap-2 text-xs font-mono">
                      {/* Linked Entities */}
                      <div className="flex flex-wrap items-center gap-1.5">
                        {visibleEntities.length > 0 && (
                          <>
                            <Tag className="w-3 h-3 text-[#929086]" />
                            {visibleEntities.map((ent) => (
                              <span
                                key={ent}
                                className="px-1.5 py-0.2 rounded bg-[#f5f3ed] text-[#617c50] border border-[#d7d2c6] text-[11px]"
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
                          <span className="text-[#77776e] text-[11px]">
                            Supersedes {decision.supersedes.length} earlier{' '}
                            {decision.supersedes.length === 1 ? 'decision' : 'decisions'}
                          </span>
                        )}

                        {decision.superseded_by && decision.superseded_by.length > 0 && (
                          <span className="text-[#e3b341] text-[11px] flex items-center gap-1">
                            <ArrowRight className="w-3 h-3" />
                            <span>Replaced</span>
                          </span>
                        )}

                        <span className="text-[#617c50] font-medium flex items-center gap-1">
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
