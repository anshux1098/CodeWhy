import React, {
  useState,
  useEffect,
  useCallback,
  useMemo,
} from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  MarkerType,
  Position,
  Handle,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type NodeProps,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import dagre from '@dagrejs/dagre';
import type {
  Repository,
  GraphResponse,
  GraphNode as RawGraphNode,
  Entity,
  QuestionContext,
} from '../types';
import {
  fetchRepositoryGraphResult,
  fetchEntitySearch,
  type GraphFetchResult,
} from '../services/api';
import { DecisionDrawer } from './DecisionDrawer';
import {
  GitFork,
  Layers,
  Search,
  Filter,
  X,
  Clock,
  CheckCircle2,
  XCircle,
  HelpCircle,
  RotateCcw,
  FileCode,
  Folder,
  Key,
  GitCommit,
  GitPullRequest,
  User,
  FileText,
  AlertTriangle,
  Table,
  Workflow,
  Eye,
  EyeOff,
  Database,
  GitBranch,
} from 'lucide-react';

// Dimensions for dagre layout
const NODE_WIDTH = 240;
const NODE_HEIGHT = 72;

// Custom Node Data
interface CustomNodeData extends Record<string, unknown> {
  raw: RawGraphNode;
  isSelected: boolean;
  onSelect: (node: RawGraphNode) => void;
  onOpenDecision?: (decisionId: string) => void;
}

// Custom React Flow Node Component
const CodeWhyGraphNode: React.FC<NodeProps<Node<CustomNodeData>>> = ({ data, selected }) => {
  const node = data.raw;
  const isSelected = selected || data.isSelected;

  // Render node icon and styling according to type and decision state
  const renderVisuals = () => {
    switch (node.type) {
      case 'Decision': {
        const state = (node.props?.state || 'ACTIVE').toUpperCase();
        const badgeText = state === 'ACTIVE'
          ? 'Active'
          : state === 'SUPERSEDED'
            ? 'Superseded'
            : state === 'REJECTED'
              ? 'Rejected'
              : 'Unresolved';
        const icon = state === 'ACTIVE'
          ? <CheckCircle2 className="w-3.5 h-3.5 text-amber-500 shrink-0" />
          : state === 'SUPERSEDED'
            ? <Clock className="w-3.5 h-3.5 text-amber-500 shrink-0" />
            : state === 'REJECTED'
              ? <XCircle className="w-3.5 h-3.5 text-amber-500 shrink-0" />
              : <HelpCircle className="w-3.5 h-3.5 text-amber-500 shrink-0" />;
        return {
          borderColor: isSelected ? 'border-amber-400 ring-2 ring-amber-400/40' : 'border-amber-500/60 hover:border-amber-400',
          bg: 'bg-[#0a0410]',
          badgeBg: 'bg-amber-500/15 text-amber-500 border-amber-500/40',
          badgeText,
          icon,
        };
      }
      case 'CodeEntity': {
        const entType = node.props?.entity_type || 'File';
        if (entType === 'Module') {
          return {
            borderColor: isSelected ? 'border-emerald-400 ring-2 ring-emerald-400/40' : 'border-emerald-500/60 hover:border-emerald-400',
            bg: 'bg-[#0a0410]',
            badgeBg: 'bg-emerald-500/15 text-emerald-500 border-emerald-500/40',
            badgeText: 'Module',
            icon: <Folder className="w-3.5 h-3.5 text-emerald-500 shrink-0" />,
          };
        }
        if (entType === 'ConfigKey') {
          return {
            borderColor: isSelected ? 'border-amber-400 ring-2 ring-amber-400/40' : 'border-amber-500/50 hover:border-amber-400',
            bg: 'bg-[#0a0410]',
            badgeBg: 'bg-amber-500/15 text-amber-400 border-amber-500/40',
            badgeText: 'ConfigKey',
            icon: <Key className="w-3.5 h-3.5 text-amber-400 shrink-0" />,
          };
        }
        return {
          borderColor: isSelected ? 'border-emerald-400 ring-2 ring-emerald-400/40' : 'border-emerald-500/60 hover:border-emerald-400',
          bg: 'bg-[#0a0410]',
          badgeBg: 'bg-emerald-500/15 text-emerald-500 border-emerald-500/40',
          badgeText: 'File',
          icon: <FileCode className="w-3.5 h-3.5 text-emerald-500 shrink-0" />,
        };
      }
      case 'Commit':
        return {
          borderColor: isSelected ? 'border-purple-400 ring-2 ring-purple-400/40' : 'border-purple-500/60 hover:border-purple-400',
          bg: 'bg-[#0a0410]',
          badgeBg: 'bg-purple-500/15 text-purple-400 border-purple-500/40',
          badgeText: 'Commit',
          icon: <GitCommit className="w-3.5 h-3.5 text-purple-400 shrink-0" />,
        };
      case 'Repository':
        return {
          borderColor: isSelected ? 'border-amber-400 ring-2 ring-amber-400/40' : 'border-amber-500/60 hover:border-amber-400',
          bg: 'bg-[#0a0410]',
          badgeBg: 'bg-amber-500/15 text-amber-400 border-amber-500/40',
          badgeText: 'Repository',
          icon: <GitBranch className="w-3.5 h-3.5 text-amber-400 shrink-0" />,
        };
      case 'PullRequest':
        return {
          borderColor: isSelected ? 'border-amber-400 ring-2 ring-amber-400/40' : 'border-amber-500/50 hover:border-amber-400',
          bg: 'bg-[#0a0410]',
          badgeBg: 'bg-purple-500/15 text-purple-500 border-purple-500/40',
          badgeText: node.props?.merged === false ? 'PR (Open)' : 'PR',
          icon: <GitPullRequest className="w-3.5 h-3.5 text-purple-500 shrink-0" />,
        };
      case 'Evidence':
        return {
          borderColor: isSelected ? 'border-emerald-400 ring-2 ring-emerald-400/40' : 'border-emerald-500/50 hover:border-emerald-400',
          bg: 'bg-[#0a0410]',
          badgeBg: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/40',
          badgeText: 'Evidence',
          icon: <FileText className="w-3.5 h-3.5 text-emerald-400 shrink-0" />,
        };
      case 'Person':
        return {
          borderColor: isSelected ? 'border-rose-400 ring-2 ring-rose-400/40' : 'border-rose-500/60 hover:border-rose-400',
          bg: 'bg-[#0a0410]',
          badgeBg: 'bg-rose-500/15 text-rose-400 border-rose-500/40',
          badgeText: 'Person',
          icon: <User className="w-3.5 h-3.5 text-rose-400 shrink-0" />,
        };
      default:
        return {
          borderColor: isSelected ? 'border-slate-400 ring-2 ring-slate-400/40' : 'border-[#d7d2c6] hover:border-slate-500',
          bg: 'bg-[#fffdf8]',
          badgeBg: 'bg-[#efede5] text-[#51534b] border-[#d7d2c6]',
          badgeText: node.type,
          icon: <Workflow className="w-3.5 h-3.5 text-[#77776e] shrink-0" />,
        };
    }
  };

  const style = renderVisuals();

  return (
    <div
      onClick={() => data.onSelect(node)}
      className={`w-[240px] px-3.5 py-2.5 rounded-xl border ${style.borderColor} ${style.bg} shadow-lg transition-all cursor-pointer select-none group text-left`}
    >
      <Handle type="target" position={Position.Top} className="!w-2 !h-2 !bg-[#0a1424] !border-[#3b82f6]" />
      
      <div className="flex items-center justify-between gap-2 mb-1">
        <span className={`text-[10px] font-mono px-2 py-0.5 rounded-md border font-semibold flex items-center gap-1 ${style.badgeBg}`}>
          {style.icon}
          <span>{style.badgeText}</span>
        </span>

        <span className="text-[10px] font-mono text-[#77776e] truncate max-w-[80px]" title={node.id}>
          {node.id.replace(/^(dec_|file:|key:|module:|person:|pr:|ev:)/, '')}
        </span>
      </div>

      <div       className="text-xs font-semibold font-mono text-[#292b25] truncate group-hover:text-amber-400 transition-colors" title={node.label}>
        {node.label}
      </div>

      {node.props?.path && (
        <div className="text-[10px] font-mono text-[#77776e] truncate mt-0.5" title={node.props.path}>
          {node.props.path}
        </div>
      )}

      {node.props?.rule && (
        <div className="mt-1 text-[9px] font-mono px-1.5 py-0.2 rounded bg-amber-500/10 text-amber-800 border border-amber-500/30 truncate inline-block">
          Rule: {node.props.rule}
        </div>
      )}

      <Handle type="source" position={Position.Bottom} className="!w-2 !h-2 !bg-[#0a1424] !border-[#3b82f6]" />
    </div>
  );
};

const nodeTypes = {
  customNode: CodeWhyGraphNode,
};

interface GraphExplorerViewProps {
  selectedRepo: Repository | null;
  questionContext: QuestionContext | null;
  onAskQuestion: () => void;
}

export const GraphExplorerView: React.FC<GraphExplorerViewProps> = ({
  selectedRepo,
  questionContext,
  onAskQuestion,
}) => {
  const [graphData, setGraphData] = useState<GraphResponse | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isGraphOffline, setIsGraphOffline] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Active focal entity (if bounded subgraph)
  const [focusSelection, setFocusSelection] = useState<{
    questionContext: QuestionContext;
    entityId: string;
  } | null>(null);

  // Search input for entities
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [searchResults, setSearchResults] = useState<Entity[]>([]);
  const [isSearching, setIsSearching] = useState<boolean>(false);
  const [isSearchOpen, setIsSearchOpen] = useState<boolean>(false);

  // View mode: Visual Graph vs Accessible List View
  const [viewMode, setViewMode] = useState<'graph' | 'list'>('graph');

  // Selected node for detail drawer/panel
  const [selectedNode, setSelectedNode] = useState<RawGraphNode | null>(null);
  const [activeDecisionDrawerId, setActiveDecisionDrawerId] = useState<string | null>(null);

  // Filters (Evidence and Person hidden by default as specified!)
  const [filters, setFilters] = useState({
    Repository: true,
    CodeEntity: true,
    Decision: true,
    PullRequest: true,
    Evidence: false, // Hidden by default
    Person: false,   // Hidden by default
  });

  // Simulated test states toggle
  const [simulateOffline, setSimulateOffline] = useState(false);
  const [simulateTruncated, setSimulateTruncated] = useState(false);

  // Resolve active repo ID
  const urlMatch = typeof window !== 'undefined'
    ? window.location.pathname.match(/\/r\/([^/]+)/)
    : null;
  const repoId = selectedRepo?.id || (urlMatch ? decodeURIComponent(urlMatch[1]) : 'acme-netclient');
  const activeQuestion = questionContext?.repositoryId === repoId ? questionContext : null;
  const focusEntityId = activeQuestion
    ? focusSelection?.questionContext === activeQuestion
      ? focusSelection.entityId
      : activeQuestion.response.entity?.id ?? null
    : null;
  const setFocusEntityId = (entityId: string | null) => {
    if (entityId && activeQuestion) {
      setFocusSelection({ questionContext: activeQuestion, entityId });
    } else {
      setFocusSelection(null);
    }
  };

  // Load graph data
  const loadGraph = useCallback(async (targetRepoId: string, focalEntity?: string | null) => {
    setIsLoading(true);
    setErrorMessage(null);

    // If simulated offline
    if (simulateOffline) {
      setIsGraphOffline(true);
      setIsLoading(false);
      return;
    }

    const result: GraphFetchResult = await fetchRepositoryGraphResult(targetRepoId, focalEntity || undefined);

    if (result.status === 'offline') {
      setIsGraphOffline(true);
      setGraphData(null);
    } else if (result.status === 'not_found') {
      setIsGraphOffline(false);
      setErrorMessage(`Repository or entity not found in graph`);
      setGraphData(null);
    } else if (result.status === 'error') {
      setIsGraphOffline(false);
      setErrorMessage(result.message);
      setGraphData(null);
    } else {
      setIsGraphOffline(false);
      let data = result.data;
      if (simulateTruncated) {
        data = { ...data, truncated: true };
      }
      setGraphData(data);
    }

    setIsLoading(false);
  }, [simulateOffline, simulateTruncated]);

  // Load only the focused subgraph associated with the latest question.
  useEffect(() => {
    if (!activeQuestion) {
      setGraphData(null);
      setIsGraphOffline(false);
      setErrorMessage(null);
      setIsLoading(false);
      return;
    }
    if (!focusEntityId) {
      setGraphData(null);
      setIsGraphOffline(false);
      setErrorMessage(null);
      setIsLoading(false);
      return;
    }
    loadGraph(repoId, focusEntityId);
  }, [repoId, activeQuestion, focusEntityId, loadGraph]);

  // Debounced search for entities via GET /api/v1/repositories/{id}/entities?q=...
  useEffect(() => {
    if (!searchQuery.trim() || searchQuery.length < 1) {
      setSearchResults([]);
      setIsSearching(false);
      return;
    }

    const timer = setTimeout(async () => {
      setIsSearching(true);
      const res = await fetchEntitySearch(repoId, searchQuery.trim());
      if (res && res.entities) {
        setSearchResults(res.entities);
      } else {
        setSearchResults([]);
      }
      setIsSearching(false);
    }, 250);

    return () => clearTimeout(timer);
  }, [searchQuery, repoId]);

  // Filter nodes based on node-type checkboxes
  const visibleNodesList = useMemo(() => {
    if (!graphData?.nodes) return [];
    return graphData.nodes.filter((node) => {
      const typeKey = node.type as keyof typeof filters;
      if (filters[typeKey] !== undefined) {
        return filters[typeKey];
      }
      return true;
    });
  }, [graphData, filters]);

  const visibleNodeIds = useMemo(() => {
    return new Set(visibleNodesList.map((n) => n.id));
  }, [visibleNodesList]);

  // Filter edges: only connect between currently visible nodes!
  const visibleEdgesList = useMemo(() => {
    if (!graphData?.edges) return [];
    return graphData.edges.filter(
      (edge) => visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target)
    );
  }, [graphData, visibleNodeIds]);

  // Stable Dagre Layout Computation
  const { layoutNodes, layoutEdges } = useMemo(() => {
    if (visibleNodesList.length === 0) {
      return { layoutNodes: [], layoutEdges: [] };
    }

    const g = new dagre.graphlib.Graph();
    g.setDefaultEdgeLabel(() => ({}));
    g.setGraph({
      rankdir: 'TB',
      nodesep: visibleNodesList.length > 30 ? 90 : 60,
      ranksep: visibleNodesList.length > 30 ? 120 : 90,
      edgesep: visibleNodesList.length > 30 ? 40 : 30,
      marginx: 30,
      marginy: 30,
    });

    // Deterministic sort of nodes by id to guarantee stable layout across re-renders
    const sortedNodes = [...visibleNodesList].sort((a, b) => a.id.localeCompare(b.id));
    const sortedEdges = [...visibleEdgesList].sort((a, b) =>
      `${a.source}->${a.target}:${a.type}`.localeCompare(`${b.source}->${b.target}:${b.type}`)
    );

    sortedNodes.forEach((node) => {
      g.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
    });

    sortedEdges.forEach((edge) => {
      g.setEdge(edge.source, edge.target);
    });

    dagre.layout(g);

    const rfNodes: Node<CustomNodeData>[] = sortedNodes.map((node) => {
      const pos = g.node(node.id);
      return {
        id: node.id,
        type: 'customNode',
        position: {
          x: pos ? pos.x - NODE_WIDTH / 2 : 0,
          y: pos ? pos.y - NODE_HEIGHT / 2 : 0,
        },
        data: {
          raw: node,
          isSelected: selectedNode?.id === node.id,
          onSelect: (n) => setSelectedNode(n),
          onOpenDecision: (decId) => setActiveDecisionDrawerId(decId),
        },
      };
    });

    const rfEdges: Edge[] = sortedEdges.map((edge, idx) => {
      let strokeColor = 'var(--text-subtle)';
      let isDashed = false;

      if (edge.type === 'SUPERSEDES') {
        strokeColor = 'var(--warning)';
        isDashed = true;
      } else if (edge.type === 'GOVERNS') {
        strokeColor = 'var(--accent)';
      } else if (edge.type === 'DECIDED_IN') {
        strokeColor = 'var(--text-muted)';
      } else if (edge.type === 'SUPPORTED_BY') {
        strokeColor = 'var(--accent)';
      } else if (edge.type === 'AUTHORED' || edge.type === 'REVIEWED') {
        strokeColor = 'var(--text-subtle)';
      }

      const edgeLabel = edge.rule ? `${edge.type} (${edge.rule})` : edge.type;

      return {
        id: `e-${edge.source}-${edge.target}-${idx}`,
        source: edge.source,
        target: edge.target,
        type: 'smoothstep',
        animated: edge.type === 'SUPERSEDES',
        label: edge.type === 'SUPERSEDES' || edge.rule ? edgeLabel : undefined,
        labelStyle: {
          fill: 'var(--text-muted)',
          fontSize: 9,
          fontFamily: 'var(--font-mono)',
          fontWeight: 600,
        },
        labelBgStyle: {
          fill: 'var(--surface)',
          fillOpacity: 0.85,
        },
        labelBgPadding: [4, 2],
        labelBgBorderRadius: 4,
        style: {
          stroke: strokeColor,
          strokeWidth: isDashed ? 2 : 1.5,
          strokeDasharray: isDashed ? '5,5' : undefined,
        },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          width: 14,
          height: 14,
          color: strokeColor,
        },
      };
    });

    return { layoutNodes: rfNodes, layoutEdges: rfEdges };
  }, [visibleNodesList, visibleEdgesList, selectedNode]);

  const [nodes, setNodes, onNodesChange] = useNodesState<Node<CustomNodeData>>(layoutNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>(layoutEdges);

  // Sync React Flow nodes/edges when layout updates
  useEffect(() => {
    setNodes(layoutNodes);
    setEdges(layoutEdges);
  }, [layoutNodes, layoutEdges, setNodes, setEdges]);

  // Toggle filter
  const toggleFilter = (key: keyof typeof filters) => {
    setFilters((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  // Connected edges for the selected node detail panel
  const connectedDetails = useMemo(() => {
    if (!selectedNode || !graphData?.edges) return { inbound: [], outbound: [] };
    const inbound = graphData.edges.filter((e) => e.target === selectedNode.id);
    const outbound = graphData.edges.filter((e) => e.source === selectedNode.id);
    return { inbound, outbound };
  }, [selectedNode, graphData]);

  return (
    <div className="flex flex-col h-[calc(100vh-5rem)] bg-[#f5f3ed] w-full text-[#292b25] overflow-hidden select-none">
      
      {/* Top Header & Context Bar */}
      <div className="border-b border-[#d7d2c6]/80 bg-[#fffdf8]/95 backdrop-blur-md px-4 sm:px-6 py-3.5 shrink-0 z-20">
        <div className="flex flex-wrap items-center justify-between gap-4">
          
          {/* Left: Breadcrumbs & Title */}
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-xl bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
              <GitFork className="w-4 h-4" />
            </div>

            <div>
              {focusEntityId && (
                <div className="flex items-center gap-2 text-xs font-mono text-amber-800 font-bold mb-0.5">
                  <span>focus:</span>
                  <code>{focusEntityId}</code>
                </div>
              )}
              <h1 className="text-lg font-bold font-sans text-[#292b25] tracking-tight flex items-center gap-2 pt-0.5">
                <span>Provenance & Subgraph Architecture</span>
                {isLoading ? (
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-cyan-500/10 text-[#54734f] border border-cyan-500/30 animate-pulse">
                    Querying Subgraph...
                  </span>
                ) : graphData ? (
                  <span className="text-xs font-mono px-2 py-0.5 rounded-full bg-[#fffdf8] border border-[#d7d2c6] text-[#51534b]">
                    {visibleNodesList.length} of {graphData.nodes.length} nodes visible
                  </span>
                ) : null}
              </h1>
            </div>
          </div>

          {activeQuestion && (
          <>
          {/* Center: Search Entities autocomplete (GET /api/v1/repositories/{id}/entities) */}
          <div className="relative w-full sm:w-72 lg:w-96">
            <div className="relative">
              <Search className="w-3.5 h-3.5 text-[#77776e] absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => {
                  setSearchQuery(e.target.value);
                  setIsSearchOpen(true);
                }}
                onFocus={() => setIsSearchOpen(true)}
                placeholder="Search entities (e.g. retry, config)..."
                className="w-full pl-8 pr-8 py-1.5 rounded-xl bg-[#f5f3ed]/80 border border-[#d7d2c6] text-xs font-mono text-[#51534b] placeholder:text-[#77776e] focus:outline-none focus:border-indigo-500/60 transition-all"
              />
              {searchQuery && (
                <button
                  onClick={() => {
                    setSearchQuery('');
                    setSearchResults([]);
                    setIsSearchOpen(false);
                  }}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[#77776e] hover:text-[#292b25]"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              )}
            </div>

            {/* Dropdown search results */}
            {isSearchOpen && (searchResults.length > 0 || isSearching) && (
              <div className="absolute top-full left-0 right-0 mt-1.5 bg-[#fffdf8] border border-[#d7d2c6]/80 rounded-xl shadow-2xl overflow-hidden z-50 text-xs font-mono max-h-64 overflow-y-auto">
                <div className="px-3 py-1.5 border-b border-[#d7d2c6] text-[10px] text-[#77776e] uppercase tracking-wider flex items-center justify-between">
                  <span>Candidate Entities</span>
                  {isSearching && <span>Searching...</span>}
                </div>

                {searchResults.map((ent) => (
                  <button
                    key={ent.id}
                    onClick={() => {
                      setFocusEntityId(ent.id);
                      setIsSearchOpen(false);
                      setSearchQuery('');
                    }}
                    className="w-full text-left px-3 py-2 hover:bg-[#efede5] flex items-center justify-between border-b border-[#d7d2c6]/40 last:border-0 transition-colors cursor-pointer"
                  >
                    <div className="flex items-center gap-2 truncate">
                      {ent.type === 'Module' && <Folder className="w-3.5 h-3.5 text-[#54734f] shrink-0" />}
                      {ent.type === 'ConfigKey' && <Key className="w-3.5 h-3.5 text-purple-400 shrink-0" />}
                      {ent.type === 'File' && <FileCode className="w-3.5 h-3.5 text-[#54734f] shrink-0" />}
                      <div className="truncate">
                        <span className="font-semibold text-[#292b25]">{ent.label}</span>
                        {ent.path && <span className="text-[#77776e] text-[10px] block truncate">{ent.path}</span>}
                      </div>
                    </div>

                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-indigo-500/20 text-indigo-800 shrink-0">
                      Focus Subgraph
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Right: Controls & Navigation */}
          <div className="flex items-center gap-2">
            
            {/* View Mode Switcher */}
            <div className="flex items-center bg-[#fffdf8] p-1 rounded-xl border border-[#d7d2c6] text-xs font-mono">
              <button
                onClick={() => setViewMode('graph')}
                className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg transition-all cursor-pointer ${
                  viewMode === 'graph'
                    ? 'bg-indigo-500/20 text-indigo-800 font-semibold border border-indigo-500/40'
                    : 'text-[#77776e] hover:text-[#51534b]'
                }`}
                title="Interactive React Flow Graph View"
              >
                <Workflow className="w-3.5 h-3.5" />
                <span>Visual</span>
              </button>

              <button
                onClick={() => setViewMode('list')}
                className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg transition-all cursor-pointer ${
                  viewMode === 'list'
                    ? 'bg-indigo-500/20 text-indigo-800 font-semibold border border-indigo-500/40'
                    : 'text-[#77776e] hover:text-[#51534b]'
                }`}
                title="Accessible Screen-Reader Ready List View"
              >
                <Table className="w-3.5 h-3.5" />
                <span>Accessible List</span>
              </button>
            </div>

            {/* Clear Entity Focus Button */}
            {focusEntityId && (
              <button
                onClick={() => setFocusEntityId(null)}
                className="flex items-center gap-1 px-2.5 py-1.5 rounded-xl bg-amber-500/10 hover:bg-amber-500/20 text-amber-800 border border-amber-500/30 text-xs font-mono transition-colors cursor-pointer"
                title="Return to the entity from the latest question"
              >
                <RotateCcw className="w-3 h-3" />
                <span>Question Entity</span>
              </button>
            )}
          </div>
          </>
          )}
        </div>

        {/* Node Type Filter Chips Bar */}
        {activeQuestion && (
        <div className="flex flex-wrap items-center gap-2 pt-3 border-t border-slate-850 mt-3 text-xs font-mono">
          <span className="text-[10px] text-[#77776e] uppercase tracking-wider flex items-center gap-1 mr-1">
            <Filter className="w-3 h-3" /> Filters:
          </span>

          {/* Repository */}
          <button
            onClick={() => toggleFilter('Repository')}
            className={`px-2.5 py-0.5 rounded-lg border flex items-center gap-1.5 transition-colors cursor-pointer text-xs ${
              filters.Repository
                ? 'bg-amber-500/15 text-amber-400 border-amber-500/40 font-semibold'
                : 'bg-[#f5f3ed] text-[#77776e] border-[#d7d2c6] opacity-60'
            }`}
          >
            <GitBranch className="w-3 h-3 text-amber-400" />
            <span>Repository</span>
          </button>

          {/* CodeEntity */}
          <button
            onClick={() => toggleFilter('CodeEntity')}
            className={`px-2.5 py-0.5 rounded-lg border flex items-center gap-1.5 transition-colors cursor-pointer text-xs ${
              filters.CodeEntity
                ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/40 font-semibold'
                : 'bg-[#f5f3ed] text-[#77776e] border-[#d7d2c6] opacity-60'
            }`}
          >
            <FileCode className="w-3 h-3 text-emerald-400" />
            <span>Entities (File/Module/Key)</span>
          </button>

          {/* Decision */}
          <button
            onClick={() => toggleFilter('Decision')}
            className={`px-2.5 py-0.5 rounded-lg border flex items-center gap-1.5 transition-colors cursor-pointer text-xs ${
              filters.Decision
                ? 'bg-amber-500/15 text-amber-400 border-amber-500/40 font-semibold'
                : 'bg-[#f5f3ed] text-[#77776e] border-[#d7d2c6] opacity-60'
            }`}
          >
            <CheckCircle2 className="w-3 h-3 text-amber-400" />
            <span>Decisions</span>
          </button>

          {/* PullRequest */}
          <button
            onClick={() => toggleFilter('PullRequest')}
            className={`px-2.5 py-0.5 rounded-lg border flex items-center gap-1.5 transition-colors cursor-pointer text-xs ${
              filters.PullRequest
                ? 'bg-amber-500/15 text-amber-400 border-amber-500/40 font-semibold'
                : 'bg-[#f5f3ed] text-[#77776e] border-[#d7d2c6] opacity-60'
            }`}
          >
            <GitPullRequest className="w-3 h-3 text-amber-400" />
            <span>Pull Requests</span>
          </button>

          {/* Evidence (Hidden by default) */}
          <button
            onClick={() => toggleFilter('Evidence')}
            className={`px-2.5 py-0.5 rounded-lg border flex items-center gap-1.5 transition-colors cursor-pointer text-xs ${
              filters.Evidence
                ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/40 font-semibold'
                : 'bg-[#f5f3ed] text-[#77776e] border-[#d7d2c6]'
            }`}
          >
            {filters.Evidence ? <Eye className="w-3 h-3 text-emerald-400" /> : <EyeOff className="w-3 h-3 text-[#77776e]" />}
            <span>Evidence {filters.Evidence ? '(Shown)' : '(Hidden)'}</span>
          </button>

          {/* Person (Hidden by default) */}
          <button
            onClick={() => toggleFilter('Person')}
            className={`px-2.5 py-0.5 rounded-lg border flex items-center gap-1.5 transition-colors cursor-pointer text-xs ${
              filters.Person
                ? 'bg-rose-500/15 text-rose-400 border-rose-500/40 font-semibold'
                : 'bg-[#f5f3ed] text-[#77776e] border-[#d7d2c6]'
            }`}
          >
            {filters.Person ? <Eye className="w-3 h-3 text-rose-400" /> : <EyeOff className="w-3 h-3 text-[#77776e]" />}
            <span>People {filters.Person ? '(Shown)' : '(Hidden)'}</span>
          </button>

          {/* Test State Simulator Toggles */}
          <div className="ml-auto flex items-center gap-2 text-[10px] text-[#77776e]">
            <span className="text-[#77776e] uppercase">Test States:</span>
            <button
              onClick={() => setSimulateOffline((o) => !o)}
              className={`px-2 py-0.5 rounded border text-[10px] font-mono transition-colors ${
                simulateOffline
                  ? 'bg-rose-500/20 text-rose-800 border-rose-500/40 font-bold'
                  : 'bg-[#fffdf8] text-[#77776e] border-[#d7d2c6] hover:text-[#292b25]'
              }`}
            >
              {simulateOffline ? 'Reset Online' : 'Simulate 503'}
            </button>
            <button
              onClick={() => setSimulateTruncated((t) => !t)}
              className={`px-2 py-0.5 rounded border text-[10px] font-mono transition-colors ${
                simulateTruncated
                  ? 'bg-amber-500/20 text-amber-800 border-amber-500/40 font-bold'
                  : 'bg-[#fffdf8] text-[#77776e] border-[#d7d2c6] hover:text-[#292b25]'
              }`}
            >
              {simulateTruncated ? 'Reset Ceiling' : 'Simulate Truncated'}
            </button>
          </div>
        </div>
        )}
      </div>

      {/* Truncated Subgraph Notice Banner */}
      {graphData?.truncated && (
        <div className="bg-amber-950/40 border-b border-amber-500/30 px-4 py-2 flex items-center justify-between text-xs font-mono text-amber-800 z-10 shrink-0">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0" />
            <span>
              <strong>Truncated Response Notice:</strong> Graph query reached the hard node budget (maximum 80 nodes returned). Some entities or temporal supersessions may not be displayed.
            </span>
          </div>
          <span className="text-[11px] text-amber-400/80 hidden sm:inline">
            Focus on an entity using the search bar to inspect focused subgraphs.
          </span>
        </div>
      )}

      {activeQuestion && (
        <div className="shrink-0 border-b border-[#d7d2c6] bg-[#fffdf8]/90 px-4 py-2">
          <p className="text-[10px] font-mono uppercase tracking-wider text-indigo-800">Graph for latest question</p>
          <p className="mt-0.5 truncate text-xs text-[#51534b]">{activeQuestion.question}</p>
        </div>
      )}

      {activeQuestion && focusEntityId && !isGraphOffline && !errorMessage && viewMode === 'graph' && (
        <div className="shrink-0 border-b border-[#d7d2c6] bg-[#fffdf8]/90 px-4 py-2">
          <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-[10px] font-mono text-[#77776e]">
            <span className="uppercase font-bold tracking-wider text-[#51534b]">Legend</span>
            <span className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-amber-500" />
              Decision
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-500" />
              Source File
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-purple-400" />
              Commit
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-rose-400" />
              Author
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-4 border-t-2 border-dashed border-orange-400" />
              SUPERSEDES
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-4 border-t-2 border-emerald-500" />
              GOVERNS
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-4 border-t-2 border-violet-500" />
              DECIDED_IN
            </span>
          </div>
        </div>
      )}

      {/* Main Content Area: Visual Graph or Accessible List or 503 Offline State */}
      <div className="flex-1 relative flex overflow-hidden">
        
        {!activeQuestion ? (
          <div className="flex-1 flex flex-col items-center justify-center p-6 text-center z-10 space-y-4">
            <div className="p-4 rounded-2xl bg-indigo-500/10 text-indigo-400 border border-indigo-500/30">
              <Workflow className="w-10 h-10" />
            </div>
            <div className="max-w-md space-y-2">
              <h2 className="text-xl font-bold font-sans text-[#292b25]">Ask a question to explore its graph</h2>
              <p className="text-xs font-mono text-[#51534b] leading-relaxed">
                The graph will focus on the entity and decision connections related to your latest question.
              </p>
            </div>
            <button
              type="button"
              onClick={onAskQuestion}
              className="px-4 py-2 rounded-xl bg-cyan-500/20 hover:bg-cyan-500/30 text-[#54734f] border border-cyan-500/40 text-xs font-mono font-semibold transition-colors"
            >
              Go to Workspace
            </button>
          </div>
        ) : !focusEntityId ? (
          <div className="flex-1 flex flex-col items-center justify-center p-6 text-center z-10 space-y-4">
            <div className="p-4 rounded-2xl bg-amber-500/10 text-amber-400 border border-amber-500/30">
              <GitFork className="w-10 h-10" />
            </div>
            <div className="max-w-md space-y-2">
              <h2 className="text-xl font-bold font-sans text-[#292b25]">No single entity to graph</h2>
              <p className="text-xs font-mono text-[#51534b] leading-relaxed">
                This question did not resolve to one code entity. Ask a question about a specific file, module, or configuration key to see its connected graph.
              </p>
            </div>
            <button
              type="button"
              onClick={onAskQuestion}
              className="px-4 py-2 rounded-xl bg-cyan-500/20 hover:bg-cyan-500/30 text-[#54734f] border border-cyan-500/40 text-xs font-mono font-semibold transition-colors"
            >
              Go to Workspace
            </button>
          </div>
        ) : isGraphOffline ? (
          <div className="flex-1 flex flex-col items-center justify-center p-6 text-center z-10 space-y-4">
            <div className="p-4 rounded-2xl bg-rose-500/10 text-rose-400 border border-rose-500/30">
              <Database className="w-10 h-10" />
            </div>

            <div className="max-w-md space-y-2">
              <div className="inline-block px-2.5 py-0.5 rounded-full bg-rose-500/20 text-rose-800 border border-rose-500/40 text-xs font-mono font-bold">
                HTTP 503 • Graph Service Offline
              </div>
              <h2 className="text-xl font-bold font-sans text-[#292b25]">
                Graph Database Engine Unavailable
              </h2>
              <p className="text-xs font-mono text-[#51534b] leading-relaxed">
                The graph query service (Neo4j) is currently offline, unconfigured, or unreachable. 
                CodeWhy's local SQLite store remains 100% operational for questions and decision timelines.
              </p>
            </div>

            <div className="flex flex-wrap items-center justify-center gap-3 pt-2 text-xs font-mono">
              <button
                onClick={() => {
                  setSimulateOffline(false);
                  loadGraph(repoId, focusEntityId);
                }}
                className="px-4 py-2 rounded-xl bg-cyan-500/20 hover:bg-cyan-500/30 text-[#54734f] border border-cyan-500/40 font-semibold transition-colors flex items-center gap-2 cursor-pointer"
              >
                <RotateCcw className="w-3.5 h-3.5" />
                <span>Retry Connection</span>
              </button>
            </div>
          </div>
        ) : errorMessage ? (
          /* Error State */
          <div className="flex-1 flex flex-col items-center justify-center p-6 text-center z-10 space-y-3">
            <AlertTriangle className="w-8 h-8 text-amber-400" />
            <h3 className="text-sm font-bold text-[#292b25] font-mono">{errorMessage}</h3>
            <button
              onClick={() => {
                setFocusEntityId(null);
                loadGraph(repoId, null);
              }}
              className="px-3 py-1.5 rounded-xl bg-[#fffdf8] text-[#51534b] border border-[#d7d2c6] text-xs font-mono hover:text-[#292b25]"
            >
              Return to Full Graph
            </button>
          </div>
        ) : viewMode === 'list' ? (
          /* 2. Accessible Screen-Reader Friendly List View */
          <div className="flex-1 overflow-y-auto p-4 sm:p-6 w-full max-w-7xl mx-auto space-y-6">
            <div className="flex items-center justify-between border-b border-[#d7d2c6] pb-3">
              <div>
                <h2 className="text-sm font-mono font-bold uppercase text-[#292b25] tracking-wider">
                  Accessible Graph Lineage View
                </h2>
                <p className="text-xs text-[#77776e] font-mono">
                  Tabular screen-reader accessible inventory of {visibleNodesList.length} visible graph nodes and {visibleEdgesList.length} relationships
                </p>
              </div>

              <span className="text-xs font-mono px-2 py-0.5 rounded bg-indigo-500/10 text-indigo-800 border border-indigo-500/30">
                ARIA Accessible
              </span>
            </div>

            <div className="rounded-xl border border-[#d7d2c6] bg-[#f5f3ed]/60 overflow-hidden text-xs font-mono">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="border-b border-[#d7d2c6] bg-[#fffdf8]/80 text-[#77776e] text-[11px] uppercase tracking-wider">
                    <th className="py-3 px-4">Node Label & ID</th>
                    <th className="py-3 px-4">Type</th>
                    <th className="py-3 px-4">State / Property</th>
                    <th className="py-3 px-4">Connections</th>
                    <th className="py-3 px-4 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60 text-[#51534b]">
                  {visibleNodesList.map((node) => {
                    const inCount = graphData?.edges.filter((e) => e.target === node.id).length || 0;
                    const outCount = graphData?.edges.filter((e) => e.source === node.id).length || 0;
                    return (
                      <tr key={node.id} className="hover:bg-[#fffdf8]/50 transition-colors">
                        <td className="py-3 px-4">
                          <div className="font-bold text-[#292b25]">{node.label}</div>
                          <div className="text-[10px] text-[#77776e]">{node.id}</div>
                        </td>
                        <td className="py-3 px-4">
                          <span className="px-2 py-0.5 rounded bg-[#efede5] text-[#51534b] border border-[#d7d2c6] text-[10px]">
                            {node.type}
                            {node.props?.entity_type ? ` (${node.props.entity_type})` : ''}
                          </span>
                        </td>
                        <td className="py-3 px-4">
                          {node.props?.state && (
                            <span
                              className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                                node.props.state === 'ACTIVE'
                                  ? 'bg-emerald-500/20 text-emerald-800 border border-emerald-500/40'
                                  : node.props.state === 'SUPERSEDED'
                                  ? 'bg-[#efede5] text-[#77776e] border border-[#d7d2c6]'
                                  : 'bg-rose-500/20 text-rose-800 border border-rose-500/40'
                              }`}
                            >
                              {node.props.state}
                            </span>
                          )}
                          {node.props?.path && (
                            <span className="text-[10px] text-[#77776e] block truncate max-w-xs">{node.props.path}</span>
                          )}
                          {node.props?.number && (
                            <span className="text-[10px] text-indigo-800">PR #{node.props.number}</span>
                          )}
                        </td>
                        <td className="py-3 px-4 text-[11px] text-[#77776e]">
                          {inCount} in • {outCount} out
                        </td>
                        <td className="py-3 px-4 text-right space-x-2">
                          <button
                            onClick={() => setSelectedNode(node)}
                            className="px-2.5 py-1 rounded bg-[#fffdf8] hover:bg-[#efede5] text-[#54734f] border border-[#d7d2c6] text-[10px]"
                          >
                            Inspect
                          </button>
                          {node.type === 'Decision' && (
                            <button
                              onClick={() => setActiveDecisionDrawerId(node.id)}
                              className="px-2.5 py-1 rounded bg-emerald-500/15 hover:bg-emerald-500/25 text-emerald-800 border border-emerald-500/30 text-[10px]"
                            >
                              Drawer
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        ) : (
          /* 3. Interactive React Flow Canvas */
          <div className="flex-1 w-full h-full relative">
            <ReactFlow
              nodes={nodes}
              edges={edges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              nodeTypes={nodeTypes}
              fitView
              fitViewOptions={{ padding: 0.2, maxZoom: 0.9 }}
              minZoom={0.2}
              maxZoom={2.5}
              defaultViewport={{ x: 0, y: 0, zoom: 0.85 }}
              className="bg-[#f5f3ed]"
              proOptions={{ hideAttribution: true }}
            >
              <Background color="var(--border)" gap={24} size={1} />
              <Controls className="codewhy-flow-controls" />
              <MiniMap
                className="codewhy-flow-minimap"
                pannable
                zoomable
                style={{ backgroundColor: 'var(--surface)', border: '1px solid var(--border)' }}
                nodeColor={(node) => {
                  const rawNode = node.data.raw as RawGraphNode;
                  if (rawNode.type === 'Decision') return 'var(--warning)';
                  if (rawNode.type === 'CodeEntity') return 'var(--accent)';
                  return 'var(--text-subtle)';
                }}
                maskColor="rgba(22, 28, 43, 0.12)"
              />
            </ReactFlow>
          </div>
        )}

        {/* 4. Node Detail Inspector Slide-Over Panel */}
        {selectedNode && (
          <aside className="w-80 sm:w-96 border-l border-[#d7d2c6] bg-[#efede5]/95 backdrop-blur-xl p-5 overflow-y-auto space-y-5 shrink-0 z-30 flex flex-col justify-between shadow-2xl">
            <div className="space-y-4">
              <div className="flex items-center justify-between border-b border-[#d7d2c6] pb-3">
                <span className="text-[10px] font-mono uppercase tracking-wider text-[#77776e] flex items-center gap-1.5 font-bold">
                  <Workflow className="w-3.5 h-3.5 text-[#54734f]" />
                  Node Inspection
                </span>
                <button
                  onClick={() => setSelectedNode(null)}
                  className="p-1 rounded-lg hover:bg-[#efede5] text-[#77776e] hover:text-[#292b25] transition-colors"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              {/* Title & Badge */}
              <div className="space-y-1.5">
                <div className="flex items-center gap-2">
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#efede5] text-[#51534b] border border-[#d7d2c6]">
                    {selectedNode.type}
                  </span>
                  {selectedNode.props?.state && (
                    <span
                      className={`text-[10px] font-mono px-2 py-0.5 rounded font-bold ${
                        selectedNode.props.state === 'ACTIVE'
                          ? 'bg-emerald-500/20 text-emerald-800 border border-emerald-500/40'
                          : selectedNode.props.state === 'SUPERSEDED'
                          ? 'bg-[#efede5] text-[#77776e] border border-[#d7d2c6]'
                          : 'bg-rose-500/20 text-rose-800 border border-rose-500/40'
                      }`}
                    >
                      {selectedNode.props.state}
                    </span>
                  )}
                </div>

                <h3 className="text-sm font-bold font-mono text-[#292b25] leading-snug">
                  {selectedNode.label}
                </h3>
                <div className="text-[11px] font-mono text-[#77776e] break-all">
                  ID: <code className="text-[#54734f]">{selectedNode.id}</code>
                </div>
              </div>

              {/* Properties table */}
              <div className="space-y-2">
                <span className="text-[10px] font-mono uppercase tracking-wider text-[#77776e] block font-bold">
                  Returned Properties
                </span>
                <div className="p-3 rounded-xl bg-[#f5f3ed]/80 border border-[#d7d2c6] space-y-1.5 text-xs font-mono">
                  {Object.entries(selectedNode.props || {}).length > 0 ? (
                    Object.entries(selectedNode.props).map(([k, v]) => (
                      <div key={k} className="flex items-start justify-between gap-2 border-b border-slate-850 pb-1 last:border-0 last:pb-0">
                        <span className="text-[#77776e] text-[11px]">{k}:</span>
                        <span className="text-[#51534b] text-right truncate max-w-[180px]" title={String(v)}>
                          {String(v)}
                        </span>
                      </div>
                    ))
                  ) : (
                    <span className="text-[#77776e] text-[11px]">No extra properties recorded</span>
                  )}
                </div>
              </div>

              {/* Connected Relationships */}
              <div className="space-y-2">
                <span className="text-[10px] font-mono uppercase tracking-wider text-[#77776e] block font-bold">
                  Relationships ({connectedDetails.inbound.length + connectedDetails.outbound.length})
                </span>

                <div className="space-y-2 max-h-48 overflow-y-auto text-xs font-mono">
                  {connectedDetails.inbound.map((edge, i) => (
                    <div key={`in-${i}`} className="p-2 rounded-lg bg-[#fffdf8]/60 border border-[#d7d2c6] flex items-center justify-between text-[11px]">
                      <span className="text-[#77776e] truncate max-w-[120px]">{edge.source}</span>
                      <span className="text-[#54734f] font-bold px-1.5 py-0.5 rounded bg-cyan-950/40 text-[9px]">
                        ──({edge.type})──►
                      </span>
                      <span className="text-[#292b25] font-semibold">this</span>
                    </div>
                  ))}

                  {connectedDetails.outbound.map((edge, i) => (
                    <div key={`out-${i}`} className="p-2 rounded-lg bg-[#fffdf8]/60 border border-[#d7d2c6] flex items-center justify-between text-[11px]">
                      <span className="text-[#292b25] font-semibold">this</span>
                      <span className="text-indigo-400 font-bold px-1.5 py-0.5 rounded bg-indigo-950/40 text-[9px]">
                        ──({edge.type})──►
                      </span>
                      <span className="text-[#77776e] truncate max-w-[120px]">{edge.target}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* Action Buttons */}
            <div className="space-y-2 pt-4 border-t border-[#d7d2c6] text-xs font-mono">
              {selectedNode.type === 'Decision' && (
                <button
                  onClick={() => setActiveDecisionDrawerId(selectedNode.id)}
                  className="w-full py-2 px-3 rounded-xl bg-gradient-to-r from-emerald-500/20 to-cyan-500/20 hover:from-emerald-500/30 hover:to-cyan-500/30 text-emerald-800 border border-emerald-500/40 font-semibold flex items-center justify-center gap-1.5 transition-all cursor-pointer"
                >
                  <Layers className="w-3.5 h-3.5 text-emerald-400" />
                  <span>Open Full Decision Drawer</span>
                </button>
              )}

              {selectedNode.type === 'CodeEntity' && (
                <button
                  onClick={() => {
                    setFocusEntityId(selectedNode.id);
                  }}
                  className="w-full py-2 px-3 rounded-xl bg-indigo-500/20 hover:bg-indigo-500/30 text-indigo-800 border border-indigo-500/40 font-semibold flex items-center justify-center gap-1.5 transition-all cursor-pointer"
                >
                  <Workflow className="w-3.5 h-3.5 text-indigo-400" />
                  <span>Focus Subgraph on this Entity</span>
                </button>
              )}
            </div>
          </aside>
        )}
      </div>

      {/* Shared Decision Detail Drawer */}
      <DecisionDrawer
        decisionId={activeDecisionDrawerId}
        onClose={() => setActiveDecisionDrawerId(null)}
      />
    </div>
  );
};
