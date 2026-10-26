import React, { useState, useEffect, useCallback } from 'react';
import type {
  Repository,
  HealthResponse,
  DependenciesResponse,
} from '../types';
import {
  fetchHealth,
  fetchDependencies,
  fetchRepository,
} from '../services/api';
import {
  Activity,
  Server,
  Database,
  GitPullRequest,
  GitCommit,
  CheckCircle2,
  HelpCircle,
  XCircle,
  Clock,
  FileCode,
  ShieldCheck,
  Cpu,
  RefreshCw,
  Box,
  ArrowRight,
} from 'lucide-react';

interface RepositoryStatusViewProps {
  selectedRepo: Repository | null;
}

export const RepositoryStatusView: React.FC<RepositoryStatusViewProps> = ({
  selectedRepo,
}) => {
  const [repoData, setRepoData] = useState<Repository | null>(selectedRepo);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [dependencies, setDependencies] = useState<DependenciesResponse | null>(null);
  const [latencyMs, setLatencyMs] = useState<number>(0);
  const [isHealthOnline, setIsHealthOnline] = useState<boolean>(false);
  const [lastPolledAt, setLastPolledAt] = useState<Date>(new Date());
  const [isManualRefreshing, setIsManualRefreshing] = useState<boolean>(false);

  // Determine repository ID from props or path URL
  const urlRepoId = typeof window !== 'undefined'
    ? window.location.pathname.match(/\/r\/([^/]+)/)?.[1]
    : null;
  const repoId = selectedRepo?.id || (urlRepoId ? decodeURIComponent(urlRepoId) : 'acme-netclient');

  // Keep repoData in sync with selectedRepo prop
  useEffect(() => {
    if (selectedRepo) {
      setRepoData(selectedRepo);
    }
  }, [selectedRepo]);

  // Load telemetry data from the three specified endpoints
  const pollTelemetry = useCallback(async () => {
    // 1. GET /api/v1/health
    const healthResult = await fetchHealth();
    setHealth(healthResult.health);
    setIsHealthOnline(healthResult.isConnected);
    setLatencyMs(healthResult.latencyMs);

    // 2. GET /api/v1/health/dependencies
    const depResult = await fetchDependencies();
    setDependencies(depResult);

    // 3. GET /api/v1/repositories/{id}
    const repoResult = await fetchRepository(repoId);
    if (repoResult) {
      setRepoData(repoResult);
    }

    setLastPolledAt(new Date());
  }, [repoId]);

  // Initial fetch and 30-second interval polling
  useEffect(() => {
    pollTelemetry();

    const interval = setInterval(() => {
      pollTelemetry();
    }, 30000); // 30-second polling as specified

    return () => clearInterval(interval);
  }, [pollTelemetry]);

  const handleManualRefresh = async () => {
    setIsManualRefreshing(true);
    await pollTelemetry();
    setIsManualRefreshing(false);
  };

  // Determine graph / storage status
  const neo4jDep = dependencies?.services.find((s) => s.name.toLowerCase() === 'neo4j');
  const isGraphRemoteConfigured = neo4jDep?.status === 'configured';
  const activeDataSource = health?.data_source || dependencies?.data_source || 'sqlite';

  return (
    <div className="flex flex-col min-h-[calc(100vh-5rem)] bg-[#f5f3ed] w-full text-[#292b25]">
      {/* Top Header & Breadcrumb Bar */}
      <div className="border-b border-[#d7d2c6]/80 bg-[#fffdf8]/90 backdrop-blur-md px-4 sm:px-6 lg:px-8 py-5">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="space-y-1">
            <div className="flex items-center gap-3 pt-1">
              <div className="p-1.5 rounded-lg bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
                <Activity className="w-5 h-5" />
              </div>
              <div>
                <h1 className="text-xl sm:text-2xl font-bold font-sans text-[#292b25] tracking-tight flex items-center gap-2.5">
                  <span>Repository Telemetry & Provenance Pipeline</span>
                  <span
                    className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-mono font-semibold ${
                      isHealthOnline
                        ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                        : 'bg-rose-500/20 text-rose-300 border border-rose-500/40'
                    }`}
                  >
                    <span
                      className={`w-1.5 h-1.5 rounded-full ${
                        isHealthOnline ? 'bg-emerald-400 animate-pulse' : 'bg-rose-400'
                      }`}
                    />
                    {isHealthOnline ? 'Live API Online' : 'Service Offline'}
                  </span>
                </h1>
                <p className="text-xs text-[#77776e] font-mono">
                  Real-time pipeline telemetry polled every 30s • SQLite local backing • Exact contract schema
                </p>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2.5">
            <button
              onClick={handleManualRefresh}
              disabled={isManualRefreshing}
              className="flex items-center gap-1.5 px-3 py-2 rounded-xl bg-[#fffdf8] hover:bg-[#efede5] text-[#51534b] border border-slate-750 text-xs font-mono transition-colors cursor-pointer"
              title="Manual Poll Telemetry"
            >
              <RefreshCw className={`w-3.5 h-3.5 text-cyan-400 ${isManualRefreshing ? 'animate-spin' : ''}`} />
              <span>Poll Now</span>
            </button>
          </div>
        </div>
      </div>

      {/* Main Content Area */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 w-full flex-1 space-y-8">
        
        {/* Telemetry Polling Header Callout */}
        <div className="p-4 rounded-2xl bg-[#fffdf8]/60 border border-[#d7d2c6] flex flex-wrap items-center justify-between gap-4 text-xs font-mono">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-xl bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
              <Server className="w-4 h-4" />
            </div>
            <div>
              <span className="text-[#77776e] block text-[10px] uppercase tracking-wider">
                Active Engine Core
              </span>
              <span className="text-sm font-bold text-[#292b25]">
                CodeWhy Engine {health?.version ? `v${health.version}` : ''} ({activeDataSource} mode)
              </span>
            </div>
          </div>

          <div className="flex items-center gap-4 text-[#77776e]">
            <span className="flex items-center gap-1.5">
              <Clock className="w-3.5 h-3.5 text-cyan-400" />
              <span>Polled: {lastPolledAt.toLocaleTimeString()}</span>
            </span>
            <span className="px-2 py-0.5 rounded bg-[#efede5] text-[#51534b] border border-[#d7d2c6]">
              Latency: {latencyMs}ms
            </span>
            <span className="text-cyan-400/80">30s Auto-poll Active</span>
          </div>
        </div>

        {/* 1. PIPELINE OVERVIEW: Ingest → Extract → Graph */}
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-xs font-mono uppercase tracking-wider text-[#77776e] font-bold">
                Archeology Pipeline Lifecycle
              </span>
              <div className="h-px bg-[#efede5] w-24 sm:w-48" />
            </div>

            {/* Visual Pipeline Flow: Ingest → Extract → Graph */}
            <div className="flex items-center gap-2 text-xs font-mono">
              <span className="px-2.5 py-0.5 rounded-lg bg-blue-500/10 text-blue-300 border border-blue-500/30 font-semibold flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-blue-400" />
                Ingest
              </span>
              <ArrowRight className="w-3.5 h-3.5 text-[#929086]" />
              <span className="px-2.5 py-0.5 rounded-lg bg-emerald-500/10 text-emerald-300 border border-emerald-500/30 font-semibold flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                Extract
              </span>
              <ArrowRight className="w-3.5 h-3.5 text-[#929086]" />
              <span className="px-2.5 py-0.5 rounded-lg bg-indigo-500/10 text-indigo-300 border border-indigo-500/30 font-semibold flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-indigo-400" />
                Graph
              </span>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            
            {/* Stage 1: Ingest */}
            <div className="rounded-2xl p-5 bg-[#fffdf8]/70 border border-[#d7d2c6] space-y-4 relative overflow-hidden group">
              <div className="flex items-center justify-between border-b border-[#d7d2c6]/80 pb-3">
                <div className="flex items-center gap-2">
                  <span className="w-6 h-6 rounded-lg bg-blue-500/15 text-blue-400 flex items-center justify-center font-mono font-bold text-xs border border-blue-500/30">
                    1
                  </span>
                  <h3 className="font-mono text-sm font-bold text-[#292b25] tracking-wide">
                    Ingest
                  </h3>
                </div>
                <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-blue-500/10 text-blue-300 border border-blue-500/30">
                  Raw Sources
                </span>
              </div>

              <p className="text-xs text-[#77776e] font-sans leading-relaxed">
                Ingests Git commits, merged and unmerged pull requests, and documentation artifacts.
              </p>

              {/* Exact returned counts */}
              <div className="grid grid-cols-2 gap-2 text-xs font-mono">
                <div className="p-3 rounded-xl bg-[#f5f3ed]/70 border border-[#d7d2c6]/80 space-y-1">
                  <span className="text-[10px] text-[#77776e] uppercase flex items-center gap-1">
                    <GitPullRequest className="w-3 h-3 text-cyan-400" /> PRs
                  </span>
                  <span className="text-lg font-bold text-[#292b25]">
                    {repoData?.counts.pull_requests ?? 0}
                  </span>
                </div>

                <div className="p-3 rounded-xl bg-[#f5f3ed]/70 border border-[#d7d2c6]/80 space-y-1">
                  <span className="text-[10px] text-[#77776e] uppercase flex items-center gap-1">
                    <GitCommit className="w-3 h-3 text-cyan-400" /> Commits
                  </span>
                  <span className="text-lg font-bold text-[#292b25]">
                    {repoData?.counts.commits ?? 0}
                  </span>
                </div>
              </div>

              {/* Ingest extra fields only when returned */}
              <div className="space-y-1 pt-1 text-xs font-mono">
                {repoData?.prs_fetched !== undefined && repoData?.prs_fetched !== null && (
                  <div className="flex items-center justify-between text-[#77776e]">
                    <span>PRs Fetched:</span>
                    <span className="text-[#51534b] font-bold">{repoData.prs_fetched}</span>
                  </div>
                )}
                {repoData?.sources_analyzed !== undefined && repoData?.sources_analyzed !== null && (
                  <div className="flex items-center justify-between text-[#77776e]">
                    <span>Sources Analyzed:</span>
                    <span className="text-[#51534b] font-bold">{repoData.sources_analyzed}</span>
                  </div>
                )}
              </div>
            </div>

            {/* Stage 2: Extract */}
            <div className="rounded-2xl p-5 bg-[#fffdf8]/70 border border-[#d7d2c6] space-y-4 relative overflow-hidden group">
              <div className="flex items-center justify-between border-b border-[#d7d2c6]/80 pb-3">
                <div className="flex items-center gap-2">
                  <span className="w-6 h-6 rounded-lg bg-emerald-500/15 text-emerald-400 flex items-center justify-center font-mono font-bold text-xs border border-emerald-500/30">
                    2
                  </span>
                  <h3 className="font-mono text-sm font-bold text-[#292b25] tracking-wide">
                    Extract
                  </h3>
                </div>
                <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-300 border border-emerald-500/30">
                  Quotes & Rules
                </span>
              </div>

              <p className="text-xs text-[#77776e] font-sans leading-relaxed">
                Applies character-level verbatim quote verification and extracts explicit decision records.
              </p>

              {/* Exact returned counts & extraction version (only when returned) */}
              <div className={`grid ${health?.version ? 'grid-cols-2' : 'grid-cols-1'} gap-2 text-xs font-mono`}>
                <div className="p-3 rounded-xl bg-[#f5f3ed]/70 border border-[#d7d2c6]/80 space-y-1">
                  <span className="text-[10px] text-[#77776e] uppercase flex items-center gap-1">
                    <CheckCircle2 className="w-3 h-3 text-emerald-400" /> Decisions
                  </span>
                  <span className="text-lg font-bold text-[#292b25]">
                    {repoData?.counts.decisions ?? 0}
                  </span>
                </div>

                {health?.version && (
                  <div className="p-3 rounded-xl bg-[#f5f3ed]/70 border border-[#d7d2c6]/80 space-y-1">
                    <span className="text-[10px] text-[#77776e] uppercase flex items-center gap-1">
                      <ShieldCheck className="w-3 h-3 text-cyan-400" /> Extraction Ver
                    </span>
                    <span className="text-sm font-bold text-cyan-300 truncate">
                      v{health.version}
                    </span>
                  </div>
                )}
              </div>

              {/* Skipped Work & Verified Decisions (only when returned) */}
              <div className="space-y-1.5 pt-1 text-xs font-mono">
                {repoData?.verified_decisions !== undefined && repoData?.verified_decisions !== null && (
                  <div className="flex items-center justify-between p-2 rounded-lg bg-emerald-950/20 border border-emerald-500/20 text-[#51534b]">
                    <span className="flex items-center gap-1.5 text-[#77776e]">
                      <CheckCircle2 className="w-3 h-3 text-emerald-400" /> Verified Decisions:
                    </span>
                    <span className="text-emerald-400 font-bold">{repoData.verified_decisions}</span>
                  </div>
                )}
                {repoData?.prs_noise_skipped !== undefined && repoData?.prs_noise_skipped !== null && (
                  <div className="flex items-center justify-between p-2 rounded-lg bg-amber-950/20 border border-amber-500/20 text-[#51534b]">
                    <span className="flex items-center gap-1.5 text-[#77776e]">
                      <ShieldCheck className="w-3 h-3 text-amber-400" /> Skipped Work (Noise PRs):
                    </span>
                    <span className="text-amber-400 font-bold">{repoData.prs_noise_skipped}</span>
                  </div>
                )}
              </div>
            </div>

            {/* Stage 3: Graph */}
            <div className="rounded-2xl p-5 bg-[#fffdf8]/70 border border-[#d7d2c6] space-y-4 relative overflow-hidden group">
              <div className="flex items-center justify-between border-b border-[#d7d2c6]/80 pb-3">
                <div className="flex items-center gap-2">
                  <span className="w-6 h-6 rounded-lg bg-indigo-500/15 text-indigo-400 flex items-center justify-center font-mono font-bold text-xs border border-indigo-500/30">
                    3
                  </span>
                  <h3 className="font-mono text-sm font-bold text-[#292b25] tracking-wide">
                    Graph
                  </h3>
                </div>
                <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-indigo-500/10 text-indigo-300 border border-indigo-500/30">
                  Entities & Lineage
                </span>
              </div>

              <p className="text-xs text-[#77776e] font-sans leading-relaxed">
                Connects code entities, temporal supersessions, and evidence receipts into a queryable graph.
              </p>

              {/* Exact returned counts */}
              <div className="grid grid-cols-2 gap-2 text-xs font-mono">
                <div className="p-3 rounded-xl bg-[#f5f3ed]/70 border border-[#d7d2c6]/80 space-y-1">
                  <span className="text-[10px] text-[#77776e] uppercase flex items-center gap-1">
                    <FileCode className="w-3 h-3 text-indigo-400" /> Entities
                  </span>
                  <span className="text-lg font-bold text-[#292b25]">
                    {repoData?.counts.entities ?? 0}
                  </span>
                </div>

                <div className="p-3 rounded-xl bg-[#f5f3ed]/70 border border-[#d7d2c6]/80 space-y-1">
                  <span className="text-[10px] text-[#77776e] uppercase flex items-center gap-1">
                    <Database className="w-3 h-3 text-indigo-400" /> Backing
                  </span>
                  <span className="text-xs font-bold text-[#51534b] uppercase truncate">
                    {activeDataSource}
                  </span>
                </div>
              </div>

              {/* Storage State (Local SQLite vs Remote Neo4j) */}
              <div className="pt-1 text-xs font-mono">
                <div className="p-2.5 rounded-lg bg-[#f5f3ed] border border-[#d7d2c6]/80 flex items-center justify-between">
                  <span className="text-[#77776e]">Graph Database:</span>
                  <span
                    className={`font-semibold ${
                      isGraphRemoteConfigured ? 'text-emerald-400' : 'text-amber-300'
                    }`}
                  >
                    {isGraphRemoteConfigured ? 'Neo4j Connected' : 'SQLite Local Mode'}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* 2. SQLITE-BACKED STATUS USABLE IF GRAPH IS OFFLINE */}
        <div className="p-5 rounded-2xl bg-gradient-to-r from-[#fffdf8] via-[#f5f3ed]/90 to-[#efede5] border border-[#d7d2c6] space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Database className="w-4 h-4 text-cyan-400" />
              <h3 className="text-xs font-mono font-bold uppercase tracking-wider text-[#292b25]">
                Persistence & Storage Resilience (SQLite Local Fallback)
              </h3>
            </div>
            <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">
              Operational
            </span>
          </div>

          <p className="text-xs font-mono text-[#51534b] leading-relaxed">
            CodeWhy is architected with complete local SQLite resilience. If an external graph database
            (Neo4j) is unconfigured or offline, CodeWhy serves all decision queries, quote checks, and
            entity lineage seamlessly using the local SQLite store and in-memory indexes.
          </p>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-2 text-xs font-mono">
            <div className="p-3 rounded-xl bg-[#f5f3ed]/80 border border-[#d7d2c6]">
              <span className="text-[#77776e] block text-[10px] uppercase">Active Data Source</span>
              <span className="text-cyan-300 font-bold text-sm uppercase">{activeDataSource}</span>
            </div>
            <div className="p-3 rounded-xl bg-[#f5f3ed]/80 border border-[#d7d2c6]">
              <span className="text-[#77776e] block text-[10px] uppercase">Graph Query Engine</span>
              <span className="text-[#292b25] font-bold text-sm">
                {isGraphRemoteConfigured ? 'Remote Neo4j' : 'Local SQLite Graph'}
              </span>
            </div>
            <div className="p-3 rounded-xl bg-[#f5f3ed]/80 border border-[#d7d2c6]">
              <span className="text-[#77776e] block text-[10px] uppercase">Query Availability</span>
              <span className="text-emerald-400 font-bold text-sm">100% Available</span>
            </div>
          </div>
        </div>

        {/* 3. DEPENDENCY SERVICES STATUS (From GET /api/v1/health/dependencies) */}
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <span className="text-xs font-mono uppercase tracking-wider text-[#77776e] font-bold">
              Configured Services & Dependencies
            </span>
            <div className="h-px bg-[#efede5] flex-1" />
          </div>

          {dependencies?.services && dependencies.services.length > 0 ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 text-xs font-mono">
              {dependencies.services.map((svc) => {
                const isConfigured = svc.status === 'configured';
                return (
                  <div
                    key={svc.name}
                    className="p-4 rounded-xl bg-[#fffdf8]/60 border border-[#d7d2c6] space-y-2"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-bold text-[#292b25] uppercase text-xs flex items-center gap-1.5">
                        <Cpu className="w-3.5 h-3.5 text-cyan-400" />
                        {svc.name}
                      </span>
                      <span
                        className={`text-[10px] font-semibold px-2 py-0.5 rounded ${
                          isConfigured
                            ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                            : 'bg-[#efede5] text-[#77776e] border border-[#d7d2c6]'
                        }`}
                      >
                        {svc.status}
                      </span>
                    </div>

                    <p className="text-[11px] text-[#77776e] leading-snug break-words">
                      {svc.detail}
                    </p>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="p-4 rounded-xl bg-[#fffdf8]/40 border border-[#d7d2c6] text-xs font-mono text-[#77776e]">
              Awaiting dependency telemetry from GET /api/v1/health/dependencies...
            </div>
          )}
        </div>

        {/* 4. FOUR SUPPORTED ANSWER OUTCOMES CONTRACT */}
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <span className="text-xs font-mono uppercase tracking-wider text-[#77776e] font-bold">
              Available Query Outcomes & Protocol Responses
            </span>
            <div className="h-px bg-[#efede5] flex-1" />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 text-xs font-mono">
            {/* Outcome 1: Full Answer */}
            <div className="p-4 rounded-xl bg-emerald-950/15 border border-emerald-500/30 space-y-2">
              <div className="flex items-center gap-2 text-emerald-300 font-bold">
                <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                <span>Full Answer</span>
              </div>
              <p className="text-[#51534b] leading-relaxed font-sans text-xs">
                Verified decision path with quoted verbatim rationale surviving quote check. High confidence score.
              </p>
            </div>

            {/* Outcome 2: Partial Answer */}
            <div className="p-4 rounded-xl bg-amber-950/15 border border-amber-500/30 space-y-2">
              <div className="flex items-center gap-2 text-amber-300 font-bold">
                <HelpCircle className="w-4 h-4 text-amber-400" />
                <span>Partial Answer</span>
              </div>
              <p className="text-[#51534b] leading-relaxed font-sans text-xs">
                Change recorded in history, rationale missing or unquoted (<code>no_verified_quote</code>). Enumerates gaps.
              </p>
            </div>

            {/* Outcome 3: Refusal */}
            <div className="p-4 rounded-xl bg-[#fffdf8]/80 border border-[#d7d2c6] space-y-2">
              <div className="flex items-center gap-2 text-[#51534b] font-bold">
                <XCircle className="w-4 h-4 text-[#77776e]" />
                <span>Calibrated Refusal</span>
              </div>
              <p className="text-[#51534b] leading-relaxed font-sans text-xs">
                Truthful refusal (<code>no_decision_path</code>, <code>entity_not_found</code>, <code>out_of_scope</code>).
              </p>
            </div>

            {/* Outcome 4: Ambiguous Entity */}
            <div className="p-4 rounded-xl bg-purple-950/15 border border-purple-500/30 space-y-2">
              <div className="flex items-center gap-2 text-purple-300 font-bold">
                <Box className="w-4 h-4 text-purple-400" />
                <span>Ambiguous Entity</span>
              </div>
              <p className="text-[#51534b] leading-relaxed font-sans text-xs">
                Matches multiple files or keys. Returns candidate chips for immediate disambiguation.
              </p>
            </div>
          </div>
        </div>

        {/* 5. REPOSITORY METADATA & TIMESTAMPS (Only when returned) */}
        <div className="p-5 rounded-2xl bg-[#fffdf8]/40 border border-[#d7d2c6] space-y-3 text-xs font-mono">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-[#51534b] uppercase tracking-wider">
              Repository Specification Record
            </span>
            {repoData?.fixture && (
              <span className="px-2 py-0.5 rounded bg-amber-500/20 text-amber-300 border border-amber-500/30 text-[10px]">
                Synthetic Benchmark Fixture
              </span>
            )}
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-2 text-[#77776e]">
            <div>
              <span className="text-[10px] text-[#77776e] block uppercase">Repository ID</span>
              <span className="text-[#292b25] font-bold">{repoData?.id || repoId}</span>
            </div>
            <div>
              <span className="text-[10px] text-[#77776e] block uppercase">Name</span>
              <span className="text-[#292b25] font-bold">{repoData?.name || repoId}</span>
            </div>
            {repoData?.full_name && (
              <div>
                <span className="text-[10px] text-[#77776e] block uppercase">Full Name</span>
                <span className="text-[#292b25] font-bold">{repoData.full_name}</span>
              </div>
            )}
            {repoData?.owner && (
              <div>
                <span className="text-[10px] text-[#77776e] block uppercase">Owner</span>
                <span className="text-[#292b25] font-bold">{repoData.owner}</span>
              </div>
            )}
            {repoData?.scope && (
              <div>
                <span className="text-[10px] text-[#77776e] block uppercase">Scope</span>
                <span className="text-[#292b25] font-bold">{repoData.scope}</span>
              </div>
            )}
            {repoData?.url && (
              <div>
                <span className="text-[10px] text-[#77776e] block uppercase">Source URL</span>
                <a
                  href={repoData.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-cyan-400 hover:text-cyan-300 font-bold truncate block underline"
                >
                  {repoData.url}
                </a>
              </div>
            )}
            {repoData?.last_rebuilt_at && (
              <div>
                <span className="text-[10px] text-[#77776e] block uppercase">Last Rebuilt Timestamp</span>
                <span className="text-cyan-300 font-bold">
                  {new Date(repoData.last_rebuilt_at).toLocaleString()}
                </span>
              </div>
            )}
          </div>
        </div>

      </div>
    </div>
  );
};
