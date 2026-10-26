import React, { useState, useEffect, useRef } from 'react';
import type {
  Repository,
  AskResponse,
} from '../types';
import {
  askQuestion,
  GROUNDED_DEMO_QUESTIONS,
} from '../services/api';
import { ContextualEvidenceMargin } from './ContextualEvidenceMargin';
import { DecisionDrawer } from './DecisionDrawer';
import {
  Send,
  Search,
  ShieldCheck,
  AlertTriangle,
  CheckCircle2,
  Quote,
  Loader2,
  Copy,
  CheckCheck,
  ChevronDown,
  ChevronUp,
  GitBranch,
  HelpCircle,
  XCircle,
  ArrowRight,
  Terminal,
} from 'lucide-react';

interface IntelligenceWorkspaceProps {
  selectedRepo: Repository | null;
  onQuestionAnswered: (question: string, response: AskResponse) => void;
  initialQuestion?: string;
}

export const IntelligenceWorkspace: React.FC<IntelligenceWorkspaceProps> = ({
  selectedRepo,
  onQuestionAnswered,
  initialQuestion,
}) => {
  const [question, setQuestion] = useState(initialQuestion || '');
  const [entityId, setEntityId] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [response, setResponse] = useState<AskResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedDecisionId, setSelectedDecisionId] = useState<string | null>(null);
  const [selectedCitationId, setSelectedCitationId] = useState<string | null>(null);
  const [showConfidenceSignals, setShowConfidenceSignals] = useState(false);
  const [copiedAnswer, setCopiedAnswer] = useState(false);

  const answerScrollRef = useRef<HTMLDivElement>(null);
  const repoId = selectedRepo?.id || 'acme-netclient';

  const isDemoRepo = repoId === 'acme-netclient' || (selectedRepo?.fixture ?? false);
  const groundedQuestions = GROUNDED_DEMO_QUESTIONS[repoId] || (isDemoRepo ? GROUNDED_DEMO_QUESTIONS['acme-netclient'] || [] : []);

  useEffect(() => {
    if (initialQuestion && initialQuestion.trim()) {
      setQuestion(initialQuestion);
      handleAsk(initialQuestion);
    }
  }, [initialQuestion]);

  useEffect(() => {
    if (response || error) {
      answerScrollRef.current?.scrollTo({ top: 0, behavior: 'smooth' });
    }
  }, [response, error]);

  const handleAsk = async (qText?: string, entId?: string) => {
    const qToAsk = (qText ?? question).trim();
    if (!qToAsk || qToAsk.length < 3) return;

    setIsLoading(true);
    setError(null);
    setSelectedCitationId(null);

    try {
      const res = await askQuestion(repoId, {
        question: qToAsk,
        entity_id: (entId !== undefined ? entId : entityId).trim() || undefined,
      });
      setResponse(res);
      setQuestion(qToAsk);
      onQuestionAnswered(qToAsk, res);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to query the decision archeology engine';
      setError(message);
      setResponse(null);
    } finally {
      setIsLoading(false);
    }
  };

  const handleCopyAnswer = () => {
    if (!response?.answer) return;
    navigator.clipboard.writeText(response.answer);
    setCopiedAnswer(true);
    setTimeout(() => setCopiedAnswer(false), 2000);
  };

  const handleSelectCitation = (citId: string | null) => {
    setSelectedCitationId(citId);
    if (citId) {
      const elem = document.getElementById(`receipt-${citId}`);
      if (elem) {
        elem.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }
    }
  };

  const activeCitations = response?.citations || [];
  const activeEvidenceGaps = response?.evidence_gaps || [];
  const activeWhoToAsk = response?.who_to_ask || [];

  const renderAnswerWithCitations = (answerText: string) => {
    if (!activeCitations || activeCitations.length === 0) {
      return <p className="prose-answer text-[#292b25]">{answerText}</p>;
    }

    return (
      <div className="text-[#292b25] leading-relaxed space-y-3">
        <p className="prose-answer">{answerText}</p>
        <div className="pt-2 flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] font-mono text-[#77776e] uppercase tracking-wider mr-1">
            Citations:
          </span>
          {activeCitations.map((c, index) => {
            const isSelected = selectedCitationId === c.id;
            return (
              <button
                key={c.id}
                onClick={() => handleSelectCitation(isSelected ? null : c.id)}
                className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-mono font-medium transition-colors cursor-pointer border ${
                  isSelected
                    ? 'bg-[#54734f] text-white border-[#718d5e]'
                    : 'bg-[#efede5] text-[#617c50] border-[#d7d2c6] hover:bg-[#d7d2c6]'
                }`}
                title={`View receipt: ${c.quote.slice(0, 50)}...`}
              >
                <Quote className="w-3 h-3" />
                <span>[{index + 1}: {c.id}]</span>
                {c.author && <span className="text-[10px] opacity-75">@{c.author}</span>}
              </button>
            );
          })}
        </div>
      </div>
    );
  };

  const showEvidencePanel = Boolean(response) || activeCitations.length > 0 || activeEvidenceGaps.length > 0;

  return (
    <div className="flex flex-col h-[calc(100vh-4rem)] w-full bg-[#f5f3ed]">
      {/* Top context bar */}
      <div className="shrink-0 flex flex-wrap items-center justify-between gap-3 px-4 sm:px-6 py-2.5 border-b border-[#d7d2c6] bg-[#fffdf8]">
        <div className="flex items-center gap-2">
          <span className="text-xs font-mono text-[#77776e]">
            Investigation Target:
          </span>
          <span className="font-mono text-xs font-semibold text-[#292b25] bg-[#efede5] px-2 py-0.5 rounded border border-[#d7d2c6] flex items-center gap-1.5">
            <GitBranch className="w-3.5 h-3.5 text-[#617c50]" />
            {selectedRepo?.name || repoId}
          </span>
          {isDemoRepo && (
            <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-amber-500/10 text-amber-400 border border-amber-500/30">
              fixture
            </span>
          )}
        </div>
      </div>

      {/* Answer + evidence */}
      <div
        ref={answerScrollRef}
        className="flex-1 min-h-0 overflow-y-auto flex flex-col lg:flex-row"
      >
        <main className="flex-1 min-w-0 p-4 sm:p-6 space-y-4">
          {isLoading && (
            <div className="p-8 rounded-lg bg-[#fffdf8] border border-[#d7d2c6] text-center space-y-3">
              <div className="w-10 h-10 rounded-full bg-[#efede5] border border-[#d7d2c6] flex items-center justify-center mx-auto text-[#617c50]">
                <Loader2 className="w-5 h-5 animate-spin" />
              </div>
              <div>
                <h3 className="text-xs font-mono font-semibold text-[#292b25]">
                  Querying Decision Graph & Verifying Quotes...
                </h3>
                <p className="text-[11px] font-mono text-[#77776e] mt-1">
                  Resolving entities, validating verbatim substring citations, and scoring provenance.
                </p>
              </div>
            </div>
          )}

          {error && (
            <div className="p-4 rounded-lg bg-[#fffdf8] border border-[#da3633]/50 text-[#f85149] space-y-1.5">
              <div className="flex items-center gap-2 font-medium text-xs">
                <AlertTriangle className="w-4 h-4 text-[#f85149]" />
                <span>Backend Error</span>
              </div>
              <p className="text-xs font-mono text-[#51534b]">{error}</p>
            </div>
          )}

          {!isLoading && !error && !response && (
            <div className="p-8 rounded-lg bg-[#fffdf8] border border-[#d7d2c6] text-center space-y-3">
              <div className="w-10 h-10 rounded-lg bg-[#efede5] text-[#617c50] border border-[#d7d2c6] flex items-center justify-center mx-auto">
                <Terminal className="w-5 h-5" />
              </div>
              <div className="max-w-md mx-auto space-y-1">
                <h3 className="text-sm font-semibold text-[#292b25]">
                  Decision Investigation Console
                </h3>
                <p className="text-xs text-[#77776e] leading-relaxed">
                  Enter a question below to reconstruct historical engineering intent from Git commits, PRs, and review discussions.
                </p>
              </div>
            </div>
          )}

          {!isLoading && response && (
            <div className="space-y-4">
              {/* Full Verified Answer */}
              {response.outcome === 'full' && (
                <div className="rounded-lg bg-[#fffdf8] border border-[#2ea043]/40 p-5 space-y-4">
                  <div className="flex flex-wrap items-center justify-between gap-2.5 border-b border-[#d7d2c6] pb-3">
                    <div className="flex items-center gap-2">
                      <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-mono font-semibold bg-[#2ea043]/15 text-[#3fb950] border border-[#2ea043]/40">
                        <CheckCircle2 className="w-3.5 h-3.5 text-[#3fb950]" />
                        Full Verified Answer
                      </span>
                      {response.confidence && (
                        <span className="px-2 py-0.5 rounded text-xs font-mono font-medium bg-[#efede5] text-[#617c50] border border-[#d7d2c6]">
                          {Math.round(response.confidence.score * 100)}% {response.confidence.label} Confidence
                        </span>
                      )}
                    </div>
                    <button
                      onClick={handleCopyAnswer}
                      className="px-2 py-1 rounded bg-[#efede5] hover:bg-[#d7d2c6] border border-[#d7d2c6] text-[#51534b] hover:text-white transition-colors flex items-center gap-1 text-xs font-mono cursor-pointer"
                      title="Copy answer text"
                    >
                      {copiedAnswer ? <CheckCheck className="w-3.5 h-3.5 text-[#3fb950]" /> : <Copy className="w-3.5 h-3.5" />}
                      <span>{copiedAnswer ? 'Copied' : 'Copy'}</span>
                    </button>
                  </div>

                  {response.entity && (
                    <div className="inline-flex items-center gap-2 px-2.5 py-1 rounded bg-[#f5f3ed] border border-[#d7d2c6] text-xs font-mono">
                      <span className="text-[#617c50] font-medium">{response.entity.type}:</span>
                      <span className="text-[#292b25] font-semibold">{response.entity.label}</span>
                      {response.entity.path && (
                        <span className="text-[#77776e]">({response.entity.path})</span>
                      )}
                      <span className="text-[#929086]">
                        • {response.entity.decision_count} governing decisions
                      </span>
                    </div>
                  )}

                  {response.answer && renderAnswerWithCitations(response.answer)}
                </div>
              )}

              {/* Partial Answer */}
              {response.outcome === 'partial' && (
                <div className="rounded-lg bg-[#fffdf8] border border-[#d29922]/40 p-5 space-y-4">
                  <div className="flex flex-wrap items-center justify-between gap-2.5 border-b border-[#d7d2c6] pb-3">
                    <div className="flex items-center gap-2">
                      <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-mono font-semibold bg-[#d29922]/15 text-[#e3b341] border border-[#d29922]/40">
                        <HelpCircle className="w-3.5 h-3.5 text-[#e3b341]" />
                        Partial Answer
                      </span>
                      {response.reason_code && (
                        <span className="px-2 py-0.5 rounded text-xs font-mono bg-[#efede5] text-[#e3b341] border border-[#d7d2c6]">
                          Reason: {response.reason_code}
                        </span>
                      )}
                      {response.confidence && (
                        <span className="px-2 py-0.5 rounded text-xs font-mono text-[#77776e] bg-[#efede5] border border-[#d7d2c6]">
                          {Math.round(response.confidence.score * 100)}% {response.confidence.label}
                        </span>
                      )}
                    </div>
                    <button
                      onClick={handleCopyAnswer}
                      className="px-2 py-1 rounded bg-[#efede5] hover:bg-[#d7d2c6] border border-[#d7d2c6] text-[#51534b] hover:text-white transition-colors flex items-center gap-1 text-xs font-mono cursor-pointer"
                    >
                      {copiedAnswer ? <CheckCheck className="w-3.5 h-3.5 text-[#3fb950]" /> : <Copy className="w-3.5 h-3.5" />}
                      <span>{copiedAnswer ? 'Copied' : 'Copy'}</span>
                    </button>
                  </div>

                  {response.answer && renderAnswerWithCitations(response.answer)}

                  <div className="p-3 rounded bg-[#f5f3ed] border border-[#d29922]/30 space-y-1">
                    <span className="text-xs font-mono font-medium text-[#e3b341] flex items-center gap-1.5 uppercase">
                      <AlertTriangle className="w-3.5 h-3.5 text-[#e3b341]" />
                      Missing Verbatim Rationale
                    </span>
                    <p className="text-xs font-mono text-[#77776e] leading-relaxed">
                      Code modifications were discovered, but no character-verified quote survived verification. See evidence gaps in the right margin.
                    </p>
                  </div>
                </div>
              )}

              {/* Refusal (Honest Negative) */}
              {response.outcome === 'refusal' && response.reason_code !== 'ambiguous_entity' && (
                <div className="rounded-lg bg-[#fffdf8] border border-[#d7d2c6] p-5 space-y-4">
                  <div className="flex flex-wrap items-center justify-between gap-2.5 border-b border-[#d7d2c6] pb-3">
                    <div className="flex items-center gap-2">
                      <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-mono font-medium bg-[#efede5] text-[#77776e] border border-[#d7d2c6]">
                        <XCircle className="w-3.5 h-3.5 text-[#77776e]" />
                        Principled Refusal
                      </span>
                      {response.reason_code && (
                        <span className="px-2 py-0.5 rounded text-xs font-mono bg-[#efede5] text-[#f85149] border border-[#d7d2c6]">
                          Code: {response.reason_code}
                        </span>
                      )}
                    </div>
                  </div>

                  {response.answer && (
                    <p className="text-[#51534b] text-sm leading-relaxed font-sans">
                      {response.answer}
                    </p>
                  )}

                  <div className="p-3 rounded bg-[#f5f3ed] border border-[#d7d2c6] text-xs font-mono text-[#77776e] space-y-0.5">
                    <span className="text-[#292b25] font-medium block">
                      Refusal Guarantee:
                    </span>
                    <span>
                      Refusal guarantees that CodeWhy never invents speculative reasons or fabricates historical records.
                    </span>
                  </div>
                </div>
              )}

              {/* Ambiguous Entity Disambiguation */}
              {response.outcome === 'refusal' && response.reason_code === 'ambiguous_entity' && (
                <div className="rounded-lg bg-[#fffdf8] border border-[#718d5e]/40 p-5 space-y-4">
                  <div className="flex items-center gap-2 border-b border-[#d7d2c6] pb-3">
                    <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-mono font-medium bg-[#54734f]/15 text-[#617c50] border border-[#718d5e]/40">
                      <AlertTriangle className="w-3.5 h-3.5 text-[#617c50]" />
                      Entity Ambiguity — Select Candidate
                    </span>
                  </div>

                  <div className="space-y-2.5">
                    <p className="text-[#77776e] text-xs font-mono">
                      Multiple matching code entities were found in the knowledge graph:
                    </p>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 pt-1">
                      {response.candidates.map((cand) => (
                        <button
                          key={cand.id}
                          onClick={() => {
                            setEntityId(cand.id);
                            handleAsk(`Why is ${cand.label} configured this way?`, cand.id);
                          }}
                          className="p-3 rounded bg-[#f5f3ed] border border-[#d7d2c6] hover:border-[#718d5e] text-left transition-colors group cursor-pointer"
                        >
                          <div className="flex items-center justify-between text-xs font-mono text-[#617c50] mb-1">
                            <span>{cand.type}</span>
                            <ArrowRight className="w-3.5 h-3.5 group-hover:translate-x-0.5 transition-transform" />
                          </div>
                          <div className="font-mono text-sm font-semibold text-[#292b25]">
                            {cand.label}
                          </div>
                          <div className="text-[11px] font-mono text-[#929086] mt-0.5">
                            {cand.id}
                          </div>
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              {/* Confidence Signals Inspector */}
              {response.confidence && (
                <div className="rounded-lg border border-[#d7d2c6] bg-[#fffdf8] p-3.5 space-y-2.5">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <ShieldCheck className="w-4 h-4 text-[#617c50]" />
                      <span className="text-xs font-mono font-semibold uppercase tracking-wider text-[#292b25]">
                        Confidence Signals:
                      </span>
                      <span className="font-mono text-xs font-medium px-2 py-0.2 rounded bg-[#efede5] text-[#617c50] border border-[#d7d2c6]">
                        {Math.round(response.confidence.score * 100)}% ({response.confidence.label})
                      </span>
                    </div>
                    <button
                      onClick={() => setShowConfidenceSignals((s) => !s)}
                      className="flex items-center gap-1 text-xs font-mono text-[#77776e] hover:text-[#292b25] transition-colors cursor-pointer"
                    >
                      <span>{showConfidenceSignals ? 'Hide signals' : 'Inspect signals'}</span>
                      {showConfidenceSignals ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                    </button>
                  </div>

                  {showConfidenceSignals && response.confidence.signals && (
                    <div className="pt-2.5 border-t border-[#d7d2c6] grid grid-cols-2 sm:grid-cols-3 gap-2.5 text-xs font-mono">
                      {Object.entries(response.confidence.signals).map(([key, val]) => (
                        <div key={key} className="p-2 rounded bg-[#f5f3ed] border border-[#d7d2c6] space-y-1">
                          <span className="text-[10px] text-[#77776e] uppercase block truncate">
                            {key.replace(/_/g, ' ')}
                          </span>
                          <div className="flex items-center justify-between">
                            <span className="text-xs font-semibold text-[#292b25]">
                              {typeof val === 'number' ? (val <= 1.0 ? `${Math.round(val * 100)}%` : val) : String(val)}
                            </span>
                            <div className="w-12 h-1 rounded bg-[#efede5] overflow-hidden">
                              <div
                                className="h-full bg-[#54734f] rounded"
                                style={{ width: `${Math.min(Number(val) * 100, 100)}%` }}
                              />
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </main>

        {/* Evidence receipts margin */}
        {showEvidencePanel && (
          <aside className="w-full lg:w-96 shrink-0 border-t lg:border-t-0 lg:border-l border-[#d7d2c6] lg:max-h-full lg:overflow-y-auto">
            <ContextualEvidenceMargin
              citations={activeCitations}
              evidenceGaps={activeEvidenceGaps}
              whoToAsk={activeWhoToAsk}
              selectedCitationId={selectedCitationId}
              onSelectCitation={(id) => setSelectedCitationId(id)}
              onOpenDecision={(id) => setSelectedDecisionId(id)}
            />
          </aside>
        )}
      </div>

      {/* Ask Input Bar */}
      <div className="shrink-0 border-t border-[#d7d2c6] bg-[#fffdf8] px-4 sm:px-6 py-3 z-20">
        <div className="max-w-4xl mx-auto space-y-2">
          <div className="relative">
            <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-[#77776e] pointer-events-none" />
            <input
              type="text"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !isLoading) {
                  handleAsk();
                }
              }}
              placeholder="Ask why code is like this (e.g. Why was MAX_RETRIES changed?)"
              className="w-full pl-10 pr-28 py-2.5 bg-[#f5f3ed] border border-[#d7d2c6] rounded-md text-[#292b25] placeholder:text-[#929086] font-sans text-xs sm:text-sm focus:outline-none focus:border-[#718d5e] transition-colors"
            />
            <button
              onClick={() => handleAsk()}
              disabled={isLoading || question.trim().length < 3}
              className="absolute right-1.5 top-1/2 -translate-y-1/2 px-3 py-1.5 rounded bg-[#54734f] hover:bg-[#718d5e] text-white font-medium font-sans text-xs flex items-center gap-1.5 disabled:opacity-40 disabled:cursor-not-allowed transition-colors cursor-pointer"
            >
              {isLoading ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  <span>Querying...</span>
                </>
              ) : (
                <>
                  <span>Investigate</span>
                  <Send className="w-3 h-3" />
                </>
              )}
            </button>
          </div>

          {groundedQuestions.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[10px] font-mono text-[#77776e] uppercase tracking-wider mr-1">
                Suggested:
              </span>
              {groundedQuestions.map((sq, idx) => (
                <button
                  key={idx}
                  onClick={() => {
                    setQuestion(sq.question);
                    handleAsk(sq.question, sq.entityId);
                  }}
                  disabled={isLoading}
                  className="px-2 py-0.5 rounded bg-[#efede5] hover:bg-[#d7d2c6] text-[#51534b] hover:text-[#292b25] border border-[#d7d2c6] text-[11px] font-mono transition-colors flex items-center gap-1.5 cursor-pointer"
                >
                  <span>{sq.label}</span>
                  <span className="text-[9px] px-1 py-0.2 rounded bg-[#fffdf8] text-[#77776e] border border-[#d7d2c6]">
                    {sq.tag}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      <DecisionDrawer
        decisionId={selectedDecisionId}
        onClose={() => setSelectedDecisionId(null)}
        onSelectDecision={(id) => setSelectedDecisionId(id)}
        onSelectCitation={(citId) => setSelectedCitationId(citId)}
      />
    </div>
  );
};
