import { useEffect, useRef, useState } from 'react';
import type { DecisionListItem, Entity, Repository } from '../types';
import {
  fetchLineBlame,
  fetchRepositoryCypherSummary,
  fetchRepositoryDecisionHistory,
  runFeatureImpactAdvisor,
  runPreflightCheck,
  searchRepositoryEntities,
  type BlameLineItem,
  type FeatureImpactAdvisorResponse,
  type LineBlameResponse,
  type PreflightResponse,
  type RepositoryCypherSummaryResponse,
} from '../services/api';
import {
  AlertTriangle,
  Check,
  Copy,
  ExternalLink,
  FileCode2,
  Loader2,
  Search,
  ShieldAlert,
} from 'lucide-react';

interface FileDecisionBriefViewProps {
  selectedRepo: Repository | null;
}

const EMPTY_DECISIONS: DecisionListItem[] = [];

function byDateAscending(a: DecisionListItem, b: DecisionListItem): number {
  if (!a.date || !b.date) {
    return a.date ? -1 : b.date ? 1 : a.id.localeCompare(b.id);
  }
  return Date.parse(a.date) - Date.parse(b.date) || a.id.localeCompare(b.id);
}

function byDateDescending(a: DecisionListItem, b: DecisionListItem): number {
  if (!a.date || !b.date) {
    return a.date ? -1 : b.date ? 1 : a.id.localeCompare(b.id);
  }
  return Date.parse(b.date) - Date.parse(a.date) || a.id.localeCompare(b.id);
}

function isExplicitRevert(decision: DecisionListItem): boolean {
  return /revert|rollback|roll back|rolled back|undo/i.test(
    `${decision.rule ?? ''} ${decision.summary}`,
  );
}

function deriveReadingOrder(decisions: DecisionListItem[]): DecisionListItem[] {
  const byId = new Map(decisions.map((decision) => [decision.id, decision]));
  const remaining = new Set(byId.keys());
  const ordered: DecisionListItem[] = [];

  while (remaining.size > 0) {
    const ready = [...remaining]
      .map((id) => byId.get(id))
      .filter((decision): decision is DecisionListItem =>
        Boolean(
          decision &&
            !decision.supersedes.some((priorId) => remaining.has(priorId)),
        ),
      )
      .sort(byDateAscending);
    const next = ready[0] ?? [...remaining]
      .map((id) => byId.get(id))
      .filter((decision): decision is DecisionListItem => Boolean(decision))
      .sort(byDateAscending)[0];

    if (!next) break;
    ordered.push(next);
    remaining.delete(next.id);
  }

  return ordered;
}

function DecisionItem({
  decision,
  note,
}: {
  decision: DecisionListItem;
  note?: string;
}) {
  return (
    <article className="rounded-xl border border-[#CAC4CE]/20 bg-[#242038] p-4 shadow-sm hover:border-[#9067C6]/65 transition-all">
      <div className="flex flex-wrap items-start justify-between gap-2.5">
        <div className="min-w-0 flex-1">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <span
              className={`rounded border px-2 py-0.5 text-[10px] font-mono font-medium ${
                decision.state === 'ACTIVE'
                  ? 'border-[#3fb950]/35 bg-[#3fb950]/15 text-[#3fb950] status-badge-active'
                  : decision.state === 'REJECTED'
                    ? 'border-[#f85149]/35 bg-[#f85149]/15 text-[#f85149] status-badge-rejected'
                    : decision.state === 'SUPERSEDED'
                      ? 'border-[#CAC4CE]/35 bg-[#CAC4CE]/15 text-[#CAC4CE] status-badge-superseded'
                      : 'border-[#e3b341]/35 bg-[#e3b341]/15 text-[#e3b341] status-badge-unresolved'
              }`}
            >
              {decision.state}
            </span>
            <span className="text-[11px] font-mono text-[#CAC4CE]">{decision.id}</span>
            <span className="text-[11px] font-mono text-[#8D86C9]">
              {decision.date ? new Date(decision.date).toLocaleDateString() : 'date unknown'}
            </span>
          </div>
          <p className="text-sm leading-relaxed text-[#F7ECE1]">{decision.summary}</p>
          {note && <p className="mt-1.5 text-xs font-mono text-[#CAC4CE]">{note}</p>}
          {decision.supersedes.length > 0 && (
            <p className="mt-1.5 text-[11px] font-mono text-[#8D86C9]">
              Supersedes: {decision.supersedes.join(', ')}
            </p>
          )}
        </div>
        {decision.source_url && (
          <a
            href={decision.source_url}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={`Open source for ${decision.id}`}
            className="shrink-0 rounded p-1 text-[#C5B0E6] hover:bg-[#322D4D] hover:text-[#F7ECE1] transition-colors"
          >
            <ExternalLink className="h-3.5 w-3.5" />
          </a>
        )}
      </div>
    </article>
  );
}

function DecisionSection({
  title,
  description,
  decisions,
  emptyMessage,
  renderNote,
}: {
  title: string;
  description: string;
  decisions: DecisionListItem[];
  emptyMessage: string;
  renderNote?: (decision: DecisionListItem) => string | undefined;
}) {
  return (
    <section className="space-y-2.5">
      <div>
        <h2 className="text-sm font-semibold text-[#F7ECE1]">{title}</h2>
        <p className="mt-0.5 text-xs text-[#CAC4CE]">{description}</p>
      </div>
      {decisions.length > 0 ? (
        <div className="space-y-2">
          {decisions.map((decision) => (
            <DecisionItem
              key={decision.id}
              decision={decision}
              note={renderNote?.(decision)}
            />
          ))}
        </div>
      ) : (
        <p className="rounded-xl border border-dashed border-[#CAC4CE]/25 bg-[#242038]/60 px-3.5 py-3 text-xs text-[#CAC4CE]">
          {emptyMessage}
        </p>
      )}
    </section>
  );
}

export function FileDecisionBriefView({ selectedRepo }: FileDecisionBriefViewProps) {
  const repoId = selectedRepo?.id ?? '';
  const [query, setQuery] = useState('');
  const [entities, setEntities] = useState<Entity[]>([]);
  const [searchedQuery, setSearchedQuery] = useState('');
  const [selectedEntity, setSelectedEntity] = useState<Entity | null>(null);
  const [searchingQuery, setSearchingQuery] = useState('');
  const [searchError, setSearchError] = useState<string | null>(null);
  const [history, setHistory] = useState<DecisionListItem[] | null>(null);
  const [historyCount, setHistoryCount] = useState(0);
  const [historyReload, setHistoryReload] = useState(0);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [preflightData, setPreflightData] = useState<PreflightResponse | null>(null);
  const [diffText, setDiffText] = useState('');
  const [isRunningPreflight, setIsRunningPreflight] = useState(false);
  const [blameData, setBlameData] = useState<LineBlameResponse | null>(null);
  const [selectedBlameLine, setSelectedBlameLine] = useState<BlameLineItem | null>(null);
  const [isLoadingBlame, setIsLoadingBlame] = useState(false);
  const [repoSummary, setRepoSummary] = useState<RepositoryCypherSummaryResponse | null>(null);
  const [impactMode, setImpactMode] = useState<'add' | 'remove'>('add');
  const [impactFeature, setImpactFeature] = useState('');
  const [impactResult, setImpactResult] = useState<FeatureImpactAdvisorResponse | null>(null);
  const [isRunningImpact, setIsRunningImpact] = useState(false);
  const [showCypherQuery, setShowCypherQuery] = useState(false);
  // Monotonic token so a slow, older search can never overwrite a newer one.
  const searchSeqRef = useRef(0);

  useEffect(() => {
    setPreflightData(null);
    setBlameData(null);
    setSelectedBlameLine(null);
    setRepoSummary(null);
    setImpactResult(null);
    if (!repoId) return;
    let cancelled = false;
    runPreflightCheck(repoId)
      .then((res) => {
        if (!cancelled) setPreflightData(res);
      })
      .catch(() => {
        // ignore if endpoint unavailable in mock unit test
      });
    fetchRepositoryCypherSummary(repoId)
      .then((res) => {
        if (!cancelled) setRepoSummary(res);
      })
      .catch(() => {
        // ignore if endpoint unavailable in mock unit test
      });
    return () => {
      cancelled = true;
    };
  }, [repoId]);

  const handleRunImpactAdvisor = async (customMode?: 'add' | 'remove', customFeature?: string) => {
    if (!repoId || isRunningImpact) return;
    const m = customMode ?? impactMode;
    const feat = (customFeature ?? impactFeature).trim()
      || preflightData?.hotspots[0]?.file
      || 'retry';
    setImpactMode(m);
    setImpactFeature(feat);
    setIsRunningImpact(true);
    try {
      const res = await runFeatureImpactAdvisor(repoId, m, feat);
      setImpactResult(res);
    } catch {
      // ignore
    } finally {
      setIsRunningImpact(false);
    }
  };

  useEffect(() => {
    const targetPath = selectedEntity?.path || selectedEntity?.label || '';
    if (!repoId || !targetPath) {
      setBlameData(null);
      setSelectedBlameLine(null);
      return;
    }
    let cancelled = false;
    setIsLoadingBlame(true);
    fetchLineBlame(repoId, targetPath)
      .then((res) => {
        if (!cancelled) {
          setBlameData(res);
          setSelectedBlameLine(res.selected_line ?? res.lines[0] ?? null);
        }
      })
      .catch(() => {
        if (!cancelled) setBlameData(null);
      })
      .finally(() => {
        if (!cancelled) setIsLoadingBlame(false);
      });
    return () => {
      cancelled = true;
    };
  }, [repoId, selectedEntity?.id, selectedEntity?.path, selectedEntity?.label]);

  const handleRunDiffPreflight = async (customDiff?: string) => {
    if (!repoId) return;
    const d = customDiff ?? diffText;
    setIsRunningPreflight(true);
    try {
      const targetFiles = selectedEntity?.path ? [selectedEntity.path] : [];
      const res = await runPreflightCheck(repoId, d, targetFiles);
      setPreflightData(res);
    } catch {
      // ignore
    } finally {
      setIsRunningPreflight(false);
    }
  };

  useEffect(() => {
    const searchTerm = query.trim();
    const seq = searchSeqRef.current + 1;
    searchSeqRef.current = seq;

    if (!repoId || !searchTerm) {
      setEntities([]);
      setSearchedQuery('');
      setSearchingQuery('');
      setSearchError(null);
      return;
    }

    let cancelled = false;
    const timer = window.setTimeout(async () => {
      setSearchingQuery(searchTerm);
      try {
        const response = await searchRepositoryEntities(repoId, searchTerm);
        if (!cancelled && seq === searchSeqRef.current) {
          setEntities(response.entities.filter((entity) => entity.type === 'File'));
          setSearchError(null);
          setSearchedQuery(searchTerm);
        }
      } catch (error) {
        if (!cancelled && seq === searchSeqRef.current) {
          setEntities([]);
          setSearchError(error instanceof Error ? error.message : 'File search failed');
          setSearchedQuery(searchTerm);
        }
      } finally {
        if (!cancelled && seq === searchSeqRef.current) {
          setSearchingQuery((current) => current === searchTerm ? '' : current);
        }
      }
    }, 250);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [query, repoId]);

  useEffect(() => {
    if (!repoId || !selectedEntity?.id) return;

    let cancelled = false;

    fetchRepositoryDecisionHistory(repoId)
      .then((response) => {
        if (!cancelled) {
          setHistory(response.items);
          setHistoryCount(response.total);
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setHistoryError(
            error instanceof Error ? error.message : 'Failed to load decision history',
          );
        }
      })
      .finally(() => {
        if (!cancelled) setIsLoadingHistory(false);
      });

    return () => {
      cancelled = true;
    };
  }, [repoId, selectedEntity?.id, historyReload]);

  const allDecisions = history ?? EMPTY_DECISIONS;
  const linkedDecisions = selectedEntity
    ? allDecisions.filter((decision) => decision.entities.includes(selectedEntity.id))
    : [];
  const governingDecisions = linkedDecisions
    .filter((decision) => decision.state === 'ACTIVE')
    .sort(byDateDescending);
  const rejectedDecisions = linkedDecisions
    .filter((decision) => decision.state === 'REJECTED')
    .sort(byDateDescending);
  const revertedDecisions = linkedDecisions
    .filter((decision) => isExplicitRevert(decision))
    .sort(byDateDescending);
  const recentActiveDecisions = [...allDecisions]
    .filter((decision) => decision.state === 'ACTIVE')
    .sort(byDateDescending)
    .slice(0, 4);
  const readingOrder = deriveReadingOrder(linkedDecisions);
  const linkedDecisionIds = new Set(linkedDecisions.map((decision) => decision.id));
  const [copiedGuardrails, setCopiedGuardrails] = useState(false);

  const modificationRisk: 'HIGH' | 'MEDIUM' | 'LOW' =
    revertedDecisions.length > 0 || governingDecisions.length >= 3
      ? 'HIGH'
      : governingDecisions.length >= 1
        ? 'MEDIUM'
        : 'LOW';

  const handleCopyGuardrails = async () => {
    if (!selectedEntity) return;
    const lines = [
      `# CodeWhy Architectural Guardrails: ${selectedEntity.path}`,
      `Repository: ${selectedRepo?.full_name ?? selectedRepo?.name ?? repoId}`,
      `Modification Risk: ${modificationRisk} (${governingDecisions.length} active, ${revertedDecisions.length} reverted)`,
      '',
      '## Active Invariants (Do Not Violate)',
      ...(governingDecisions.length > 0
        ? governingDecisions.map((d) => `- [${d.id}] ${d.summary}${d.source_url ? ` (${d.source_url})` : ''}`)
        : ['- None recorded yet.']),
      '',
      '## Historical Reverts / Traps',
      ...(revertedDecisions.length > 0
        ? revertedDecisions.map((d) => `- [${d.id}] ${d.summary}${d.source_url ? ` (${d.source_url})` : ''}`)
        : ['- None recorded.']),
    ];
    try {
      await navigator.clipboard?.writeText(lines.join('\n'));
      setCopiedGuardrails(true);
      window.setTimeout(() => setCopiedGuardrails(false), 2000);
    } catch {
      // ignore clipboard denial in headless browsers
    }
  };

  return (
    <div className="h-[calc(100vh-4rem)] w-full overflow-y-auto bg-[#191628] text-[#F7ECE1]">
      <header className="sticky top-0 z-10 flex flex-wrap items-center justify-between gap-3 border-b border-[#CAC4CE]/20 bg-[#242038] px-4 py-3 sm:px-6">
        <div className="flex items-center gap-2.5">
          <FileCode2 className="h-4 w-4 text-[#9067C6]" />
          <div>
            <h1 className="text-sm font-semibold text-[#F7ECE1]">Before You Change This File</h1>
            <p className="text-[11px] font-mono text-[#CAC4CE]">{selectedRepo?.name ?? repoId}</p>
          </div>
        </div>
        {selectedEntity && history && (
          <div className="flex flex-wrap items-center gap-2.5">
            <span
              className={`inline-flex items-center gap-1 rounded border px-2 py-0.5 text-[11px] font-mono font-semibold ${
                modificationRisk === 'HIGH'
                  ? 'border-[#da3633]/40 bg-[#da3633]/15 text-[#f85149]'
                  : modificationRisk === 'MEDIUM'
                    ? 'border-[#d29922]/40 bg-[#d29922]/15 text-[#e3b341]'
                    : 'border-[#2ea043]/40 bg-[#2ea043]/15 text-[#3fb950]'
              }`}
            >
              <ShieldAlert className="h-3 w-3" />
              Risk: {modificationRisk}
            </span>
            <button
              type="button"
              onClick={handleCopyGuardrails}
              className="inline-flex items-center gap-1.5 rounded border border-[#CAC4CE]/25 bg-[#161324] px-2.5 py-1 text-[11px] font-mono text-[#F7ECE1] hover:border-[#9067C6] transition-colors cursor-pointer"
            >
              {copiedGuardrails ? <Check className="h-3 w-3 text-[#3fb950]" /> : <Copy className="h-3 w-3 text-[#9067C6]" />}
              {copiedGuardrails ? 'Copied Guardrails' : 'Copy AI Guardrails'}
            </button>
            <span className="text-xs font-mono text-[#CAC4CE]">
              Derived from {linkedDecisions.length} decisions
            </span>
          </div>
        )}
      </header>

      <main className="mx-auto max-w-5xl space-y-5 p-4 sm:p-6">
        <section className="space-y-3">
          <div>
            <h2 className="text-sm font-semibold text-[#F7ECE1]">Find a file</h2>
            <p className="mt-1 text-xs text-[#CAC4CE]">
              Search repository files by entity label to inspect their recorded decision history.
            </p>
          </div>
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#9067C6]" />
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search files by name"
              aria-label="Search files by name"
              className="w-full rounded-lg border border-[#CAC4CE]/25 bg-[#161324] py-2.5 pl-9 pr-3 text-sm font-mono text-[#F7ECE1] placeholder:text-[#CAC4CE]/65 focus:border-[#9067C6] focus:outline-none focus:ring-1 focus:ring-[#9067C6]/40 transition-all"
            />
          </div>
          {searchingQuery === query.trim() && query.trim() && (
            <p className="flex items-center gap-2 text-xs text-[#CAC4CE]" role="status">
              <Loader2 className="h-3.5 w-3.5 animate-spin text-[#9067C6]" />
              Searching files…
            </p>
          )}
          {searchedQuery === query.trim() && searchError && (
            <p className="rounded-xl border border-[#f85149]/45 bg-[#242038] p-3 text-xs text-[#f85149]" role="alert">
              {searchError}
            </p>
          )}
          {searchedQuery === query.trim() && query.trim() && !searchError && entities.length === 0 && (
            <p className="text-xs text-[#CAC4CE]">No matching files found.</p>
          )}
          {searchedQuery === query.trim() && entities.length > 0 && (
            <ul className="max-h-56 space-y-1 overflow-y-auto rounded-xl border border-[#CAC4CE]/25 bg-[#242038] p-1.5 shadow-lg">
              {entities.map((entity) => {
                const isSelected = selectedEntity?.id === entity.id;
                return (
                  <li key={entity.id}>
                    <button
                      type="button"
                      onClick={() => {
                        if (selectedEntity?.id === entity.id) return;
                        setSelectedEntity(entity);
                        setHistory(null);
                        setHistoryCount(0);
                        setIsLoadingHistory(true);
                        setHistoryError(null);
                      }}
                      className={`flex w-full items-start gap-2.5 rounded-lg px-3 py-2 text-left transition-colors cursor-pointer ${
                        isSelected
                          ? 'bg-[#322D4D] text-[#F7ECE1] border border-[#9067C6] shadow-sm'
                          : 'text-[#CAC4CE] hover:bg-[#161324] hover:text-[#F7ECE1] border border-transparent'
                      }`}
                    >
                      <FileCode2 className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${isSelected ? 'text-[#9067C6]' : 'text-[#8D86C9]'}`} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-xs font-medium text-[#F7ECE1]">{entity.path || entity.label}</span>
                        <span className="block truncate text-[10px] font-mono text-[#CAC4CE]">{entity.id}</span>
                      </span>
                      <span className="shrink-0 rounded border border-[#CAC4CE]/20 bg-[#161324] px-1.5 py-0.5 text-[10px] font-mono text-[#CAC4CE]">
                        {entity.decision_count ?? 0} linked
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        {selectedEntity && (
          <div className="space-y-5">
            <section className="rounded-xl border border-[#CAC4CE]/20 bg-[#242038] p-4 shadow-sm space-y-1">
              <p className="text-[10px] font-mono uppercase tracking-wider text-[#CAC4CE] font-semibold">Selected file</p>
              <p className="mt-1 break-all text-sm font-medium text-[#F7ECE1] font-mono">
                {selectedEntity.path || selectedEntity.label}
              </p>
              <p className="mt-1 break-all text-[11px] font-mono text-[#8D86C9]">{selectedEntity.id}</p>
            </section>

            {/* F2: Line-Level "Why Blame" Code Viewer */}
            {blameData && blameData.lines.length > 0 && (
              <section className="rounded-xl border border-[#CAC4CE]/20 bg-[#242038] p-4 space-y-3 shadow-sm">
                <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#CAC4CE]/20 pb-2.5">
                  <div>
                    <h3 className="text-xs font-mono font-semibold uppercase tracking-wider text-[#C5B0E6]">
                      Line-Level "Why Blame" Inspector — {blameData.path}
                    </h3>
                    <p className="text-[11px] text-[#CAC4CE]">
                      Click any decision-governed line to inspect its commit → PR → Decision &amp; revert lineage.
                    </p>
                  </div>
                  <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-[#161324] border border-[#CAC4CE]/20 text-[#CAC4CE]">
                    {blameData.governed_decisions_count} governing decision(s)
                  </span>
                </div>
                <div className="grid grid-cols-1 lg:grid-cols-12 gap-3">
                  <div className="lg:col-span-7 max-h-64 overflow-y-auto rounded-lg bg-[#161324] border border-[#CAC4CE]/20 font-mono text-xs divide-y divide-[#242038]">
                    {blameData.lines.map((ln) => {
                      const isSel = selectedBlameLine?.line_number === ln.line_number;
                      const state = ln.decision?.state || '';
                      return (
                        <button
                          key={ln.line_number}
                          type="button"
                          onClick={() => setSelectedBlameLine(ln)}
                          className={`w-full text-left px-3 py-1.5 flex items-center gap-2.5 transition-colors cursor-pointer ${
                            isSel
                              ? 'bg-[#9067C6]/20 text-[#F7ECE1]'
                              : ln.governed
                              ? 'hover:bg-[#322D4D] text-[#CAC4CE]'
                              : 'text-[#8D86C9]/70 hover:bg-[#242038]'
                          }`}
                        >
                          <span className="w-7 shrink-0 text-right text-[10px] text-[#8D86C9]">
                            {ln.line_number}
                          </span>
                          <span
                            className={`w-2 h-2 rounded-full shrink-0 ${
                              !ln.governed
                                ? 'bg-transparent'
                                : state === 'ACTIVE'
                                ? 'bg-[#3fb950]'
                                : 'bg-[#9067C6]'
                            }`}
                          />
                          <span className="w-16 shrink-0 text-[10px] text-[#CAC4CE] truncate">
                            {ln.sha || 'HEAD'}
                          </span>
                          <span className="truncate flex-1">{ln.code || ' '}</span>
                        </button>
                      );
                    })}
                  </div>
                  <div className="lg:col-span-5 rounded-lg bg-[#161324] border border-[#CAC4CE]/20 p-3.5 space-y-2.5 text-xs">
                    {isLoadingBlame ? (
                      <p className="text-[#CAC4CE] font-mono">Loading line blame…</p>
                    ) : selectedBlameLine?.decision ? (
                      <>
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-mono text-[11px] text-[#C5B0E6]">
                            Line {selectedBlameLine.line_number} · @{selectedBlameLine.author}
                          </span>
                          <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-[#242038] border border-[#CAC4CE]/20 text-[#3fb950]">
                            {selectedBlameLine.decision.state}
                          </span>
                        </div>
                        <p className="font-semibold text-[#F7ECE1]">{selectedBlameLine.decision.summary}</p>
                        {selectedBlameLine.decision.rule && (
                          <p className="text-[11px] font-mono text-[#CAC4CE] bg-[#242038] p-2 rounded border border-[#CAC4CE]/20">
                            Rule: {selectedBlameLine.decision.rule}
                          </p>
                        )}
                        {selectedBlameLine.decision.quote && (
                          <blockquote className="text-[11px] italic text-[#CAC4CE] border-l-2 border-[#9067C6] pl-2.5">
                            "{selectedBlameLine.decision.quote}"
                          </blockquote>
                        )}
                        <div className="text-[10px] font-mono text-[#8D86C9] flex flex-wrap gap-2 pt-1">
                          <span>ID: {selectedBlameLine.decision.id}</span>
                          {selectedBlameLine.decision.supersedes && (
                            <span>· Supersedes: {selectedBlameLine.decision.supersedes}</span>
                          )}
                          {selectedBlameLine.decision.superseded_by && (
                            <span className="text-[#f85149]">· Superseded by: {selectedBlameLine.decision.superseded_by}</span>
                          )}
                        </div>
                      </>
                    ) : (
                      <p className="text-[#CAC4CE] font-mono">
                        Select a highlighted line to inspect its governing decision and verbatim PR quote.
                      </p>
                    )}
                  </div>
                </div>
              </section>
            )}

            <div className="flex items-start gap-2.5 rounded-xl border border-[#9067C6]/35 bg-[#242038] p-3.5 text-xs leading-relaxed text-[#CAC4CE] shadow-sm">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-[#9067C6]" />
              <p>
                A file-level view can include unrelated repository decisions. Only a decision whose
                <code className="mx-1 rounded bg-[#161324] border border-[#CAC4CE]/25 px-1.5 py-0.5 font-mono text-[#C5B0E6]">entities</code>
                list explicitly contains this file is treated as supported for it; recent repository
                decisions without that link are labeled as unlinked.
              </p>
            </div>

            {isLoadingHistory && (
              <p className="flex items-center gap-2 py-4 text-xs text-[#CAC4CE]" role="status">
                <Loader2 className="h-4 w-4 animate-spin text-[#9067C6]" />
                Loading repository decision history…
              </p>
            )}
            {historyError && (
              <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[#f85149]/45 bg-[#242038] p-3 text-xs text-[#f85149]" role="alert">
                <p>{historyError}</p>
                <button
                  type="button"
                  onClick={() => {
                    setHistoryError(null);
                    setIsLoadingHistory(true);
                    setHistoryReload((reload) => reload + 1);
                  }}
                  className="rounded-lg border border-[#f85149]/45 px-2.5 py-1 text-xs text-[#f85149] hover:bg-[#f85149]/15 transition-colors cursor-pointer"
                >
                  Retry
                </button>
              </div>
            )}
            {history && (
              <>
                <DecisionSection
                  title="Supported governing decisions"
                  description="Active decisions explicitly linked to this file by the API response."
                  decisions={governingDecisions}
                  emptyMessage="No active decision is explicitly linked to this file."
                />
                <DecisionSection
                  title="Reverted / rollback decisions"
                  description="Linked decisions whose rule or summary explicitly identifies a revert or rollback."
                  decisions={revertedDecisions}
                  emptyMessage="No linked decision explicitly identifies a revert or rollback."
                />
                <DecisionSection
                  title="Rejected decisions"
                  description="Rejected decisions explicitly linked to this file."
                  decisions={rejectedDecisions}
                  emptyMessage="No rejected decision is explicitly linked to this file."
                />
                <DecisionSection
                  title="Recent active decisions"
                  description="The four most recent active decisions in the repository; unlinked items are not file-level evidence."
                  decisions={recentActiveDecisions}
                  emptyMessage="No active decisions are available in repository history."
                  renderNote={(decision) =>
                    linkedDecisionIds.has(decision.id)
                      ? 'Explicitly linked to this file.'
                      : 'Repository decision; no direct link to this file.'
                  }
                />
                <DecisionSection
                  title="Suggested reading order"
                  description="Linked history ordered oldest-first, respecting explicit supersedes relationships where available."
                  decisions={readingOrder}
                  emptyMessage="No decision history is explicitly linked to this file."
                  renderNote={(decision) => {
                    const index = readingOrder.findIndex((item) => item.id === decision.id);
                    return `Read ${index + 1} of ${readingOrder.length}`;
                  }}
                />
                <p className="flex items-center gap-2 border-t border-[#CAC4CE]/20 pt-3 text-[11px] font-mono text-[#CAC4CE]">
                  <Check className="h-3.5 w-3.5 text-[#3fb950]" />
                  Reading order is derived from {linkedDecisions.length} explicitly linked decisions
                  out of {historyCount} repository decisions.
                </p>
              </>
            )}
          </div>
        )}
        {!selectedEntity && !query.trim() && (
          <div className="rounded-xl border border-[#CAC4CE]/20 bg-[#242038] p-8 text-center space-y-2 shadow-sm">
            <Search className="mx-auto h-5 w-5 text-[#9067C6]" />
            <p className="text-xs font-mono text-[#CAC4CE]">Search and select a file to build its brief.</p>
          </div>
        )}

        {/* F6: Modification Risk Badge & Hotspot Map + F7: Constant Timeline + B7: Pre-Flight Diff Check */}
        {preflightData && (
          <div className="space-y-4 pt-2">
            {/* Hotspot Grid */}
            {preflightData.hotspots.length > 0 && (
              <section className="rounded-xl border border-[#292A23] bg-[#12130F] p-4 space-y-3 shadow-sm">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <h3 className="text-xs font-mono font-semibold uppercase tracking-wider text-[#F5F3ED]">
                      Regression Hotspot Map &amp; Modification Risk Badges
                    </h3>
                    <p className="text-[11px] text-[#A5A69D]">
                      Click any tracked file to open its decision brief and line-level Why Blame inspector.
                    </p>
                  </div>
                  <span
                    className={`px-2.5 py-0.5 rounded text-xs font-mono font-semibold border ${
                      preflightData.risk_level === 'HIGH'
                        ? 'bg-[#f85149]/15 text-[#f85149] border-[#f85149]/40'
                        : preflightData.risk_level === 'MEDIUM'
                        ? 'bg-[#B9915E]/15 text-[#B9915E] border-[#B9915E]/40'
                        : 'bg-[#2ea043]/15 text-[#3fb950] border-[#2ea043]/40'
                    }`}
                  >
                    Repo Posture: {preflightData.risk_badge}
                  </span>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2.5">
                  {preflightData.hotspots.map((h) => (
                    <button
                      key={h.file}
                      type="button"
                      onClick={() =>
                        setSelectedEntity({
                          id: `file:${h.file}`,
                          type: 'File',
                          label: h.file,
                          path: h.file,
                          decision_count: h.active_count + h.reverted_or_superseded_count,
                        })
                      }
                      className="text-left p-3 rounded-lg bg-[#080907] hover:bg-[#181914] border border-[#292A23] hover:border-[#B9915E]/50 transition-colors space-y-1.5 cursor-pointer"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-mono text-xs font-semibold text-[#F5F3ED] truncate">{h.file}</span>
                        <span
                          className={`shrink-0 px-1.5 py-0.5 rounded text-[10px] font-mono font-semibold ${
                            h.risk_level === 'HIGH'
                              ? 'bg-[#f85149]/20 text-[#f85149]'
                              : h.risk_level === 'MEDIUM'
                              ? 'bg-[#B9915E]/20 text-[#B9915E]'
                              : 'bg-[#2ea043]/20 text-[#3fb950]'
                          }`}
                        >
                          {h.risk_badge}
                        </span>
                      </div>
                      <p className="text-[11px] text-[#A5A69D] line-clamp-1">{h.top_decision}</p>
                      <p className="text-[10px] font-mono text-[#757F6C]">
                        {h.active_count} active · {h.reverted_or_superseded_count} reverted/superseded
                      </p>
                    </button>
                  ))}
                </div>
              </section>
            )}

            {/* F7: Visual Constant/Config Value Evolution Timeline */}
            {preflightData.constant_timeline.length > 0 && (
              <section className="rounded-xl border border-[#292A23] bg-[#12130F] p-4 space-y-3 shadow-sm">
                <h3 className="text-xs font-mono font-semibold uppercase tracking-wider text-[#F5F3ED]">
                  AST Constant &amp; Config Value Evolution Timeline
                </h3>
                <div className="space-y-2">
                  {preflightData.constant_timeline.map((ct) => (
                    <div
                      key={`${ct.file}:${ct.name}`}
                      className="p-3 rounded-lg bg-[#080907] border border-[#292A23] flex flex-wrap items-center justify-between gap-2 text-xs font-mono"
                    >
                      <div>
                        <span className="text-[#B9915E] font-semibold">{ct.name}</span>
                        <span className="text-[#757F6C] ml-2">({ct.file})</span>
                      </div>
                      <div className="flex flex-wrap items-center gap-1.5">
                        {ct.transitions.map((tr, i) => (
                          <span
                            key={i}
                            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded bg-[#12130F] border border-[#292A23] text-[#F5F3ED]"
                          >
                            <span className="text-[#A5A69D]">{tr.old_value ?? 'init'}</span>
                            <span className="text-[#B9915E]">→</span>
                            <span className="text-[#3fb950] font-semibold">{tr.new_value}</span>
                            <span className="text-[10px] text-[#757F6C]">({tr.source_id})</span>
                          </span>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {/* B7: Pre-Flight Diff Check Analyzer */}
            <section className="rounded-xl border border-[#292A23] bg-[#12130F] p-4 space-y-3 shadow-sm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h3 className="text-xs font-mono font-semibold uppercase tracking-wider text-[#F5F3ED]">
                    Pre-Flight Impact &amp; Diff Analyzer
                  </h3>
                  <p className="text-[11px] text-[#A5A69D]">
                    Paste a unified <code className="font-mono text-[#B9915E]">git diff</code> to check modified files and constants against ACTIVE decisions and past reverts.
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      const sampleFile = preflightData.hotspots[0]?.file || 'src/retry.py';
                      const sample = `diff --git a/${sampleFile} b/${sampleFile}\n--- a/${sampleFile}\n+++ b/${sampleFile}\n@@ -12,3 +12,3 @@\n-ALPN_PROTOCOLS = ['http/1.1']\n+ALPN_PROTOCOLS = ['h2', 'http/1.1']`;
                      setDiffText(sample);
                      handleRunDiffPreflight(sample);
                    }}
                    className="px-2.5 py-1 rounded bg-[#080907] hover:bg-[#181914] border border-[#292A23] text-xs font-mono text-[#A5A69D] hover:text-[#F5F3ED] cursor-pointer"
                  >
                    Load Sample Diff
                  </button>
                  <button
                    type="button"
                    onClick={() => handleRunDiffPreflight()}
                    disabled={isRunningPreflight}
                    className="px-3 py-1 rounded bg-[#B9915E]/20 hover:bg-[#B9915E]/30 border border-[#B9915E]/40 text-xs font-mono font-semibold text-[#B9915E] cursor-pointer"
                  >
                    {isRunningPreflight ? 'Checking…' : 'Run Pre-Flight Check'}
                  </button>
                </div>
              </div>
              <textarea
                value={diffText}
                onChange={(e) => setDiffText(e.target.value)}
                rows={3}
                placeholder="Paste git diff here (e.g. +++ b/src/urllib3/util/ssl_.py)..."
                className="w-full rounded-lg bg-[#080907] border border-[#292A23] p-2.5 font-mono text-xs text-[#F5F3ED] placeholder:text-[#757F6C]"
              />
              {preflightData.warnings.length > 0 && (
                <div className="space-y-1.5">
                  {preflightData.warnings.map((w, idx) => (
                    <div
                      key={idx}
                      className="p-2.5 rounded-lg bg-[#080907] border border-[#B9915E]/40 flex items-start gap-2 text-xs"
                    >
                      <AlertTriangle className="h-4 w-4 text-[#B9915E] shrink-0 mt-0.5" />
                      <div>
                        <span className="font-mono font-semibold text-[#B9915E]">[{w.severity}] </span>
                        <span className="text-[#F5F3ED]">{w.message}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>

            {/* N1: GitHub Repo Architectural Summary via Neo4j Cypher */}
            {repoSummary && (
              <section className="rounded-xl border border-[#292A23] bg-[#12130F] p-4 space-y-3 shadow-sm">
                <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#292A23] pb-2.5">
                  <div>
                    <h3 className="text-xs font-mono font-semibold uppercase tracking-wider text-[#B9915E]">
                      1. Neo4j Cypher Repository Architectural Summary — {repoSummary.full_name}
                    </h3>
                    <p className="text-xs text-[#F5F3ED] mt-1 leading-relaxed">{repoSummary.overview}</p>
                  </div>
                  <button
                    type="button"
                    onClick={() => setShowCypherQuery((prev) => !prev)}
                    className="px-2.5 py-1 rounded bg-[#080907] hover:bg-[#181914] border border-[#292A23] text-[11px] font-mono text-[#A5A69D] hover:text-[#F5F3ED] cursor-pointer"
                  >
                    {showCypherQuery ? 'Hide Cypher Query' : 'Show Neo4j Cypher'}
                  </button>
                </div>
                {showCypherQuery && (
                  <pre className="p-3 rounded-lg bg-[#080907] border border-[#292A23] text-[11px] font-mono text-[#B9915E] overflow-x-auto">
                    {repoSummary.cypher_query}
                  </pre>
                )}
                {repoSummary.top_maintainers.length > 0 && (
                  <div className="flex flex-wrap items-center gap-1.5 text-xs font-mono">
                    <span className="text-[#757F6C]">Top Maintainers (AUTHORED / REVIEWED):</span>
                    {repoSummary.top_maintainers.map((m) => (
                      <span
                        key={m.login}
                        className="px-2 py-0.5 rounded bg-[#080907] border border-[#292A23] text-[#F5F3ED]"
                      >
                        @{m.login}
                      </span>
                    ))}
                  </div>
                )}
              </section>
            )}

            {/* N2 & N3: Neo4j Add-On vs. Feature Removal Impact Advisor */}
            <section className="rounded-xl border border-[#B9915E]/40 bg-[#12130F] p-4 space-y-3.5 shadow-sm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h3 className="text-xs font-mono font-semibold uppercase tracking-wider text-[#B9915E]">
                    2 &amp; 3. Neo4j Feature Add-On &amp; Removal Impact Advisor (Cypher Multi-Hop)
                  </h3>
                  <p className="text-[11px] text-[#A5A69D]">
                    Check if an add-on already exists (when &amp; how it was added + blast radius) or what breaks if you remove/change a feature (all related PRs, required co-changes, what could go wrong &amp; verbatim evidence).
                  </p>
                </div>
                <div className="flex items-center gap-1.5">
                  <button
                    type="button"
                    onClick={() => handleRunImpactAdvisor('add')}
                    className={`px-2.5 py-1 rounded text-xs font-mono font-semibold border cursor-pointer ${
                      impactMode === 'add'
                        ? 'bg-[#2ea043]/20 text-[#3fb950] border-[#2ea043]/50'
                        : 'bg-[#080907] text-[#A5A69D] border-[#292A23]'
                    }`}
                  >
                    + Add Extra Add-On
                  </button>
                  <button
                    type="button"
                    onClick={() => handleRunImpactAdvisor('remove')}
                    className={`px-2.5 py-1 rounded text-xs font-mono font-semibold border cursor-pointer ${
                      impactMode === 'remove'
                        ? 'bg-[#f85149]/20 text-[#f85149] border-[#f85149]/50'
                        : 'bg-[#080907] text-[#A5A69D] border-[#292A23]'
                    }`}
                  >
                    - Remove / Modify Feature
                  </button>
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <input
                  type="text"
                  value={impactFeature}
                  onChange={(e) => setImpactFeature(e.target.value)}
                  placeholder="Enter feature, add-on, constant, or file (e.g. retry, ALPN_PROTOCOLS, timeout)..."
                  className="flex-1 min-w-[220px] rounded-lg bg-[#080907] border border-[#292A23] px-3 py-1.5 font-mono text-xs text-[#F5F3ED] placeholder:text-[#757F6C]"
                />
                <button
                  type="button"
                  onClick={() => handleRunImpactAdvisor()}
                  disabled={isRunningImpact}
                  className="px-3.5 py-1.5 rounded-lg bg-[#B9915E]/20 hover:bg-[#B9915E]/30 border border-[#B9915E]/50 text-xs font-mono font-semibold text-[#B9915E] cursor-pointer"
                >
                  {isRunningImpact ? 'Querying Neo4j…' : 'Analyze in Neo4j'}
                </button>
              </div>

              {impactResult && (
                <div className="space-y-3 pt-1">
                  <div className="p-3 rounded-lg bg-[#080907] border border-[#292A23] space-y-2 text-xs">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="font-mono font-semibold text-[#F5F3ED]">
                        {impactResult.mode === 'add'
                          ? impactResult.already_exists
                            ? '✓ Already Added / Attempted in History'
                            : '✦ New Add-On — Not Yet Added in History'
                          : `⚠ Removal & Change Impact Report for "${impactResult.feature}"`}
                      </span>
                      {impactResult.who_to_ask.length > 0 && (
                        <span className="font-mono text-[11px] text-[#B9915E]">
                          Consult: {impactResult.who_to_ask.map((u) => `@${u}`).join(', ')}
                        </span>
                      )}
                    </div>
                    <p className="text-[#D4CBBF] leading-relaxed">{impactResult.recommendation}</p>
                    <pre className="p-2 rounded bg-[#12130F] border border-[#292A23] text-[10px] font-mono text-[#757F6C] overflow-x-auto">
                      {impactResult.cypher_query}
                    </pre>
                  </div>

                  {/* Mode = ADD: When & How it was added + What else gets affected */}
                  {impactResult.mode === 'add' && (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
                      <div className="p-3 rounded-lg bg-[#080907] border border-[#292A23] space-y-2">
                        <h4 className="font-mono font-semibold text-[#3fb950] uppercase text-[11px]">
                          When &amp; How It Was Added Before
                        </h4>
                        {impactResult.existing_history.length === 0 ? (
                          <p className="text-[#A5A69D]">
                            No prior implementation found in the graph—this is a net-new feature/add-on.
                          </p>
                        ) : (
                          impactResult.existing_history.map((h) => (
                            <div key={h.decision_id} className="p-2.5 rounded bg-[#12130F] border border-[#292A23] space-y-1">
                              <div className="flex items-center justify-between font-mono text-[11px]">
                                <span className="text-[#B9915E]">{h.date} · @{h.author}</span>
                                <span className="px-1.5 py-0.5 rounded bg-[#080907] text-[#3fb950]">{h.state}</span>
                              </div>
                              <p className="font-semibold text-[#F5F3ED]">{h.summary}</p>
                              <p className="text-[#A5A69D] text-[11px]">How: {h.how_added}</p>
                              {h.quote && (
                                <p className="text-[11px] italic text-[#D4CBBF]">"{h.quote}" ({h.source_id})</p>
                              )}
                            </div>
                          ))
                        )}
                      </div>

                      <div className="p-3 rounded-lg bg-[#080907] border border-[#292A23] space-y-2">
                        <h4 className="font-mono font-semibold text-[#B9915E] uppercase text-[11px]">
                          What Else Will Be Affected (Blast Radius)
                        </h4>
                        {impactResult.affected_if_added.map((af) => (
                          <div key={af.path} className="p-2.5 rounded bg-[#12130F] border border-[#292A23] space-y-1">
                            <div className="flex items-center justify-between font-mono text-[11px]">
                              <span className="text-[#F5F3ED] font-semibold">{af.path}</span>
                              <span className="text-[#B9915E]">{af.risk_badge}</span>
                            </div>
                            <p className="text-[#A5A69D] text-[11px]">{af.reason}</p>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Mode = REMOVE: All Related PRs + Required Co-Changes + What Could Go Wrong & Evidence */}
                  {impactResult.mode === 'remove' && (
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
                      <div className="p-3 rounded-lg bg-[#080907] border border-[#292A23] space-y-2">
                        <h4 className="font-mono font-semibold text-[#AFD2FA] uppercase text-[11px]">
                          All Related Pull Requests ({impactResult.related_pull_requests.length})
                        </h4>
                        {impactResult.related_pull_requests.map((pr, idx) => (
                          <div key={idx} className="p-2.5 rounded bg-[#12130F] border border-[#292A23] space-y-1">
                            <div className="flex items-center justify-between font-mono text-[10px] text-[#A5A69D]">
                              <span>{pr.source_id}</span>
                              <span>{pr.date} · @{pr.author}</span>
                            </div>
                            <p className="text-[#F5F3ED] font-medium">{pr.summary}</p>
                          </div>
                        ))}
                      </div>

                      <div className="p-3 rounded-lg bg-[#080907] border border-[#292A23] space-y-2">
                        <h4 className="font-mono font-semibold text-[#B9915E] uppercase text-[11px]">
                          What Else You Must Change (Co-Changes)
                        </h4>
                        {impactResult.required_co_changes.map((co) => (
                          <div key={co.path} className="p-2.5 rounded bg-[#12130F] border border-[#292A23] space-y-1">
                            <p className="font-mono font-semibold text-[#F5F3ED]">{co.path}</p>
                            <p className="text-[11px] text-[#A5A69D]">{co.reason}</p>
                          </div>
                        ))}
                      </div>

                      <div className="p-3 rounded-lg bg-[#080907] border border-[#f85149]/40 space-y-2">
                        <h4 className="font-mono font-semibold text-[#f85149] uppercase text-[11px]">
                          What Could Go Wrong &amp; Verbatim Evidence
                        </h4>
                        {impactResult.what_could_go_wrong.map((w, idx) => (
                          <div key={idx} className="p-2.5 rounded bg-[#12130F] border border-[#f85149]/30 space-y-1">
                            <span className="text-[10px] font-mono text-[#f85149] font-bold">[{w.severity}]</span>
                            <p className="font-semibold text-[#F5F3ED]">{w.risk_title}</p>
                            <p className="text-[11px] text-[#D4CBBF]">{w.explanation}</p>
                          </div>
                        ))}
                        {impactResult.supporting_evidence.map((ev, idx) => (
                          <blockquote
                            key={idx}
                            className="p-2 rounded bg-[#12130F] border-l-2 border-[#3fb950] text-[11px] italic text-[#A5A69D]"
                          >
                            "{ev.quote}" — <span className="not-italic font-mono text-[#3fb950]">{ev.source_id}</span>
                          </blockquote>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </section>
          </div>
        )}
      </main>
    </div>
  );
}
