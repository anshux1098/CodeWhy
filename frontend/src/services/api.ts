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

export const FALLBACK_REPOSITORIES: Repository[] = [
  {
    id: 'acme-netclient',
    name: 'netclient',
    full_name: 'acme/netclient',
    owner: 'acme',
    url: 'https://github.invalid/acme/netclient',
    scope: 'HTTP & Resilient Networking Client',
    counts: {
      decisions: 5,
      entities: 6,
      pull_requests: 5,
      commits: 9,
    },
    fixture: true,
  },
  {
    id: 'urllib3-urllib3',
    name: 'urllib3/urllib3',
    full_name: 'urllib3/urllib3',
    owner: 'urllib3',
    url: 'https://github.com/urllib3/urllib3',
    scope: 'HTTP Client & Connection Pool Engine',
    counts: {
      decisions: 48,
      entities: 142,
      pull_requests: 120,
      commits: 340,
    },
    verified_decisions: 42,
    prs_fetched: 120,
    sources_analyzed: 95,
    last_rebuilt_at: '2025-03-01T14:10:00Z',
    fixture: false,
  },
  {
    id: 'sqlalchemy-alembic',
    name: 'sqlalchemy/alembic',
    full_name: 'sqlalchemy/alembic',
    owner: 'sqlalchemy',
    url: 'https://github.com/sqlalchemy/alembic',
    scope: 'Database Migration Tooling',
    counts: {
      decisions: 0,
      entities: 0,
      pull_requests: 0,
      commits: 0,
    },
    fixture: true,
  },
];

export interface GroundedQuestion {
  label: string;
  question: string;
  outcomeType: 'full' | 'partial' | 'refusal' | 'ambiguous';
  tag: string;
  entityId?: string;
}

export const GROUNDED_DEMO_QUESTIONS: Record<string, GroundedQuestion[]> = {
  'acme-netclient': [
    {
      label: 'Why is MAX_RETRIES 3?',
      question: 'Why is MAX_RETRIES 3?',
      outcomeType: 'full',
      tag: 'Full Answer',
      entityId: 'key:MAX_RETRIES',
    },
    {
      label: 'Why did netclient move the helper?',
      question: 'Why did the netclient package move that helper into its own module?',
      outcomeType: 'partial',
      tag: 'Partial (No Quote)',
      entityId: 'module:netclient',
    },
    {
      label: 'Why is _PAD_BYTES 17?',
      question: 'Why is _PAD_BYTES 17?',
      outcomeType: 'refusal',
      tag: 'Refusal (No Path)',
      entityId: 'key:_PAD_BYTES',
    },
    {
      label: 'Why is retry set this way?',
      question: 'Why is retry set this way?',
      outcomeType: 'ambiguous',
      tag: 'Ambiguous Entity',
    },
    {
      label: 'Why is TIMEOUT_MS 500?',
      question: 'Why is TIMEOUT_MS 500?',
      outcomeType: 'refusal',
      tag: 'Refusal (Entity Not Found)',
    },
    {
      label: 'Why was the team late for the demo?',
      question: 'Why was the team late for the demo?',
      outcomeType: 'refusal',
      tag: 'Refusal (Out of Scope)',
    },
  ],
  'urllib3-urllib3': [
    {
      label: 'Why was ssl_.py changed for HTTP/2?',
      question: 'Why was src/urllib3/util/ssl_.py changed for HTTP/2 TLS support?',
      outcomeType: 'full',
      tag: 'Full Answer (RFC 9113)',
      entityId: 'file:urllib3/urllib3:src/urllib3/util/ssl_.py',
    },
    {
      label: 'Why was Python 2.6 support dropped?',
      question: 'Why was support for Python 2.6 dropped in urllib3?',
      outcomeType: 'full',
      tag: 'Full Answer (PR #1429)',
      entityId: 'file:urllib3/urllib3:src/urllib3/__init__.py',
    },
    {
      label: 'Why was HTTP/2 TLS reverted?',
      question: 'Why was src/urllib3/util/ssl_.py reverted for HTTP/2 TLS?',
      outcomeType: 'full',
      tag: 'Superseded (PR #3466)',
      entityId: 'file:urllib3/urllib3:src/urllib3/util/ssl_.py',
    },
    {
      label: 'Why was url.py changed?',
      question: 'Why was src/urllib3/util/url.py changed?',
      outcomeType: 'refusal',
      tag: 'Refusal (Thin Score)',
      entityId: 'file:urllib3/urllib3:src/urllib3/util/url.py',
    },
    {
      label: 'Why does urllib3 use Kubernetes?',
      question: 'Why does urllib3 use Kubernetes for orchestration?',
      outcomeType: 'refusal',
      tag: 'Refusal (Entity Not Found)',
    },
    {
      label: 'Why does this code exist?',
      question: 'Why does this code exist?',
      outcomeType: 'refusal',
      tag: 'Refusal (Unknown Entity)',
      entityId: 'file:urllib3/urllib3:does/not/exist.py',
    },
  ],
  'sqlalchemy-alembic': [
    {
      label: 'Why avoid CAST(x as JSON) in SQLite?',
      question: 'Why avoid using CAST(x as JSON) in SQLite batch operations?',
      outcomeType: 'full',
      tag: 'Full Answer (PR #698)',
      entityId: 'file:sqlalchemy/alembic:alembic/operations/batch.py',
    },
    {
      label: 'Why report warnings from caller line?',
      question: "Why report warnings from the caller's file and line number instead of utils.py?",
      outcomeType: 'full',
      tag: 'Full Answer (PR #578)',
      entityId: 'file:sqlalchemy/alembic:alembic/util/messaging.py',
    },
    {
      label: 'Why add engine.dispose() to asyncio?',
      question: 'Why add engine.dispose() to the asyncio cookbook example?',
      outcomeType: 'full',
      tag: 'Full Answer (PR #973)',
    },
  ],
};

export async function fetchRepositories(): Promise<{ items: Repository[]; isLive: boolean }> {
  try {
    const res = await fetch('/api/v1/repositories', {
      headers: { Accept: 'application/json' },
      signal: AbortSignal.timeout(4000),
    });
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }
    const data = await res.json();
    if (data && Array.isArray(data.items) && data.items.length > 0) {
      const targetRepositories = FALLBACK_REPOSITORIES.filter((repo) =>
        ['urllib3-urllib3', 'sqlalchemy-alembic'].includes(repo.id)
      );
      const items: Repository[] = data.items
        .filter((repo: Repository) =>
          repo.id.toLowerCase() !== 'hynek-structlog'
          && repo.full_name?.toLowerCase() !== 'hynek/structlog'
        )
        .map((repo: Repository) => {
          const target = targetRepositories.find((candidate) => candidate.id === repo.id);
          return target
            ? {
                ...target,
                ...repo,
                name: target.full_name,
                full_name: target.full_name,
                owner: target.owner,
                url: repo.url || target.url,
              }
            : repo;
        });
      for (const target of targetRepositories) {
        if (!items.some((repo) =>
          repo.id === target.id || repo.full_name?.toLowerCase() === target.full_name?.toLowerCase()
        )) {
          items.push(target);
        }
      }
      return { items, isLive: true };
    }
    return { items: FALLBACK_REPOSITORIES, isLive: true };
  } catch {
    return { items: FALLBACK_REPOSITORIES, isLive: false };
  }
}

export async function fetchRepository(repositoryId: string): Promise<Repository | null> {
  try {
    const res = await fetch(`/api/v1/repositories/${encodeURIComponent(repositoryId)}`, {
      headers: { Accept: 'application/json' },
      signal: AbortSignal.timeout(4000),
    });
    if (!res.ok) {
      const fallback = FALLBACK_REPOSITORIES.find((r) => r.id === repositoryId);
      return fallback || null;
    }
    return await res.json();
  } catch {
    const fallback = FALLBACK_REPOSITORIES.find((r) => r.id === repositoryId);
    return fallback || null;
  }
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
