import React, { useCallback, useEffect, useRef, useState } from 'react';
import type { Repository } from '../types';
import { startIngest, fetchIngestStatus, fetchRepository } from '../services/api';
import type { IngestJobStatus } from '../services/api';
import { 
  GitBranch, 
  Search, 
  Check, 
  ExternalLink, 
  X, 
  Database, 
  ShieldCheck, 
  FileCode, 
  GitCommit,
  GitPullRequest,
  Plus,
} from 'lucide-react';

interface LegacyRepositorySelectorModalProps {
  isOpen: boolean;
  onClose: () => void;
  repositories: Repository[];
  selectedRepo: Repository | null;
  onSelectRepo: (repo: Repository) => void;
  onAddNewRepo?: (newRepo: Repository) => void;
}

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

function getFocusableElements(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
    (element) => !element.hasAttribute('disabled') && element.getAttribute('aria-hidden') !== 'true',
  );
}

export const LegacyRepositorySelectorModal: React.FC<LegacyRepositorySelectorModalProps> = ({
  isOpen,
  onClose,
  repositories,
  selectedRepo,
  onSelectRepo,
}) => {
  const [searchQuery, setSearchQuery] = useState('');

  if (!isOpen) return null;

  const filteredRepos = repositories
    .filter(r =>
      r.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (r.owner && r.owner.toLowerCase().includes(searchQuery.toLowerCase()))
    );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6">
      {/* Backdrop */}
      <div
        className="fixed inset-0 transition-opacity"
        style={{ background: 'rgba(0,0,0,0.75)' }}
        onClick={onClose}
      />

      {/* Modal */}
      <div
        className="relative w-full max-w-xl rounded-xl overflow-hidden z-10 flex flex-col"
        style={{
          background: 'var(--surface-card)',
          border: '1px solid var(--border)',
          boxShadow: '0 0 60px rgba(0,0,0,0.6), 0 0 30px rgba(192,193,255,0.05)',
          maxHeight: '80vh',
        }}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between px-5 py-4"
          style={{ borderBottom: '1px solid var(--border)' }}
        >
          <div className="flex items-center gap-3">
            <div
              className="p-2 rounded-lg"
              style={{ background: 'var(--accent-soft)', border: '1px solid var(--accent-glow)' }}
            >
              <GitBranch className="w-4 h-4" style={{ color: 'var(--primary)' }} />
            </div>
            <div>
              <h3
                style={{
                  fontFamily: "'Inter', sans-serif",
                  fontWeight: 700,
                  fontSize: '15px',
                  color: 'var(--text)',
                  margin: 0,
                }}
              >
                Select Repository
              </h3>
              <p style={{ fontSize: '11px', color: 'var(--text-muted)', margin: 0, marginTop: '2px', fontFamily: 'monospace' }}>
                Choose a repository to inspect architectural provenance
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg cursor-pointer transition-colors"
            style={{ color: 'var(--text-muted)', background: 'transparent' }}
            onMouseEnter={e => {
              (e.currentTarget as HTMLButtonElement).style.background = 'var(--surface-hover)';
              (e.currentTarget as HTMLButtonElement).style.color = 'var(--text)';
            }}
            onMouseLeave={e => {
              (e.currentTarget as HTMLButtonElement).style.background = 'transparent';
              (e.currentTarget as HTMLButtonElement).style.color = 'var(--text-muted)';
            }}
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Search */}
        <div className="px-5 pt-4 pb-2">
          <div
            className="flex items-center gap-2 px-3 py-2 rounded-lg"
            style={{ background: 'var(--surface-lowest)', border: '1px solid var(--border)' }}
          >
            <Search className="w-3.5 h-3.5 shrink-0" style={{ color: 'var(--text-subtle)' }} />
            <input
              type="text"
              placeholder="Filter repositories..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              style={{
                flex: 1,
                background: 'transparent',
                border: 'none',
                outline: 'none',
                fontSize: '12px',
                fontFamily: 'monospace',
                color: 'var(--text)',
              }}
            />
          </div>
        </div>

        {/* Repo List */}
        <div className="p-5 pt-3 flex flex-col gap-3 overflow-y-auto">
          {filteredRepos.length === 0 ? (
            <div
              className="text-center py-10 font-mono text-xs"
              style={{ color: 'var(--text-subtle)' }}
            >
              No repositories match "{searchQuery}"
            </div>
          ) : (
            filteredRepos.map((repo) => {
              const isSelected = selectedRepo?.id === repo.id;
              return (
                <div
                  key={repo.id}
                  onClick={() => { onSelectRepo(repo); onClose(); }}
                  className="rounded-xl p-4 cursor-pointer transition-all"
                  style={{
                    background: isSelected ? 'var(--surface-raised)' : 'transparent',
                    border: `1px solid ${isSelected ? 'var(--evidence-emerald)' : 'var(--border)'}`,
                    boxShadow: isSelected ? '0 0 16px rgba(16,185,129,0.10)' : 'none',
                  }}
                  onMouseEnter={e => {
                    if (!isSelected) {
                      (e.currentTarget as HTMLDivElement).style.borderColor = 'var(--primary)';
                      (e.currentTarget as HTMLDivElement).style.background = 'var(--surface-raised)';
                    }
                  }}
                  onMouseLeave={e => {
                    if (!isSelected) {
                      (e.currentTarget as HTMLDivElement).style.borderColor = 'var(--border)';
                      (e.currentTarget as HTMLDivElement).style.background = 'transparent';
                    }
                  }}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <span
                          style={{
                            fontFamily: 'monospace',
                            fontSize: '14px',
                            fontWeight: 600,
                            color: isSelected ? 'var(--evidence-emerald)' : 'var(--text)',
                          }}
                        >
                          {repo.name}
                        </span>
                        {isSelected && (
                          <span
                            className="flex items-center gap-1 text-[10px] font-mono px-1.5 py-0.5 rounded"
                            style={{
                              color: 'var(--evidence-emerald)',
                              background: 'var(--emerald-soft)',
                              border: '1px solid var(--emerald-border)',
                            }}
                          >
                            <Check className="w-3 h-3" /> Active
                          </span>
                        )}
                        {repo.fixture && (
                          <span
                            className="text-[10px] font-mono px-1.5 py-0.5 rounded"
                            style={{
                              color: 'var(--rationale-amber)',
                              background: 'var(--amber-soft)',
                              border: '1px solid var(--amber-border)',
                            }}
                          >
                            fixture
                          </span>
                        )}
                      </div>

                      {repo.scope && (
                        <p style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '8px' }}>
                          {repo.scope}
                        </p>
                      )}

                      {/* Metrics */}
                      <div className="flex flex-wrap items-center gap-3" style={{ fontSize: '11px', fontFamily: 'monospace', color: 'var(--text-muted)' }}>
                        <div className="flex items-center gap-1">
                          <ShieldCheck className="w-3 h-3" style={{ color: 'var(--evidence-emerald)' }} />
                          <span>{repo.counts.decisions} decisions</span>
                        </div>
                        <span style={{ color: 'var(--border-strong)' }}>•</span>
                        <div className="flex items-center gap-1">
                          <FileCode className="w-3 h-3" style={{ color: 'var(--entity-cyan)' }} />
                          <span>{repo.counts.entities} entities</span>
                        </div>
                        <span style={{ color: 'var(--border-strong)' }}>•</span>
                        <div className="flex items-center gap-1">
                          <GitPullRequest className="w-3 h-3" style={{ color: 'var(--primary-container)' }} />
                          <span>{repo.counts.pull_requests} PRs</span>
                        </div>
                        <span style={{ color: 'var(--border-strong)' }}>•</span>
                        <div className="flex items-center gap-1">
                          <GitCommit className="w-3 h-3" style={{ color: 'var(--text-muted)' }} />
                          <span>{repo.counts.commits} commits</span>
                        </div>
                      </div>
                    </div>

                    {repo.url && (
                      <a
                        href={repo.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        onClick={(e) => e.stopPropagation()}
                        className="p-1.5 rounded-lg flex-shrink-0 transition-colors"
                        style={{ color: 'var(--text-subtle)' }}
                        title="Open on GitHub"
                        onMouseEnter={e => (e.currentTarget as HTMLAnchorElement).style.color = 'var(--primary)'}
                        onMouseLeave={e => (e.currentTarget as HTMLAnchorElement).style.color = 'var(--text-subtle)'}
                      >
                        <ExternalLink className="w-3.5 h-3.5" />
                      </a>
                    )}
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
};


interface RepositorySelectorModalProps {
  isOpen: boolean;
  onClose: () => void;
  repositories: Repository[];
  selectedRepo: Repository | null;
  onSelectRepo: (repo: Repository) => void;
  onAddNewRepo?: (newRepo: Repository) => void;
}

export const RepositorySelectorModal: React.FC<RepositorySelectorModalProps> = ({
  isOpen,
  onClose,
  repositories,
  selectedRepo,
  onSelectRepo,
  onAddNewRepo,
}) => {
  const [searchQuery, setSearchQuery] = useState('');
  const [activeTab, setActiveTab] = useState<'existing' | 'custom'>('existing');
  const dialogRef = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);

  // Ingest state
  const [ingestRepo, setIngestRepo] = useState('');
  const [ingestMode, setIngestMode] = useState<'quick' | 'deep'>('quick');
  const [ingestFiles, setIngestFiles] = useState('');
  const [ingestJobId, setIngestJobId] = useState<string | null>(null);
  const [ingestStatus, setIngestStatus] = useState<IngestJobStatus | null>(null);
  const [ingestError, setIngestError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const clearPolling = useCallback(() => {
    if (intervalRef.current !== null) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, []);

  // Polling effect
  useEffect(() => {
    if (!ingestJobId) return;
    clearPolling();
    intervalRef.current = setInterval(async () => {
      try {
        const status = await fetchIngestStatus(ingestJobId);
        setIngestStatus(status);
        if (status.status === 'done') {
          clearPolling();
          const canonicalSlug = status.repo || ingestRepo.trim().replace(/^https?:\/\/github\.com\//i, '').replace(/\.git$/i, '').replace(/^\/+|\/+$/g, '');
          const resultId = status.result_repo_id ?? canonicalSlug.replace('/', '-');
          let resolvedRepo: Repository = {
            id: resultId,
            name: canonicalSlug.split('/').pop() || canonicalSlug,
            full_name: canonicalSlug,
            url: `https://github.com/${canonicalSlug}`,
            counts: { decisions: 0, entities: 0, pull_requests: 0, commits: 0 },
            fixture: false,
          };
          try {
            const fetched = await fetchRepository(resultId);
            if (fetched) resolvedRepo = fetched;
          } catch {
            // Use fallback resolvedRepo if backend detail endpoint is still settling
          }
          if (onAddNewRepo) {
            onAddNewRepo(resolvedRepo);
          }
          onSelectRepo(resolvedRepo);
          setIngestJobId(null);
          setIngestStatus(null);
          setIngestRepo('');
          setIngestFiles('');
          onClose();
        } else if (status.status === 'failed') {
          clearPolling();
          setIngestJobId(null);
          setIngestError(status.error ?? 'Ingestion failed');
        }
      } catch (e) {
        // transient poll error — keep polling
        console.error('Ingest poll error', e);
      }
    }, 3000);
    return clearPolling;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ingestJobId]);

  // Cleanup on unmount
  useEffect(() => clearPolling, [clearPolling]);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  // Dialog keyboard contract: trap Tab inside the modal, close on Escape, and
  // hand focus back to the trigger when the dialog unmounts.
  useEffect(() => {
    if (!isOpen) return;

    const previouslyFocused = document.activeElement as HTMLElement | null;
    const dialog = dialogRef.current;
    if (dialog) {
      const focusable = getFocusableElements(dialog);
      (focusable[0] ?? dialog).focus();
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== 'Tab') return;

      const node = dialogRef.current;
      if (!node) return;

      const focusable = getFocusableElements(node);
      if (focusable.length === 0) {
        event.preventDefault();
        node.focus();
        return;
      }

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;

      if (event.shiftKey && (active === first || !node.contains(active))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (active === last || !node.contains(active))) {
        event.preventDefault();
        first.focus();
      }
    };

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    document.addEventListener('keydown', handleKeyDown);

    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = previousOverflow;
      if (previouslyFocused && document.contains(previouslyFocused)) {
        previouslyFocused.focus();
      }
    };
  }, [isOpen]);

  if (!isOpen) return null;

  const filteredRepos = repositories.filter(
    (r) =>
      r.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (r.owner && r.owner.toLowerCase().includes(searchQuery.toLowerCase()))
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6">
      {/* Backdrop */}
      <div 
        className="fixed inset-0 bg-black/70 transition-opacity"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Modal Dialog */}
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="repository-selector-title"
        aria-describedby="repository-selector-description"
        tabIndex={-1}
        className="relative w-full max-w-2xl bg-[#191628] border border-[#CAC4CE]/25 rounded-2xl shadow-2xl overflow-hidden z-10 flex flex-col max-h-[85vh] text-[#F7ECE1]"
      >
        
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[#CAC4CE]/20 bg-[#242038]">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-xl bg-[#2E284A] text-[#C5B0E6] border border-[#9067C6]/45">
              <GitBranch className="w-4 h-4 text-[#C5B0E6]" />
            </div>
            <div>
              <h3 id="repository-selector-title" className="text-base font-semibold text-[#F7ECE1] leading-snug">
                Select Target Repository
              </h3>
              <p id="repository-selector-description" className="text-xs text-[#CAC4CE] mt-0.5">
                Choose a repository to inspect architectural provenance
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 text-[#F7ECE1] bg-[#2E284A] hover:bg-[#3A335C] border border-[#CAC4CE]/25 rounded-lg transition-colors cursor-pointer"
            aria-label="Close repository selector"
            title="Close (Esc)"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Navigation Tabs */}
        <div className="flex border-b border-[#CAC4CE]/20 px-6 bg-[#242038] gap-1">
          <button
            onClick={() => setActiveTab('existing')}
            className={`py-3 px-4 text-xs font-semibold border-b-2 transition-colors flex items-center gap-2 cursor-pointer rounded-t-lg ${
              activeTab === 'existing'
                ? 'border-[#9067C6] text-[#F7ECE1] bg-[#2E284A]'
                : 'border-transparent text-[#CAC4CE] hover:text-[#F7ECE1] hover:bg-[#2E284A]/55'
            }`}
          >
            <Database className={`w-3.5 h-3.5 ${activeTab === 'existing' ? 'text-[#C5B0E6]' : 'text-[#8D86C9]'}`} />
            <span>Available Repositories ({repositories.length})</span>
          </button>
          <button
            onClick={() => setActiveTab('custom')}
            className={`py-3 px-4 text-xs font-semibold border-b-2 transition-colors flex items-center gap-2 cursor-pointer rounded-t-lg ${
              activeTab === 'custom'
                ? 'border-[#9067C6] text-[#F7ECE1] bg-[#2E284A]'
                : 'border-transparent text-[#CAC4CE] hover:text-[#F7ECE1] hover:bg-[#2E284A]/55'
            }`}
          >
            <Plus className={`w-3.5 h-3.5 ${activeTab === 'custom' ? 'text-[#C5B0E6]' : 'text-[#8D86C9]'}`} />
            <span>Add Target</span>
          </button>
        </div>

        {/* Content Body */}
        {activeTab === 'existing' ? (
          <div className="p-6 flex flex-col gap-4 overflow-y-auto bg-[#191628]">
            {/* Search Input */}
            <div className="relative">
              <Search className="w-4 h-4 text-[#CAC4CE] absolute left-3.5 top-1/2 -translate-y-1/2 pointer-events-none" />
              <input
                type="text"
                placeholder="Filter by name, owner, or scope..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-10 pr-4 py-2.5 bg-[#161324] border border-[#CAC4CE]/25 rounded-xl text-xs font-mono text-[#F7ECE1] placeholder:text-[#CAC4CE]/70 focus:outline-none focus:border-[#9067C6] focus:ring-2 focus:ring-[#9067C6]/35 transition-colors"
              />
            </div>

            {/* Repositories List */}
            <div className="space-y-3">
              {filteredRepos.length === 0 ? (
                <div className="text-center py-8 text-[#CAC4CE] text-xs font-mono bg-[#242038] rounded-xl border border-[#CAC4CE]/20">
                  No repositories match "{searchQuery}"
                </div>
              ) : (
                filteredRepos.map((repo) => {
                  const isSelected = selectedRepo?.id === repo.id;
                  return (
                    <div
                      key={repo.id}
                      role="button"
                      tabIndex={0}
                      aria-pressed={isSelected}
                      aria-label={`${isSelected ? 'Selected repository' : 'Select repository'} ${repo.name}`}
                      onClick={() => {
                        onSelectRepo(repo);
                        onClose();
                      }}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter' || event.key === ' ' || event.key === 'Spacebar') {
                          event.preventDefault();
                          onSelectRepo(repo);
                          onClose();
                        }
                      }}
                      className={`group p-4 rounded-xl border transition-all cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#9067C6] ${
                        isSelected
                          ? 'bg-[#322952] border-[#9067C6] ring-1 ring-[#9067C6]/50 shadow-sm'
                          : 'bg-[#242038] border-[#CAC4CE]/20 hover:border-[#9067C6]/70 hover:bg-[#2C2647]'
                      }`}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="space-y-1.5 flex-1 min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            {isSelected && (
                              <span
                                className="w-2 h-2 rounded-full bg-[#C5B0E6] shrink-0"
                                aria-hidden="true"
                              />
                            )}
                            <span className="font-mono text-sm font-semibold text-[#F7ECE1] group-hover:text-white transition-colors truncate">
                              {repo.name}
                            </span>
                            {isSelected && (
                              <span className="inline-flex items-center gap-1 text-[11px] font-mono font-semibold text-white bg-[#9067C6] px-2 py-0.5 rounded-md">
                                <Check className="w-3 h-3" /> Selected
                              </span>
                            )}
                            {repo.fixture && (
                              <span className="text-[10px] font-mono font-semibold text-[#F7ECE1] bg-[#161324] border border-[#CAC4CE]/25 px-1.5 py-0.5 rounded">
                                fixture
                              </span>
                            )}
                          </div>

                          {repo.scope && (
                            <p className="text-xs text-[#CAC4CE] line-clamp-1">
                              {repo.scope}
                            </p>
                          )}

                          {/* Metric Pill Grid */}
                          <div className="flex flex-wrap items-center gap-2.5 pt-1 text-xs font-mono text-[#CAC4CE]">
                            <div className="flex items-center gap-1 text-[#F7ECE1]">
                              <ShieldCheck className="w-3.5 h-3.5 text-[#3fb950]" />
                              <span>{repo.counts.decisions} decisions</span>
                            </div>
                            <span className="text-[#CAC4CE]/40">•</span>
                            <div className="flex items-center gap-1 text-[#F7ECE1]">
                              <FileCode className="w-3.5 h-3.5 text-[#C5B0E6]" />
                              <span>{repo.counts.entities} entities</span>
                            </div>
                            <span className="text-[#CAC4CE]/40">•</span>
                            <div className="flex items-center gap-1 text-[#F7ECE1]">
                              <GitPullRequest className="w-3.5 h-3.5 text-[#8D86C9]" />
                              <span>{repo.counts.pull_requests} PRs</span>
                            </div>
                            <span className="text-[#CAC4CE]/40">•</span>
                            <div className="flex items-center gap-1 text-[#F7ECE1]">
                              <GitCommit className="w-3.5 h-3.5 text-[#CAC4CE]" />
                              <span>{repo.counts.commits} commits</span>
                            </div>
                          </div>
                        </div>

                        {repo.url && (
                          <a
                            href={repo.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            onClick={(e) => e.stopPropagation()}
                            onKeyDown={(e) => e.stopPropagation()}
                            className={`p-2 rounded-lg transition-colors flex-shrink-0 border ${
                              isSelected
                                ? 'text-[#F7ECE1] bg-[#242038] border-[#9067C6]/50 hover:border-[#9067C6]'
                                : 'text-[#CAC4CE] border-transparent hover:text-[#F7ECE1] hover:bg-[#322952]'
                            }`}
                            title="Open repository in GitHub"
                            aria-label={`Open ${repo.name} on GitHub`}
                          >
                            <ExternalLink className="w-3.5 h-3.5" />
                          </a>
                        )}
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        ) : (
          <div className="p-6 space-y-4 overflow-y-auto bg-[#191628]">
            <div className="space-y-3.5">
              <div>
                <label htmlFor="ingest-repo-input" className="block text-xs font-semibold text-[#F7ECE1] mb-1.5">
                  GitHub Repository URL or owner/repo
                </label>
                <input
                  id="ingest-repo-input"
                  type="text"
                  placeholder="https://github.com/pallets/flask or pallets/flask"
                  value={ingestRepo}
                  onChange={(e) => {
                    setIngestRepo(e.target.value);
                    setIngestError(null);
                  }}
                  disabled={isSubmitting || !!ingestJobId}
                  className="w-full px-3.5 py-2.5 bg-[#161324] border border-[#CAC4CE]/25 rounded-xl text-xs font-mono text-[#F7ECE1] placeholder:text-[#CAC4CE]/70 focus:outline-none focus:border-[#9067C6] focus:ring-2 focus:ring-[#9067C6]/35"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-[#F7ECE1] mb-1.5">
                  Scan Mode
                </label>
                <div className="grid grid-cols-2 gap-2.5">
                  <button
                    type="button"
                    disabled={isSubmitting || !!ingestJobId}
                    onClick={() => setIngestMode('quick')}
                    className={`p-3 rounded-xl border text-left transition-colors cursor-pointer ${
                      ingestMode === 'quick'
                        ? 'bg-[#322952] border-[#9067C6] text-[#F7ECE1] ring-1 ring-[#9067C6]/50'
                        : 'bg-[#242038] border-[#CAC4CE]/20 text-[#CAC4CE] hover:border-[#9067C6]/65 hover:text-[#F7ECE1]'
                    }`}
                  >
                    <div className="text-xs font-semibold text-[#F7ECE1]">Quick Start (~30–45s)</div>
                    <div className="text-[11px] text-[#CAC4CE] mt-0.5">Top 8 hotspot files · 25 high-signal PRs</div>
                  </button>
                  <button
                    type="button"
                    disabled={isSubmitting || !!ingestJobId}
                    onClick={() => setIngestMode('deep')}
                    className={`p-3 rounded-xl border text-left transition-colors cursor-pointer ${
                      ingestMode === 'deep'
                        ? 'bg-[#322952] border-[#9067C6] text-[#F7ECE1] ring-1 ring-[#9067C6]/50'
                        : 'bg-[#242038] border-[#CAC4CE]/20 text-[#CAC4CE] hover:border-[#9067C6]/65 hover:text-[#F7ECE1]'
                    }`}
                  >
                    <div className="text-xs font-semibold text-[#F7ECE1]">Deep Scan</div>
                    <div className="text-[11px] text-[#CAC4CE] mt-0.5">Top 20 files · up to 200 PRs</div>
                  </button>
                </div>
              </div>

              <div>
                <label htmlFor="ingest-files-input" className="block text-xs font-semibold text-[#F7ECE1] mb-1.5">
                  Target Files <span className="font-normal text-[#CAC4CE]">(optional — leave blank for zero-config auto-discovery)</span>
                </label>
                <input
                  id="ingest-files-input"
                  type="text"
                  placeholder="Leave blank to auto-discover hotspot files, or comma-separate paths"
                  value={ingestFiles}
                  onChange={(e) => setIngestFiles(e.target.value)}
                  disabled={isSubmitting || !!ingestJobId}
                  className="w-full px-3.5 py-2.5 bg-[#161324] border border-[#CAC4CE]/25 rounded-xl text-xs font-mono text-[#F7ECE1] placeholder:text-[#CAC4CE]/70 focus:outline-none focus:border-[#9067C6] focus:ring-2 focus:ring-[#9067C6]/35"
                />
              </div>

              <button
                onClick={async () => {
                  const repo = ingestRepo.trim();
                  if (!repo || !repo.includes('/')) {
                    setIngestError('Please enter a valid GitHub URL or owner/repo (e.g. pallets/flask)');
                    return;
                  }
                  const parsedFiles = ingestFiles
                    .split(',')
                    .map((s) => s.trim())
                    .filter(Boolean);
                  setIngestError(null);
                  setIsSubmitting(true);
                  try {
                    const job = await startIngest(repo, {
                      mode: ingestMode,
                      files: parsedFiles,
                    });
                    setIngestJobId(job.job_id);
                    setIngestStatus(job);
                  } catch (e) {
                    setIngestError(e instanceof Error ? e.message : String(e));
                  } finally {
                    setIsSubmitting(false);
                  }
                }}
                disabled={isSubmitting || !!ingestJobId || !ingestRepo.trim()}
                className="px-4 py-2.5 bg-[#9067C6] text-white text-xs font-semibold rounded-xl hover:bg-[#7B52B3] transition-colors disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer shadow-sm"
              >
                {isSubmitting ? 'Starting…' : ingestMode === 'quick' ? 'Quick Analyze Repository' : 'Deep Analyze Repository'}
              </button>

              {ingestError && (
                <p className="text-[#f85149] text-xs font-mono font-medium">{ingestError}</p>
              )}

              {ingestStatus && ingestStatus.status !== 'failed' && (
                <div className="space-y-2 pt-1 bg-[#242038] p-3.5 rounded-xl border border-[#CAC4CE]/25">
                  <div className="flex justify-between items-center text-xs font-mono text-[#F7ECE1]">
                    <span>{ingestStatus.phase ?? ingestStatus.status}</span>
                    <span>{ingestStatus.progress_pct}%</span>
                  </div>
                  <div className="w-full bg-[#161324] rounded-full h-2">
                    <div
                      className="bg-[#9067C6] h-2 rounded-full transition-all"
                      style={{ width: `${ingestStatus.progress_pct}%` }}
                    />
                  </div>
                  {ingestStatus.status === 'done' && (
                    <p className="text-xs font-mono font-medium text-[#3fb950]">Done! Loading repository…</p>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
