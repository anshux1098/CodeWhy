import type {
  Repository,
  HealthResponse,
  DependenciesResponse,
  AskRequest,
  AskResponse,
  DecisionListResponse,
  DecisionDetail,
  GraphResponse,
  EntityListResponse,
} from '../types';


export interface GroundedQuestion {
  label: string;
  question: string;
  outcomeType: 'full' | 'partial' | 'refusal' | 'ambiguous';
  tag: string;
  entityId?: string;
}

export const GROUNDED_DEMO_QUESTIONS: Record<string, GroundedQuestion[]> = {
  'urllib3-urllib3': [
    {
      label: 'Demonstrates: RFC 9113 HTTP/2 TLS support',
      question: 'Why was src/urllib3/util/ssl_.py changed for HTTP/2 TLS support?',
      outcomeType: 'full',
      tag: 'Full Answer',
      entityId: 'file:urllib3/urllib3:src/urllib3/util/ssl_.py',
    },
    {
      label: 'Demonstrates: Commit revert supersession',
      question: 'Why was src/urllib3/util/ssl_.py reverted for HTTP/2 TLS?',
      outcomeType: 'full',
      tag: 'Full Answer (Supersedes PR #3456)',
      entityId: 'file:urllib3/urllib3:src/urllib3/util/ssl_.py',
    },
    {
      label: 'Demonstrates: Multi-decision file history',
      question: 'Why was src/urllib3/util/url.py changed?',
      outcomeType: 'full',
      tag: 'Full Answer',
      entityId: 'file:urllib3/urllib3:src/urllib3/util/url.py',
    },
    {
      label: 'Demonstrates: Low score refusal (below similarity threshold)',
      question: 'Why was support for Python 2.6 dropped in urllib3?',
      outcomeType: 'refusal',
      tag: 'Refusal (Low Score)',
      entityId: 'file:urllib3/urllib3:src/urllib3/__init__.py',
    },
    {
      label: 'Demonstrates: Out of scope off-topic refusal',
      question: 'Why does urllib3 use Kubernetes for orchestration?',
      outcomeType: 'refusal',
      tag: 'Refusal (Entity Not Found)',
    },
    {
      label: 'Demonstrates: Non-existent file entity refusal',
      question: 'Why does this code exist?',
      outcomeType: 'refusal',
      tag: 'Refusal (Entity Not Found)',
      entityId: 'file:urllib3/urllib3:does/not/exist.py',
    },
  ],
  'sqlalchemy-alembic': [
    {
      label: 'Demonstrates: SQLite batch operation workaround',
      question: 'Why avoid using CAST(x as JSON) in SQLite batch operations?',
      outcomeType: 'full',
      tag: 'Full Answer',
      entityId: 'file:sqlalchemy/alembic:alembic/operations/batch.py',
    },
    {
      label: 'Demonstrates: Warning caller attribution',
      question: "Why report warnings from the caller's file and line number instead of utils.py?",
      outcomeType: 'full',
      tag: 'Full Answer',
      entityId: 'file:sqlalchemy/alembic:alembic/util/messaging.py',
    },
    {
      label: 'Demonstrates: Asyncio cookbook connection cleanup',
      question: 'Why add engine.dispose() to the asyncio cookbook example?',
      outcomeType: 'full',
      tag: 'Full Answer',
    },
  ],
};

export async function fetchRepositories(): Promise<{ items: Repository[]; isLive: boolean }> {
  const res = await fetch('/api/v1/repositories', {
    headers: { Accept: 'application/json' },
    signal: AbortSignal.timeout(4000),
  });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  const data = await res.json();
  if (!data || !Array.isArray(data.items) || data.items.length === 0) {
    throw new Error('The API returned no repositories.');
  }
  const items: Repository[] = data.items;
  return { items, isLive: true };
}

export async function fetchRepository(repositoryId: string): Promise<Repository | null> {
  const res = await fetch(`/api/v1/repositories/${encodeURIComponent(repositoryId)}`, {
    headers: { Accept: 'application/json' },
    signal: AbortSignal.timeout(4000),
  });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  return await res.json();
}

export async function fetchHealth(): Promise<{ health: HealthResponse | null; latencyMs: number; isConnected: boolean }> {
  const start = performance.now();
  try {
    const res = await fetch('/api/v1/health', {
      headers: { Accept: 'application/json' },
      signal: AbortSignal.timeout(3000),
    });
    const latencyMs = Math.round(performance.now() - start);
    if (!res.ok) {
      return { health: null, latencyMs, isConnected: false };
    }
    const data = await res.json();
    return { health: data, latencyMs, isConnected: true };
  } catch {
    const latencyMs = Math.round(performance.now() - start);
    return { health: null, latencyMs, isConnected: false };
  }
}

export async function fetchDependencies(): Promise<DependenciesResponse | null> {
  try {
    const res = await fetch('/api/v1/health/dependencies', {
      headers: { Accept: 'application/json' },
      signal: AbortSignal.timeout(3000),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export async function askQuestion(
  repositoryId: string,
  request: AskRequest
): Promise<AskResponse> {
  const res = await fetch(`/api/v1/repositories/${encodeURIComponent(repositoryId)}/ask`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify(request),
  });

  if (!res.ok) {
    let errorDetail = `Request failed with status ${res.status}`;
    try {
      const errJson = await res.json();
      if (errJson?.detail) {
        errorDetail = typeof errJson.detail === 'string' ? errJson.detail : JSON.stringify(errJson.detail);
      }
    } catch {
      // ignore json parse error
    }
    throw new Error(errorDetail);
  }

  const data: AskResponse = await res.json();
  return data;
}

export async function fetchRepositoryDecisions(
  repositoryId: string,
  options?: { entity_id?: string; state?: string; limit?: number; offset?: number }
): Promise<DecisionListResponse> {
  const params = new URLSearchParams();
  if (options?.entity_id) params.set('entity_id', options.entity_id);
  if (options?.state) params.set('state', options.state);
  if (options?.limit) params.set('limit', String(options.limit));
  if (options?.offset) params.set('offset', String(options.offset));

  const url = `/api/v1/repositories/${encodeURIComponent(repositoryId)}/decisions${
    params.toString() ? `?${params.toString()}` : ''
  }`;

  const res = await fetch(url, {
    headers: { Accept: 'application/json' },
  });

  if (!res.ok) {
    throw new Error(`Failed to fetch decisions: ${res.statusText}`);
  }

  return await res.json();
}

export async function fetchDecisionDetail(decisionId: string): Promise<DecisionDetail> {
  const res = await fetch(`/api/v1/decisions/${encodeURIComponent(decisionId)}`, {
    headers: { Accept: 'application/json' },
  });

  if (!res.ok) {
    throw new Error(`Failed to fetch decision details: ${res.statusText}`);
  }

  return await res.json();
}

export async function fetchRepositoryGraph(
  repositoryId: string,
  entityId?: string
): Promise<GraphResponse | null> {
  try {
    const url = `/api/v1/repositories/${encodeURIComponent(repositoryId)}/graph${
      entityId ? `?entity_id=${encodeURIComponent(entityId)}` : ''
    }`;
    const res = await fetch(url, {
      headers: { Accept: 'application/json' },
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export async function fetchEntitySearch(
  repositoryId: string,
  q: string
): Promise<EntityListResponse | null> {
  try {
    return await searchRepositoryEntities(repositoryId, q);
  } catch {
    return null;
  }
}

export async function searchRepositoryEntities(
  repositoryId: string,
  q: string
): Promise<EntityListResponse> {
  const url = `/api/v1/repositories/${encodeURIComponent(repositoryId)}/entities?q=${encodeURIComponent(q)}`;
  const res = await fetch(url, {
    headers: { Accept: 'application/json' },
    signal: AbortSignal.timeout(4000),
  });
  if (!res.ok) {
    throw new Error(`Failed to search repository entities: HTTP ${res.status}`);
  }
  return await res.json();
}

export async function fetchRepositoryDecisionHistory(
  repositoryId: string
): Promise<DecisionListResponse> {
  const limit = 200;
  const firstPage = await fetchRepositoryDecisions(repositoryId, { limit, offset: 0 });
  const items = [...firstPage.items];
  let offset = items.length;

  while (offset < firstPage.total) {
    const page = await fetchRepositoryDecisions(repositoryId, { limit, offset });
    if (page.items.length === 0) {
      throw new Error('Decision history pagination stopped before all decisions were loaded');
    }
    items.push(...page.items);
    offset = items.length;
  }

  return { ...firstPage, items, limit, offset: 0 };
}


export type GraphFetchResult =
  | { status: 'ok'; data: GraphResponse }
  | { status: 'offline' }
  | { status: 'not_found' }
  | { status: 'error'; message: string };

export async function fetchRepositoryGraphResult(
  repositoryId: string,
  entityId?: string
): Promise<GraphFetchResult> {
  try {
    const url = `/api/v1/repositories/${encodeURIComponent(repositoryId)}/graph${
      entityId ? `?entity_id=${encodeURIComponent(entityId)}` : ''
    }`;
    const res = await fetch(url, {
      headers: { Accept: 'application/json' },
      signal: AbortSignal.timeout(8000),
    });
    if (res.status === 503) return { status: 'offline' };
    if (res.status === 404) return { status: 'not_found' };
    if (!res.ok) return { status: 'error', message: `HTTP ${res.status}` };
    const data: GraphResponse = await res.json();
    return { status: 'ok', data };
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    if (msg.includes('fetch') || msg.includes('network') || msg.includes('timeout')) {
      return { status: 'offline' };
    }
    return { status: 'error', message: msg };
  }
}


// ─── On-Demand Ingestion API ───────────────────────────────────────────────

export interface IngestJobStatus {
  job_id: string;
  repo: string;
  status: 'queued' | 'cloning' | 'fetching' | 'extracting' | 'building_graph' | 'done' | 'failed';
  phase: string | null;
  progress_pct: number;
  started_at: string;
  finished_at: string | null;
  error: string | null;
  result_repo_id: string | null;
}

export type IngestMode = 'quick' | 'deep';

export async function startIngest(
  repo: string,
  options: { mode?: IngestMode; maxPrs?: number; files?: string[] } = {},
): Promise<IngestJobStatus> {
  const mode = options.mode ?? 'quick';
  const res = await fetch('/api/v1/repositories/ingest', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({
      repo,
      mode,
      ...(options.maxPrs !== undefined ? { max_prs: options.maxPrs } : {}),
      ...(options.files && options.files.length > 0 ? { files: options.files } : {}),
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err?.detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}

export async function fetchIngestStatus(jobId: string): Promise<IngestJobStatus> {
  const res = await fetch(`/api/v1/repositories/ingest/${jobId}`, {
    headers: { Accept: 'application/json' },
    signal: AbortSignal.timeout(5000),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export async function fetchSuggestedPrompts(repositoryId: string, limit = 5): Promise<GroundedQuestion[]> {
  try {
    const res = await fetch(
      `/api/v1/repositories/${encodeURIComponent(repositoryId)}/prompts?limit=${limit}`,
      { headers: { Accept: 'application/json' }, signal: AbortSignal.timeout(5000) },
    );
    if (!res.ok) return [];
    const data = await res.json();
    return Array.isArray(data?.prompts) ? data.prompts : [];
  } catch {
    return [];
  }
}

export interface FileAuditResponse {
  repository_id: string;
  files_checked: number;
  risk_level: 'HIGH' | 'MEDIUM' | 'LOW';
  active_constraints_count: number;
  superseded_or_reverted_count: number;
  decisions: Array<{
    id: string;
    summary: string;
    rationale?: string | null;
    state: string;
    rule?: string | null;
    source_url?: string | null;
    author?: string | null;
    entity_path?: string | null;
  }>;
}

export async function auditRepositoryFiles(
  repositoryId: string,
  files: string[],
): Promise<FileAuditResponse> {
  const res = await fetch(
    `/api/v1/repositories/${encodeURIComponent(repositoryId)}/audit`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ files }),
      signal: AbortSignal.timeout(6000),
    },
  );
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export interface DuelClaim {
  id: string;
  text: string;
  verified: boolean;
  flag: string;
}

export interface HallucinationDuelResponse {
  repository_id: string;
  question: string;
  plain_llm: {
    model_label: string;
    answer: string;
    claims: DuelClaim[];
    unverified_claims_count: number;
    latency_ms: number;
    tokens_used: number;
  };
  codewhy: {
    model_label: string;
    outcome: string;
    reason_code?: string | null;
    answer?: string | null;
    confidence?: string | null;
    citations: Array<{ id: string; quote: string; url?: string | null; author?: string | null }>;
    verified_quotes_count: number;
    latency_ms: number;
    tokens_used: number;
    gate_summary: string;
  };
  verdict: string;
}

export async function runHallucinationDuel(
  repositoryId: string,
  question: string,
  entityId?: string,
): Promise<HallucinationDuelResponse> {
  const res = await fetch(
    `/api/v1/repositories/${encodeURIComponent(repositoryId)}/duel`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ question, ...(entityId ? { entity_id: entityId } : {}) }),
      signal: AbortSignal.timeout(15000),
    },
  );
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export interface BlameLineDecision {
  id: string;
  summary: string;
  state: string;
  date?: string | null;
  rule?: string | null;
  supersedes?: string | null;
  superseded_by?: string | null;
  quote: string;
  source_id: string;
  source_url: string;
  author: string;
}

export interface BlameLineItem {
  line_number: number;
  code: string;
  sha: string;
  author: string;
  summary: string;
  governed: boolean;
  decision?: BlameLineDecision | null;
}

export interface LineBlameResponse {
  repository_id: string;
  path: string;
  total_lines: number;
  governed_decisions_count: number;
  selected_line?: BlameLineItem | null;
  lines: BlameLineItem[];
}

export async function fetchLineBlame(
  repositoryId: string,
  path: string,
  line?: number,
): Promise<LineBlameResponse> {
  const qs = new URLSearchParams({ path, ...(line !== undefined ? { line: String(line) } : {}) });
  const res = await fetch(
    `/api/v1/repositories/${encodeURIComponent(repositoryId)}/blame?${qs.toString()}`,
    { headers: { Accept: 'application/json' }, signal: AbortSignal.timeout(8000) },
  );
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export interface PreflightResponse {
  repository_id: string;
  risk_level: 'HIGH' | 'MEDIUM' | 'LOW';
  risk_badge: 'HIGH RISK' | 'CAUTION' | 'LOW RISK';
  files_checked: string[];
  constants_touched: string[];
  active_constraints_count: number;
  superseded_or_reverted_count: number;
  warnings: Array<{ file: string; severity: string; message: string }>;
  hotspots: Array<{
    file: string;
    risk_level: 'HIGH' | 'MEDIUM' | 'LOW';
    risk_badge: string;
    active_count: number;
    reverted_or_superseded_count: number;
    top_decision: string;
  }>;
  constant_timeline: Array<{
    name: string;
    file: string;
    transitions: Array<{
      old_value?: string | null;
      new_value: string;
      source_id: string;
      date: string;
      author: string;
      summary?: string;
    }>;
  }>;
}

export async function runPreflightCheck(
  repositoryId: string,
  diff = '',
  files: string[] = [],
): Promise<PreflightResponse> {
  const res = await fetch(
    `/api/v1/repositories/${encodeURIComponent(repositoryId)}/preflight`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ diff, files }),
      signal: AbortSignal.timeout(8000),
    },
  );
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export interface AdrExportResponse {
  repository_id: string;
  full_name: string;
  total_adrs: number;
  files: Array<{ path: string; title: string; state: string; date: string; content: string }>;
  combined_markdown: string;
}

export async function exportRepositoryAdrs(repositoryId: string): Promise<AdrExportResponse> {
  const res = await fetch(
    `/api/v1/repositories/${encodeURIComponent(repositoryId)}/adrs/export`,
    { headers: { Accept: 'application/json' }, signal: AbortSignal.timeout(8000) },
  );
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export interface TrustScoreboardResponse {
  citation_precision_pct: number;
  refusal_accuracy_pct: number;
  hallucinations_blocked: number;
  rejected_quotes_count: number;
  unverified_decisions_blocked: number;
  verified_decisions_total: number;
  noisy_prs_filtered: number;
  p50_latency_ms: number;
  p95_latency_ms: number;
  avg_tokens_per_answer: number;
  tokens_on_refusal: number;
  benchmark_cases: Array<{
    question: string;
    expected_outcome: string;
    actual_outcome: string;
    reason_code?: string | null;
    verified_citations: number;
    tokens_used: number;
    latency_ms: number;
    passed: boolean;
  }>;
}

export async function fetchTrustScoreboard(): Promise<TrustScoreboardResponse> {
  const res = await fetch('/api/v1/eval/scoreboard', {
    headers: { Accept: 'application/json' },
    signal: AbortSignal.timeout(6000),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export interface LiveExtractionPreviewResponse {
  status: string;
  injection_flagged: boolean;
  injection_reasons: string[];
  decision?: { summary: string; rationale: string; constraint_rule?: string | null } | null;
  verified_quotes: Array<{ quote: string; verified: boolean; classification?: string }>;
  rejected_quotes: Array<{ quote: string; reason: string }>;
}

export async function previewLiveExtraction(
  text: string,
  title = 'PR #42: Enforce strict timeout boundary',
): Promise<LiveExtractionPreviewResponse> {
  const res = await fetch('/api/v1/extract/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ text, title, source_type: 'pr' }),
    signal: AbortSignal.timeout(15000),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export interface RepositoryCypherSummaryResponse {
  repository_id: string;
  full_name: string;
  overview: string;
  cypher_query: string;
  stats: {
    total_decisions: number;
    active_decisions: number;
    superseded_or_reverted: number;
    tracked_entities: number;
    pull_requests: number;
    commits: number;
  };
  key_active_decisions: Array<{ id: string; summary: string; rule?: string | null; date?: string | null; entities: string[] }>;
  historical_reverts_and_pitfalls: Array<{ id: string; summary: string; state: string; date?: string | null; entities: string[] }>;
  hotspot_entities: Array<{ path: string; decision_count: number }>;
  top_maintainers: Array<{ login: string; role: string }>;
}

export async function fetchRepositoryCypherSummary(
  repositoryId: string,
): Promise<RepositoryCypherSummaryResponse> {
  const res = await fetch(
    `/api/v1/repositories/${encodeURIComponent(repositoryId)}/summary`,
    { headers: { Accept: 'application/json' }, signal: AbortSignal.timeout(8000) },
  );
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export interface FeatureImpactAdvisorResponse {
  repository_id: string;
  mode: 'add' | 'remove';
  feature: string;
  already_exists: boolean;
  recommendation: string;
  cypher_query: string;
  existing_history: Array<{
    decision_id: string;
    summary: string;
    state: string;
    date: string;
    how_added: string;
    source_id: string;
    source_url: string;
    author: string;
    quote: string;
  }>;
  affected_if_added: Array<{ path: string; risk_badge: string; reason: string }>;
  related_pull_requests: Array<{
    source_id: string;
    url: string;
    author: string;
    date: string;
    summary: string;
    state: string;
  }>;
  required_co_changes: Array<{ path: string; reason: string }>;
  what_could_go_wrong: Array<{
    decision_id: string;
    state: string;
    severity: string;
    risk_title: string;
    explanation: string;
  }>;
  supporting_evidence: Array<{
    source_id: string;
    source_url: string;
    author: string;
    date: string;
    quote: string;
    claim: string;
  }>;
  who_to_ask: string[];
}

export async function runFeatureImpactAdvisor(
  repositoryId: string,
  mode: 'add' | 'remove',
  feature: string,
): Promise<FeatureImpactAdvisorResponse> {
  const res = await fetch(
    `/api/v1/repositories/${encodeURIComponent(repositoryId)}/impact`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ mode, feature }),
      signal: AbortSignal.timeout(8000),
    },
  );
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}
