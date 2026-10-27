export type DecisionState = 'ACTIVE' | 'SUPERSEDED' | 'REJECTED' | 'UNRESOLVED';

export type Outcome = 'full' | 'partial' | 'refusal';

export type ReasonCode =
  | 'entity_not_found'
  | 'ambiguous_entity'
  | 'out_of_scope'
  | 'no_decision_path'
  | 'no_verified_quote'
  | 'low_score';

export interface RepositoryCounts {
  decisions: number;
  entities: number;
  pull_requests: number;
  commits: number;
}

export interface Repository {
  id: string;
  name: string;
  url: string;
  owner?: string | null;
  full_name?: string | null;
  scope?: string | null;
  counts: RepositoryCounts;
  prs_fetched?: number | null;
  sources_analyzed?: number | null;
  prs_noise_skipped?: number | null;
  verified_decisions?: number | null;
  last_rebuilt_at?: string | null;
  fixture?: boolean;
}

export interface SourceRef {
  type: 'PullRequest' | 'Issue' | 'Document' | 'Commit' | string;
  number?: number | null;
  url?: string | null;
}

export interface Citation {
  id: string;
  decision_id: string;
  kind: 'SOURCE' | 'INFERRED' | string;
  quote: string;
  source_url: string;
  source_type: string;
  author?: string | null;
  timestamp?: string | null;
}

export interface Decision {
  id: string;
  summary: string;
  rationale?: string | null;
  state: DecisionState;
  recorded_at?: string | null;
  effective_at?: string | null;
  ended_at?: string | null;
  source: SourceRef;
  supersedes: string[];
  superseded_by: string[];
  rule?: string | null;
  probable_superseded_by?: string[];
  conflicts_with?: string[];
  reaffirms?: string[];
}

export interface DecisionListItem {
  id: string;
  summary: string;
  state: DecisionState;
  date?: string | null;
  source_url?: string | null;
  entities: string[];
  supersedes: string[];
  superseded_by: string[];
  rule?: string | null;
}

export interface DecisionListResponse {
  items: DecisionListItem[];
  total: number;
  limit: number;
  offset: number;
  fixture: boolean;
}

export interface DecisionDetail extends Decision {
  citations: Citation[];
  evidence_gaps: string[];
  fixture: boolean;
}

export interface ConfidenceSignals {
  directness: number;
  provenance: number;
  agreement: number;
  relevance: number;
  temporal_consistency: number;
  contradiction: 0.0 | 1.0 | number;
  [key: string]: number;
}

export interface ConfidenceScore {
  score: number;
  label: 'HIGH' | 'MEDIUM' | 'LOW';
  signals: ConfidenceSignals;
}

export interface Entity {
  id: string;
  type: 'File' | 'Module' | 'ConfigKey' | string;
  label: string;
  path?: string;
  decision_count?: number;
}

export interface EntityListResponse {
  entities: Entity[];
  query: string;
  fixture: boolean;
}

export interface Candidate {
  id: string;
  type: string;
  label: string;
  path?: string;
}

export interface WhoToAsk {
  login: string;
  reason: 'author' | 'reviewer' | 'recent_contributor' | string;
  active: boolean;
}

export interface AskRequest {
  question: string;
  entity_id?: string | null;
}

export interface AskResponse {
  outcome: Outcome;
  reason_code?: ReasonCode | string | null;
  answer?: string | null;
  entity?: Entity | null;
  candidates: Candidate[];
  confidence?: ConfidenceScore | null;
  decisions: Decision[];
  citations: Citation[];
  evidence_gaps: string[];
  who_to_ask: WhoToAsk[];
  code_differs_from_latest?: boolean | null;
  fixture: boolean;
}

export interface QuestionContext {
  repositoryId: string;
  question: string;
  response: AskResponse;
}

export interface GraphNode {
  id: string;
  label: string;
  type: string;
  props: Record<string, any>;
}

export interface GraphEdge {
  source: string;
  target: string;
  type: string;
  rule?: string | null;
  props: Record<string, any>;
}

export interface GraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
  truncated: boolean;
  fixture: boolean;
}

export interface DependencyStatus {
  name: string;
  status: 'configured' | 'not configured' | string;
  detail: string;
}

export interface DependenciesResponse {
  services: DependencyStatus[];
  data_source: string;
}

export interface HealthResponse {
  status: string;
  version: string;
  app_version?: string;
  data_source: string;
  database?: string;
  timestamp?: string;
  dependencies?: Record<string, string>;
}
