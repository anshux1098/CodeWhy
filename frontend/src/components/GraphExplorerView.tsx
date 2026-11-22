import React, {
  useState,
  useEffect,
  useCallback,
  useMemo,
  useRef,
} from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MarkerType,
  Position,
  Handle,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type NodeProps,
  type ReactFlowInstance,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
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
  Loader2,
  Focus,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';

const NODE_WIDTH = 288;
const NODE_HEIGHT = 144;
const NODE_SPACING = 400;
const RADIAL_SPACING = 440;

function radialNodePositions(
  nodes: RawGraphNode[],
  edges: GraphResponse['edges'],
  focusId?: string | null,
): Map<string, { x: number; y: number }> {
  const adjacency = new Map(nodes.map((node) => [node.id, new Set<string>()]));
  for (const edge of edges) {
    adjacency.get(edge.source)?.add(edge.target);
    adjacency.get(edge.target)?.add(edge.source);
  }

  const degree = (id: string) => adjacency.get(id)?.size ?? 0;
  const rootNode = nodes.find((node) => node.id === focusId)
    ?? [...nodes].sort((a, b) => degree(b.id) - degree(a.id) || a.id.localeCompare(b.id))[0];
  if (!rootNode) return new Map();
  const rootId = rootNode.id;
  const levels = new Map<string, number>([[rootId, 0]]);
  const queue = [rootId];

  for (let index = 0; index < queue.length; index += 1) {
    const nodeId = queue[index];
    for (const neighbor of adjacency.get(nodeId) ?? []) {
      if (levels.has(neighbor)) continue;
      levels.set(neighbor, (levels.get(nodeId) ?? 0) + 1);
      queue.push(neighbor);
    }
  }

  const maxLevel = Math.max(0, ...levels.values());
  for (const node of nodes) {
    if (!levels.has(node.id)) levels.set(node.id, maxLevel + 1);
  }

  const rings = new Map<number, RawGraphNode[]>();
  for (const node of nodes) {
    const level = levels.get(node.id) ?? 0;
    const ring = rings.get(level) ?? [];
    ring.push(node);
    rings.set(level, ring);
  }

  const positions = new Map<string, { x: number; y: number }>([
    [rootId, { x: -NODE_WIDTH / 2, y: -NODE_HEIGHT / 2 }],
  ]);
  for (const [level, ring] of rings) {
    if (level === 0) continue;
    ring.sort((a, b) => degree(b.id) - degree(a.id) || a.id.localeCompare(b.id));
    const radius = Math.max(RADIAL_SPACING * level, ring.length * NODE_SPACING / (2 * Math.PI));
    const offset = (level % 2) * Math.PI / Math.max(ring.length, 1);
    ring.forEach((node, index) => {
      const angle = (2 * Math.PI * index) / ring.length + offset;
      positions.set(node.id, {
        x: Math.cos(angle) * radius - NODE_WIDTH / 2,
        y: Math.sin(angle) * radius - NODE_HEIGHT / 2,
      });
    });
  }
  return positions;
}

// Custom Node Data
interface CustomNodeData extends Record<string, unknown> {
  raw: RawGraphNode;
  isSelected: boolean;
  isFocus: boolean;
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
          ? <CheckCircle2 className="w-3.5 h-3.5 text-[#C5B0E6] shrink-0" />
          : state === 'SUPERSEDED'
            ? <Clock className="w-3.5 h-3.5 text-[#CAC4CE] shrink-0" />
            : state === 'REJECTED'
              ? <XCircle className="w-3.5 h-3.5 text-[#f85149] shrink-0" />
              : <HelpCircle className="w-3.5 h-3.5 text-[#e3b341] shrink-0" />;
        return {
          borderColor: isSelected
            ? 'border-[#9067C6] ring-2 ring-[#9067C6]/50'
            : 'border-[#9067C6]/55 hover:border-[#9067C6]',
          bg: 'bg-[#242038]',
          badgeBg: 'bg-[#9067C6]/20 text-[#F7ECE1] border-[#9067C6]/45',
          badgeText,
          icon,
          glowColor: 'hover:shadow-[0_0_20px_rgba(144,103,198,0.28)]',
          handleColor: '!bg-[#9067C6] !border-[#242038]',
        };
      }
      case 'CodeEntity': {
        const entType = node.props?.entity_type || 'File';
        if (entType === 'Module') {
          return {
            borderColor: isSelected
              ? 'border-[#8D86C9] ring-2 ring-[#8D86C9]/50'
              : 'border-[#8D86C9]/55 hover:border-[#8D86C9]',
            bg: 'bg-[#242038]',
            badgeBg: 'bg-[#8D86C9]/20 text-[#F7ECE1] border-[#8D86C9]/45',
            badgeText: 'Module',
            icon: <Folder className="w-3.5 h-3.5 text-[#8D86C9] shrink-0" />,
            glowColor: 'hover:shadow-[0_0_20px_rgba(141,134,201,0.25)]',
            handleColor: '!bg-[#8D86C9] !border-[#242038]',
          };
        }
        if (entType === 'ConfigKey') {
          return {
            borderColor: isSelected
              ? 'border-[#CAC4CE] ring-2 ring-[#CAC4CE]/45'
              : 'border-[#CAC4CE]/45 hover:border-[#CAC4CE]',
            bg: 'bg-[#242038]',
            badgeBg: 'bg-[#CAC4CE]/15 text-[#F7ECE1] border-[#CAC4CE]/35',
            badgeText: 'ConfigKey',
            icon: <Key className="w-3.5 h-3.5 text-[#CAC4CE] shrink-0" />,
            glowColor: 'hover:shadow-[0_0_18px_rgba(202,196,206,0.2)]',
            handleColor: '!bg-[#CAC4CE] !border-[#242038]',
          };
        }
        return {
          borderColor: isSelected
            ? 'border-[#8D86C9] ring-2 ring-[#8D86C9]/50'
            : 'border-[#8D86C9]/55 hover:border-[#8D86C9]',
          bg: 'bg-[#242038]',
          badgeBg: 'bg-[#8D86C9]/20 text-[#F7ECE1] border-[#8D86C9]/45',
          badgeText: 'File',
          icon: <FileCode className="w-3.5 h-3.5 text-[#8D86C9] shrink-0" />,
          glowColor: 'hover:shadow-[0_0_20px_rgba(141,134,201,0.25)]',
          handleColor: '!bg-[#8D86C9] !border-[#242038]',
        };
      }
      case 'Commit':
        return {
          borderColor: isSelected
            ? 'border-[#E06C75] ring-2 ring-[#E06C75]/50'
            : 'border-[#E06C75]/45 hover:border-[#E06C75]',
          bg: 'bg-[#242038]',
          badgeBg: 'bg-[#E06C75]/15 text-[#F7ECE1] border-[#E06C75]/35',
          badgeText: 'Commit',
          icon: <GitCommit className="w-3.5 h-3.5 text-[#E06C75] shrink-0" />,
          glowColor: 'hover:shadow-[0_0_18px_rgba(224,108,117,0.22)]',
          handleColor: '!bg-[#E06C75] !border-[#242038]',
        };
      case 'Repository':
        return {
          borderColor: isSelected
            ? 'border-[#F7ECE1] ring-2 ring-[#9067C6]/55'
            : 'border-[#F7ECE1]/45 hover:border-[#F7ECE1]',
          bg: 'bg-[#242038]',
          badgeBg: 'bg-[#F7ECE1]/15 text-[#F7ECE1] border-[#F7ECE1]/35',
          badgeText: 'Repository',
          icon: <GitBranch className="w-3.5 h-3.5 text-[#F7ECE1] shrink-0" />,
          glowColor: 'hover:shadow-[0_0_18px_rgba(247,236,225,0.2)]',
          handleColor: '!bg-[#F7ECE1] !border-[#242038]',
        };
      case 'PullRequest':
        return {
          borderColor: isSelected
            ? 'border-[#AFD2FA] ring-2 ring-[#AFD2FA]/50'
            : 'border-[#AFD2FA]/45 hover:border-[#AFD2FA]',
          bg: 'bg-[#242038]',
          badgeBg: 'bg-[#AFD2FA]/15 text-[#F7ECE1] border-[#AFD2FA]/35',
          badgeText: node.props?.merged === false ? 'PR (Open)' : 'PR',
          icon: <GitPullRequest className="w-3.5 h-3.5 text-[#AFD2FA] shrink-0" />,
          glowColor: 'hover:shadow-[0_0_18px_rgba(175,210,250,0.22)]',
          handleColor: '!bg-[#AFD2FA] !border-[#242038]',
        };
      case 'Evidence':
        return {
          borderColor: isSelected
            ? 'border-[#CAC4CE] ring-2 ring-[#CAC4CE]/45'
            : 'border-[#CAC4CE]/30 hover:border-[#CAC4CE]/65',
          bg: 'bg-[#242038]',
          badgeBg: 'bg-[#161324] text-[#CAC4CE] border-[#CAC4CE]/25',
          badgeText: 'Evidence',
          icon: <FileText className="w-3.5 h-3.5 text-[#CAC4CE] shrink-0" />,
          glowColor: 'hover:shadow-[0_0_16px_rgba(202,196,206,0.18)]',
          handleColor: '!bg-[#CAC4CE] !border-[#242038]',
        };
      case 'Person':
        return {
          borderColor: isSelected
            ? 'border-[#8D86C9] ring-2 ring-[#8D86C9]/50'
            : 'border-[#CAC4CE]/30 hover:border-[#8D86C9]/65',
          bg: 'bg-[#242038]',
          badgeBg: 'bg-[#8D86C9]/20 text-[#F7ECE1] border-[#8D86C9]/40',
          badgeText: 'Person',
          icon: <User className="w-3.5 h-3.5 text-[#8D86C9] shrink-0" />,
          glowColor: 'hover:shadow-[0_0_16px_rgba(141,134,201,0.22)]',
          handleColor: '!bg-[#8D86C9] !border-[#242038]',
        };
      default:
        return {
          borderColor: isSelected
            ? 'border-[#9067C6] ring-2 ring-[#9067C6]/50'
            : 'border-[#CAC4CE]/30 hover:border-[#9067C6]',
          bg: 'bg-[#242038]',
          badgeBg: 'bg-[#161324] text-[#CAC4CE] border-[#CAC4CE]/25',
          badgeText: node.type,
          icon: <Workflow className="w-3.5 h-3.5 text-[#CAC4CE] shrink-0" />,
          glowColor: 'hover:shadow-[0_0_16px_rgba(144,103,198,0.2)]',
          handleColor: '!bg-[#9067C6] !border-[#242038]',
        };
    }
  };

  const style = renderVisuals();

  return (
    <div
      onClick={() => data.onSelect(node)}
      className={`w-[288px] min-h-[144px] px-4 py-3 rounded-xl border ${style.borderColor} ${style.bg} ${style.glowColor} shadow-xl transition-all duration-150 cursor-pointer select-none group text-left ${data.isFocus ? 'ring-2 ring-[#F7ECE1] shadow-[0_0_24px_rgba(144,103,198,0.45)]' : ''}`}
    >
      <Handle type="target" position={Position.Left} className={`!w-2.5 !h-2.5 !border-2 ${style.handleColor}`} />
      
      <div className="flex items-center justify-between gap-2 mb-1.5">
        <span className={`text-[10px] font-mono px-2 py-0.5 rounded-md border font-semibold flex items-center gap-1.5 ${style.badgeBg}`}>
          {style.icon}
          <span>{style.badgeText}</span>
        </span>

        {data.isFocus ? (
          <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-[#FFFFFF] bg-[#9067C6] border border-[#9067C6] rounded px-1.5 py-0.5 shadow-[0_0_10px_rgba(144,103,198,0.35)]">
            Focus
          </span>
        ) : (
          <span className="text-[10px] font-mono text-[#CAC4CE] truncate max-w-[108px]" title={node.id}>
            {node.id.replace(/^(dec_|file:|key:|module:|person:|pr:|ev:)/, '')}
          </span>
        )}
      </div>

      <div className="text-sm font-semibold font-mono text-[#F7ECE1] leading-snug break-words line-clamp-3 group-hover:text-white transition-colors" title={node.label}>
        {node.label}
      </div>

      {node.props?.path && (
        <div className="text-[11px] font-mono text-[#CAC4CE] break-all line-clamp-2 mt-1" title={node.props.path}>
          {node.props.path}
        </div>
      )}

      {node.props?.rule && (
        <div className="mt-1.5 text-[10px] font-mono px-1.5 py-0.5 rounded bg-[#161324] text-[#C5B0E6] border border-[#9067C6]/40 truncate inline-block">
          Rule: {node.props.rule}
        </div>
      )}

      <Handle type="source" position={Position.Right} className={`!w-2.5 !h-2.5 !border-2 ${style.handleColor}`} />
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
}) => {
  const [graphData, setGraphData] = useState<GraphResponse | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isGraphOffline, setIsGraphOffline] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Focused entity for a bounded subgraph; null shows the whole repository graph.
  const [focusEntityId, setFocusEntityId] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

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

  // Collapsible legend / filters for maximum graph viewport
  const [isLegendOpen, setIsLegendOpen] = useState(true);
  const rfInstanceRef = useRef<ReactFlowInstance<Node<CustomNodeData>, Edge> | null>(null);
  const searchSeqRef = useRef(0);

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
  const repoId = selectedRepo?.id || (urlMatch ? decodeURIComponent(urlMatch[1]) : '');
  const activeQuestion = questionContext?.repositoryId === repoId ? questionContext : null;
  const questionEntityId = activeQuestion?.response.entity?.id ?? null;

  // A new question moves the focus to its entity; a repo switch clears it.
  useEffect(() => {
    setFocusEntityId(questionEntityId);
    setSelectedNode(null);
  }, [questionEntityId, repoId]);

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

  // Load the focused subgraph, or the repo-wide graph when nothing is focused.
  useEffect(() => {
    if (!repoId) {
      setGraphData(null);
      setIsGraphOffline(false);
      setErrorMessage(null);
      setIsLoading(false);
      return;
    }
    loadGraph(repoId, focusEntityId);
  }, [repoId, focusEntityId, reloadToken, loadGraph]);

  // Debounced search for entities via GET /api/v1/repositories/{id}/entities?q=...
  useEffect(() => {
    const seq = searchSeqRef.current + 1;
    searchSeqRef.current = seq;

    if (!searchQuery.trim() || searchQuery.length < 1 || !repoId) {
      setSearchResults([]);
      setIsSearching(false);
      return;
    }

    let cancelled = false;
    const timer = setTimeout(async () => {
      setIsSearching(true);
      const res = await fetchEntitySearch(repoId, searchQuery.trim());
      if (!cancelled && seq === searchSeqRef.current) {
        if (res && res.entities) {
          setSearchResults(res.entities);
        } else {
          setSearchResults([]);
        }
        setIsSearching(false);
      }
    }, 250);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [searchQuery, repoId]);

  // Filter nodes based on node-type checkboxes and Time-Travel year scrubber (2018 -> 2026)
  const [timeTravelYear, setTimeTravelYear] = useState<number>(2026);

  const visibleNodesList = useMemo(() => {
    if (!graphData?.nodes) return [];
    return graphData.nodes.filter((node) => {
      const typeKey = node.type as keyof typeof filters;
      if (filters[typeKey] !== undefined && !filters[typeKey]) {
        return false;
      }
      if (timeTravelYear < 2026) {
        const rawDate = (node as unknown as { date?: string; created_at?: string }).date
          || (node as unknown as { date?: string; created_at?: string }).created_at
          || '';
        const match = /^(\d{4})/.exec(String(rawDate));
        if (match && Number(match[1]) > timeTravelYear) {
          return false;
        }
      }
      return true;
    });
  }, [graphData, filters, timeTravelYear]);

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

  // Place the focus entity at the center and connected nodes in relationship rings.
  const { layoutNodes, layoutEdges } = useMemo(() => {
    if (visibleNodesList.length === 0) {
      return { layoutNodes: [], layoutEdges: [] };
    }

    const sortedNodes = [...visibleNodesList].sort((a, b) => a.id.localeCompare(b.id));
    const sortedEdges = [...visibleEdgesList].sort((a, b) =>
      `${a.source}->${a.target}:${a.type}`.localeCompare(`${b.source}->${b.target}:${b.type}`)
    );
    const positions = radialNodePositions(sortedNodes, sortedEdges, focusEntityId);

    const rfNodes: Node<CustomNodeData>[] = sortedNodes.map((node) => {
      return {
        id: node.id,
        type: 'customNode',
        position: positions.get(node.id) ?? { x: 0, y: 0 },
        data: {
          raw: node,
          isSelected: selectedNode?.id === node.id,
          isFocus: node.id === focusEntityId,
          onSelect: (n) => setSelectedNode(n),
          onOpenDecision: (decId) => setActiveDecisionDrawerId(decId),
        },
      };
    });

    const rfEdges: Edge[] = sortedEdges.map((edge, idx) => {
      let strokeColor = '#CAC4CE';
      let isDashed = false;

      if (edge.type === 'SUPERSEDES') {
        strokeColor = '#9067C6'; // dashed primary purple
        isDashed = true;
      } else if (edge.type === 'GOVERNS') {
        strokeColor = '#8D86C9'; // secondary lavender
      } else if (edge.type === 'DECIDED_IN') {
        strokeColor = '#E06C75'; // warm coral/red
      } else if (edge.type === 'SUPPORTED_BY') {
        strokeColor = '#3fb950';
      } else if (edge.type === 'AUTHORED' || edge.type === 'REVIEWED') {
        strokeColor = '#AFD2FA'; // powder blue
      } else if (edge.type === 'REFERENCES') {
        strokeColor = '#CAC4CE'; // soft lavender-grey
      }

      const edgeLabel = edge.rule ? `${edge.type} (${edge.rule})` : edge.type;

      return {
        id: `e-${edge.source}-${edge.target}-${idx}`,
        source: edge.source,
        target: edge.target,
        type: 'default',
        animated: edge.type === 'SUPERSEDES',
        label: edgeLabel,
        labelStyle: {
          fill: '#F7ECE1',
          fontSize: 10,
          fontFamily: 'var(--font-mono)',
          fontWeight: 600,
        },
        labelBgStyle: {
          fill: '#242038',
          fillOpacity: 0.95,
        },
        labelBgPadding: [6, 3],
        labelBgBorderRadius: 4,
        style: {
          stroke: strokeColor,
          strokeWidth: isDashed ? 2.2 : 1.85,
          strokeDasharray: isDashed ? '5,5' : undefined,
          opacity: 0.9,
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
  }, [visibleNodesList, visibleEdgesList, selectedNode, focusEntityId]);

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

  // Precompute inbound/outbound counts for the accessible list view
  const nodeDegrees = useMemo(() => {
    const counts = new Map<string, { inCount: number; outCount: number }>();
    if (!graphData?.edges) return counts;
    for (const edge of graphData.edges) {
      const src = counts.get(edge.source) ?? { inCount: 0, outCount: 0 };
      src.outCount += 1;
      counts.set(edge.source, src);
      const tgt = counts.get(edge.target) ?? { inCount: 0, outCount: 0 };
      tgt.inCount += 1;
      counts.set(edge.target, tgt);
    }
    return counts;
  }, [graphData]);

  const handleFitView = useCallback(() => {
    rfInstanceRef.current?.fitView({ padding: 0.1, maxZoom: 1.25, duration: 250 });
  }, []);

  return (
    <div
      className="flex flex-col h-[calc(100vh-var(--cw-header-h,62px))] min-h-[640px] bg-[#191628] w-full text-[#F7ECE1] overflow-hidden select-none"
    >
      
      {/* Compact Top Header & Controls Bar */}
      <div className="border-b border-[#CAC4CE]/20 bg-[#242038]/95 backdrop-blur-md px-3 sm:px-5 py-2.5 shrink-0 z-20">
        <div className="flex flex-wrap items-center justify-between gap-2.5">
          
          {/* Left: Title & Count */}
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded-lg bg-[#161324] text-[#9067C6] border border-[#9067C6]/40 shadow-sm">
              <GitFork className="w-4 h-4" />
            </div>

            <div>
              {focusEntityId && (
                <div className="flex items-center gap-1.5 text-[11px] font-mono text-[#C5B0E6] font-semibold">
                  <span className="text-[#CAC4CE] text-[10px] uppercase tracking-wider">focus:</span>
                  <code className="text-[#F7ECE1] bg-[#161324] px-1.5 py-0.2 rounded border border-[#CAC4CE]/25 max-w-[240px] truncate">{focusEntityId}</code>
                </div>
              )}
              <h1 className="text-base font-bold font-sans text-[#F7ECE1] tracking-tight flex items-center gap-2">
                <span>Connected Knowledge Graph</span>
                {isLoading ? (
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-[#9067C6]/20 text-[#C5B0E6] border border-[#9067C6]/40 animate-pulse">
                    Loading graph...
                  </span>
                ) : graphData ? (
                  <span className="text-[11px] font-mono px-2 py-0.5 rounded-full bg-[#161324] border border-[#CAC4CE]/25 text-[#CAC4CE]">
                    {visibleNodesList.length} of {graphData.nodes.length} nodes
                  </span>
                ) : null}
              </h1>
            </div>
          </div>

          {/* Center: Search Entities autocomplete */}
          <div className="relative w-full sm:w-64 lg:w-80">
            <div className="relative">
              <Search className="w-3.5 h-3.5 text-[#9067C6] absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => {
                  setSearchQuery(e.target.value);
                  setIsSearchOpen(true);
                }}
                onFocus={() => setIsSearchOpen(true)}
                placeholder="Search entities (e.g. retry, config)..."
                className="w-full pl-8 pr-8 py-1.5 rounded-lg bg-[#161324] border border-[#CAC4CE]/25 text-xs font-mono text-[#F7ECE1] placeholder:text-[#CAC4CE]/65 focus:outline-none focus:border-[#9067C6] focus:ring-1 focus:ring-[#9067C6]/40 transition-all"
              />
              {searchQuery && (
                <button
                  onClick={() => {
                    setSearchQuery('');
                    setSearchResults([]);
                    setIsSearchOpen(false);
                  }}
                  aria-label="Clear entity search"
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[#CAC4CE] hover:text-[#F7ECE1] cursor-pointer"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              )}
            </div>

            {/* Dropdown search results */}
            {isSearchOpen && (searchResults.length > 0 || isSearching) && (
              <div className="absolute top-full left-0 right-0 mt-1.5 bg-[#242038] border border-[#CAC4CE]/25 rounded-xl shadow-2xl overflow-hidden z-50 text-xs font-mono max-h-64 overflow-y-auto">
                <div className="px-3 py-1.5 border-b border-[#CAC4CE]/20 text-[10px] text-[#CAC4CE] uppercase tracking-wider flex items-center justify-between bg-[#161324]">
                  <span>Candidate Entities</span>
                  {isSearching && <span className="text-[#C5B0E6]">Searching...</span>}
                </div>

                {searchResults.map((ent) => (
                  <button
                    key={ent.id}
                    onClick={() => {
                      setFocusEntityId(ent.id);
                      setIsSearchOpen(false);
                      setSearchQuery('');
                    }}
                    className="w-full text-left px-3 py-2 hover:bg-[#322D4D] flex items-center justify-between border-b border-[#CAC4CE]/15 last:border-0 transition-colors cursor-pointer"
                  >
                    <div className="flex items-center gap-2 truncate">
                      {ent.type === 'Module' && <Folder className="w-3.5 h-3.5 text-[#8D86C9] shrink-0" />}
                      {ent.type === 'ConfigKey' && <Key className="w-3.5 h-3.5 text-[#CAC4CE] shrink-0" />}
                      {ent.type === 'File' && <FileCode className="w-3.5 h-3.5 text-[#8D86C9] shrink-0" />}
                      <div className="truncate">
                        <span className="font-semibold text-[#F7ECE1]">{ent.label}</span>
                        {ent.path && <span className="text-[#CAC4CE] text-[10px] block truncate">{ent.path}</span>}
                      </div>
                    </div>

                    <span className="text-[10px] px-2 py-0.5 rounded bg-[#9067C6]/20 text-[#F7ECE1] border border-[#9067C6]/45 shrink-0">
                      Focus Subgraph
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Right: Controls & Navigation */}
          <div className="flex flex-wrap items-center gap-1.5">
            
            {/* View Mode Switcher */}
            <div className="flex items-center bg-[#161324] p-0.5 rounded-lg border border-[#CAC4CE]/25 text-xs font-mono">
              <button
                onClick={() => setViewMode('graph')}
                className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md transition-all cursor-pointer ${
                  viewMode === 'graph'
                    ? 'bg-[#9067C6] text-white font-semibold shadow-sm'
                    : 'text-[#CAC4CE] hover:text-[#F7ECE1]'
                }`}
                title="Interactive connected node graph"
              >
                <Workflow className="w-3.5 h-3.5" />
                <span>Visual</span>
              </button>

              <button
                onClick={() => setViewMode('list')}
                className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md transition-all cursor-pointer ${
                  viewMode === 'list'
                    ? 'bg-[#9067C6] text-white font-semibold shadow-sm'
                    : 'text-[#CAC4CE] hover:text-[#F7ECE1]'
                }`}
                title="Accessible Screen-Reader Ready List View"
              >
                <Table className="w-3.5 h-3.5" />
                <span>Accessible List</span>
              </button>
            </div>

            {viewMode === 'graph' && (
              <>
                <button
                  type="button"
                  onClick={handleFitView}
                  className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-[#161324] hover:bg-[#322D4D] text-[#CAC4CE] hover:text-[#F7ECE1] border border-[#CAC4CE]/25 text-xs font-mono transition-colors cursor-pointer"
                  title="Fit graph to screen"
                >
                  <Focus className="w-3.5 h-3.5 text-[#8D86C9]" />
                  <span className="hidden xl:inline">Fit</span>
                </button>
              </>
            )}

            {/* Clear Entity Focus Button */}
            {focusEntityId && focusEntityId !== questionEntityId && (
              <button
                onClick={() => setFocusEntityId(questionEntityId)}
                className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-[#9067C6]/20 hover:bg-[#9067C6]/35 text-[#F7ECE1] border border-[#9067C6]/45 text-xs font-mono transition-colors cursor-pointer"
                title={questionEntityId ? 'Return to the entity from the latest question' : 'Return to the full repository graph'}
              >
                <RotateCcw className="w-3 h-3" />
                <span>{questionEntityId ? 'Question Entity' : 'Full Graph'}</span>
              </button>
            )}
          </div>
        </div>

        {/* Compact Node Type Filter Chips Bar */}
        <div className="flex flex-wrap items-center gap-1.5 pt-2 border-t border-[#CAC4CE]/15 mt-2 text-xs font-mono">
          <span className="text-[10px] text-[#CAC4CE] uppercase tracking-wider flex items-center gap-1 mr-1">
            <Filter className="w-3 h-3 text-[#9067C6]" /> Filters:
          </span>

          {/* Repository */}
          <button
            onClick={() => toggleFilter('Repository')}
            className={`px-2 py-0.5 rounded-md border flex items-center gap-1.5 transition-colors cursor-pointer text-[11px] ${
              filters.Repository
                ? 'bg-[#9067C6]/20 text-[#F7ECE1] border-[#9067C6]/50 font-semibold'
                : 'bg-[#161324] text-[#CAC4CE]/65 border-[#CAC4CE]/20 opacity-70'
            }`}
          >
            <GitBranch className="w-3 h-3 text-[#F7ECE1]" />
            <span>Repository</span>
          </button>

          {/* CodeEntity */}
          <button
            onClick={() => toggleFilter('CodeEntity')}
            className={`px-2 py-0.5 rounded-md border flex items-center gap-1.5 transition-colors cursor-pointer text-[11px] ${
              filters.CodeEntity
                ? 'bg-[#8D86C9]/20 text-[#F7ECE1] border-[#8D86C9]/50 font-semibold'
                : 'bg-[#161324] text-[#CAC4CE]/65 border-[#CAC4CE]/20 opacity-70'
            }`}
          >
            <FileCode className="w-3 h-3 text-[#8D86C9]" />
            <span>Entities (File/Module/Key)</span>
          </button>

          {/* Decision */}
          <button
            onClick={() => toggleFilter('Decision')}
            className={`px-2 py-0.5 rounded-md border flex items-center gap-1.5 transition-colors cursor-pointer text-[11px] ${
              filters.Decision
                ? 'bg-[#9067C6]/20 text-[#F7ECE1] border-[#9067C6]/50 font-semibold'
                : 'bg-[#161324] text-[#CAC4CE]/65 border-[#CAC4CE]/20 opacity-70'
            }`}
          >
            <CheckCircle2 className="w-3 h-3 text-[#C5B0E6]" />
            <span>Decisions</span>
          </button>

          {/* PullRequest */}
          <button
            onClick={() => toggleFilter('PullRequest')}
            className={`px-2 py-0.5 rounded-md border flex items-center gap-1.5 transition-colors cursor-pointer text-[11px] ${
              filters.PullRequest
                ? 'bg-[#AFD2FA]/15 text-[#F7ECE1] border-[#AFD2FA]/45 font-semibold'
                : 'bg-[#161324] text-[#CAC4CE]/65 border-[#CAC4CE]/20 opacity-70'
            }`}
          >
            <GitPullRequest className="w-3 h-3 text-[#AFD2FA]" />
            <span>Pull Requests</span>
          </button>

          {/* Evidence (Hidden by default) */}
          <button
            onClick={() => toggleFilter('Evidence')}
            className={`px-2 py-0.5 rounded-md border flex items-center gap-1.5 transition-colors cursor-pointer text-[11px] ${
              filters.Evidence
                ? 'bg-[#CAC4CE]/20 text-[#F7ECE1] border-[#CAC4CE]/45 font-semibold'
                : 'bg-[#161324] text-[#CAC4CE] border-[#CAC4CE]/20'
            }`}
          >
            {filters.Evidence ? <Eye className="w-3 h-3 text-[#F7ECE1]" /> : <EyeOff className="w-3 h-3 text-[#CAC4CE]" />}
            <span>Evidence {filters.Evidence ? '(Shown)' : '(Hidden)'}</span>
          </button>

          {/* Person (Hidden by default) */}
          <button
            onClick={() => toggleFilter('Person')}
            className={`px-2 py-0.5 rounded-md border flex items-center gap-1.5 transition-colors cursor-pointer text-[11px] ${
              filters.Person
                ? 'bg-[#8D86C9]/20 text-[#F7ECE1] border-[#8D86C9]/45 font-semibold'
                : 'bg-[#161324] text-[#CAC4CE] border-[#CAC4CE]/20'
            }`}
          >
            {filters.Person ? <Eye className="w-3 h-3 text-[#F7ECE1]" /> : <EyeOff className="w-3 h-3 text-[#CAC4CE]" />}
            <span>People {filters.Person ? '(Shown)' : '(Hidden)'}</span>
          </button>

{import.meta.env.DEV && (
          <div className="ml-auto flex items-center gap-2 text-[10px] text-[#CAC4CE]">
            <span className="text-[#CAC4CE] uppercase">Test States:</span>
            <button
              onClick={() => setSimulateOffline((o) => !o)}
              className={`px-2 py-0.5 rounded border text-[10px] font-mono transition-colors cursor-pointer ${
                simulateOffline
                  ? 'bg-[#f85149]/20 text-[#f85149] border-[#f85149]/45 font-bold'
                  : 'bg-[#161324] text-[#CAC4CE] border-[#CAC4CE]/20 hover:text-[#F7ECE1]'
              }`}
            >
              {simulateOffline ? 'Reset Online' : 'Simulate 503'}
            </button>
            <button
              onClick={() => setSimulateTruncated((t) => !t)}
              className={`px-2 py-0.5 rounded border text-[10px] font-mono transition-colors cursor-pointer ${
                simulateTruncated
                  ? 'bg-[#9067C6]/25 text-[#F7ECE1] border-[#9067C6]/50 font-bold'
                  : 'bg-[#161324] text-[#CAC4CE] border-[#CAC4CE]/20 hover:text-[#F7ECE1]'
              }`}
            >
              {simulateTruncated ? 'Reset Ceiling' : 'Simulate Truncated'}
            </button>
          </div>
        )}
        </div>
      </div>

      {/* Truncated Subgraph Notice Banner */}
      {graphData?.truncated && (
        <div className="bg-[#242038] border-b border-[#e3b341]/35 px-4 py-1.5 flex items-center justify-between text-xs font-mono text-[#e3b341] z-10 shrink-0">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-3.5 h-3.5 text-[#e3b341] shrink-0" />
            <span>
              <strong>Truncated Response Notice:</strong> Graph query reached the hard node budget (maximum 80 nodes returned). Some entities or temporal supersessions may not be displayed.
            </span>
          </div>
          <span className="text-[11px] text-[#CAC4CE] hidden sm:inline">
            Focus on an entity using the search bar to inspect focused subgraphs.
          </span>
        </div>
      )}

      {activeQuestion && (
        <div className="shrink-0 border-b border-[#CAC4CE]/15 bg-[#242038]/85 px-4 py-1.5 flex items-center gap-2">
          <span className="text-[10px] font-mono uppercase tracking-wider text-[#C5B0E6] font-semibold shrink-0">
            Graph for latest question:
          </span>
          <p className="truncate text-xs font-mono text-[#F7ECE1]">{activeQuestion.question}</p>
        </div>
      )}

      {!isGraphOffline && !errorMessage && viewMode === 'graph' && graphData && (
        <div className="shrink-0 border-b border-[#CAC4CE]/20 bg-[#242038]/90 px-4 py-2">
          {/* F5: Time-Travel Graph Scrubber (2018 -> 2026) */}
          <div className="flex items-center gap-3 text-xs font-mono">
            <span className="text-[#C5B0E6] font-semibold">⏳ Time-Travel Scrubber:</span>
            <span className="text-[#CAC4CE]">2018</span>
            <input
              type="range"
              min={2018}
              max={2026}
              step={1}
              value={timeTravelYear}
              onChange={(e) => setTimeTravelYear(Number(e.target.value))}
              aria-label="Time-Travel Year Scrubber"
              className="w-44 accent-[#9067C6] cursor-pointer"
            />
            <span className="px-2 py-0.5 rounded bg-[#161324] border border-[#9067C6]/40 text-[#F7ECE1] font-bold">
              ≤ {timeTravelYear}
            </span>
            {timeTravelYear < 2026 && (
              <button
                type="button"
                onClick={() => setTimeTravelYear(2026)}
                className="text-[11px] text-[#CAC4CE] hover:text-[#F7ECE1] underline cursor-pointer"
              >
                Reset to 2026
              </button>
            )}
          </div>
        </div>
      )}

      {/* Main Content Area: Full-bleed Visual Graph or Accessible List or 503 Offline State */}
      <div className="flex-1 min-h-0 relative flex overflow-hidden">
        
        {isLoading ? (
          <div className="flex-1 flex flex-col items-center justify-center p-6 text-center z-10 space-y-3">
            <Loader2 className="w-8 h-8 animate-spin text-[#9067C6]" />
            <p className="text-xs font-mono text-[#CAC4CE]">
              Loading {focusEntityId ? 'focused subgraph' : 'repository graph'}...
            </p>
          </div>
        ) : isGraphOffline ? (
          <div className="flex-1 flex flex-col items-center justify-center p-6 text-center z-10 space-y-4">
            <div className="p-4 rounded-2xl bg-[#242038] text-[#f85149] border border-[#f85149]/35 shadow-lg">
              <Database className="w-10 h-10" />
            </div>

            <div className="max-w-md space-y-2">
              <div className="inline-block px-2.5 py-0.5 rounded-full bg-[#f85149]/15 text-[#f85149] border border-[#f85149]/35 text-xs font-mono font-bold">
                HTTP 503 • Graph Service Offline
              </div>
              <h2 className="text-xl font-bold font-sans text-[#F7ECE1]">
                Graph Database Engine Unavailable
              </h2>
              <p className="text-xs font-mono text-[#CAC4CE] leading-relaxed">
                The graph query service (Neo4j) is currently offline, unconfigured, or unreachable. 
                CodeWhy's local SQLite store remains 100% operational for questions and decision timelines.
              </p>
            </div>

            <div className="flex flex-wrap items-center justify-center gap-3 pt-2 text-xs font-mono">
              <button
                onClick={() => {
                  setSimulateOffline(false);
                  setReloadToken((token) => token + 1);
                }}
                className="px-4 py-2 rounded-xl bg-[#9067C6] hover:bg-[#7B52B3] text-white border border-[#9067C6] font-semibold transition-colors flex items-center gap-2 cursor-pointer shadow-sm"
              >
                <RotateCcw className="w-3.5 h-3.5" />
                <span>Retry Connection</span>
              </button>
            </div>
          </div>
        ) : errorMessage ? (
          /* Error State */
          <div className="flex-1 flex flex-col items-center justify-center p-6 text-center z-10 space-y-3">
            <AlertTriangle className="w-8 h-8 text-[#e3b341]" />
            <h3 className="text-sm font-bold text-[#F7ECE1] font-mono">{errorMessage}</h3>
            <button
              onClick={() => {
                setFocusEntityId(null);
                setReloadToken((token) => token + 1);
              }}
              className="px-3 py-1.5 rounded-xl bg-[#9067C6] hover:bg-[#7B52B3] text-white text-xs font-mono cursor-pointer transition-colors"
            >
              Return to Full Graph
            </button>
          </div>
        ) : !graphData ? (
          <div className="flex-1 flex flex-col items-center justify-center p-6 text-center z-10 space-y-3">
            <GitFork className="w-8 h-8 text-[#8D86C9]" />
            <h3 className="text-sm font-bold text-[#F7ECE1] font-mono">No graph data returned</h3>
            <p className="text-xs font-mono text-[#CAC4CE] max-w-md">
              This repository returned no nodes. Search for an entity, or reload the graph.
            </p>
            <button
              onClick={() => setReloadToken((token) => token + 1)}
              className="px-3 py-1.5 rounded-xl bg-[#9067C6] hover:bg-[#7B52B3] text-white text-xs font-mono cursor-pointer transition-colors"
            >
              Reload Graph
            </button>
          </div>
        ) : viewMode === 'list' ? (
          /* 2. Accessible Screen-Reader Friendly List View */
          <div className="flex-1 overflow-y-auto p-4 sm:p-6 w-full max-w-7xl mx-auto space-y-6">
            <div className="flex items-center justify-between border-b border-[#CAC4CE]/20 pb-3">
              <div>
                <h2 className="text-sm font-mono font-bold uppercase text-[#F7ECE1] tracking-wider">
                  Accessible Node & Relationship View
                </h2>
                <p className="text-xs text-[#CAC4CE] font-mono">
                  Tabular screen-reader accessible inventory of {visibleNodesList.length} visible graph nodes and {visibleEdgesList.length} relationships
                </p>
              </div>

              <span className="text-xs font-mono px-2 py-0.5 rounded bg-[#9067C6]/20 text-[#F7ECE1] border border-[#9067C6]/40">
                ARIA Accessible
              </span>
            </div>

            <div className="rounded-xl border border-[#CAC4CE]/20 bg-[#242038] overflow-hidden text-xs font-mono">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="border-b border-[#CAC4CE]/20 bg-[#161324] text-[#CAC4CE] text-[11px] uppercase tracking-wider">
                    <th className="py-3 px-4">Node Label & ID</th>
                    <th className="py-3 px-4">Type</th>
                    <th className="py-3 px-4">State / Property</th>
                    <th className="py-3 px-4">Connections</th>
                    <th className="py-3 px-4 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#CAC4CE]/15 text-[#CAC4CE]">
                  {visibleNodesList.map((node) => {
                    const deg = nodeDegrees.get(node.id) ?? { inCount: 0, outCount: 0 };
                    return (
                      <tr key={node.id} className="hover:bg-[#322D4D]/60 transition-colors">
                        <td className="py-3 px-4">
                          <div className="font-bold text-[#F7ECE1]">{node.label}</div>
                          <div className="text-[10px] text-[#CAC4CE]/80">{node.id}</div>
                        </td>
                        <td className="py-3 px-4">
                          <span className="px-2 py-0.5 rounded bg-[#161324] text-[#F7ECE1] border border-[#CAC4CE]/25 text-[10px]">
                            {node.type}
                            {node.props?.entity_type ? ` (${node.props.entity_type})` : ''}
                          </span>
                        </td>
                        <td className="py-3 px-4">
                          {node.props?.state && (
                            <span
                              className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                                node.props.state === 'ACTIVE'
                                  ? 'bg-[#9067C6]/20 text-[#F7ECE1] border border-[#9067C6]/45'
                                  : node.props.state === 'SUPERSEDED'
                                  ? 'bg-[#161324] text-[#CAC4CE] border border-[#CAC4CE]/25'
                                  : 'bg-[#f85149]/15 text-[#f85149] border border-[#f85149]/40'
                              }`}
                            >
                              {node.props.state}
                            </span>
                          )}
                          {node.props?.path && (
                            <span className="text-[10px] text-[#CAC4CE] block truncate max-w-xs">{node.props.path}</span>
                          )}
                          {node.props?.number && (
                            <span className="text-[10px] text-[#AFD2FA]">PR #{node.props.number}</span>
                          )}
                        </td>
                        <td className="py-3 px-4 text-[11px] text-[#CAC4CE]">
                          {deg.inCount} in • {deg.outCount} out
                        </td>
                        <td className="py-3 px-4 text-right space-x-2">
                          <button
                            onClick={() => setSelectedNode(node)}
                            className="px-2.5 py-1 rounded bg-[#161324] hover:bg-[#322D4D] text-[#F7ECE1] border border-[#CAC4CE]/25 hover:border-[#8D86C9] text-[10px] cursor-pointer"
                          >
                            Inspect
                          </button>
                          {node.type === 'Decision' && (
                            <button
                              onClick={() => setActiveDecisionDrawerId(node.id)}
                              className="px-2.5 py-1 rounded bg-[#9067C6] hover:bg-[#7B52B3] text-white border border-[#9067C6] text-[10px] cursor-pointer"
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
          /* 3. Interactive React Flow Canvas (Maximized Viewport) */
          <div className="flex-1 w-full h-full min-h-[520px] relative">
            <ReactFlow
              nodes={nodes}
              edges={edges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onInit={(instance) => {
                rfInstanceRef.current = instance;
              }}
              nodeTypes={nodeTypes}
              nodesDraggable
              panOnDrag
              zoomOnScroll
              fitView
              fitViewOptions={{ padding: 0.1, maxZoom: 1.2 }}
              minZoom={0.2}
              maxZoom={2.5}
              defaultViewport={{ x: 0, y: 0, zoom: 1 }}
              className="bg-[#191628]"
              proOptions={{ hideAttribution: true }}
            >
              <Background color="#3A3456" gap={24} size={1.25} />
              <Controls className="codewhy-flow-controls" showInteractive={false} showFitView={false} />
            </ReactFlow>

            {/* Floating Collapsible Legend (keeps canvas height maximized) */}
            <div className="absolute left-14 bottom-4 z-20 max-w-[calc(100%-5rem)]">
              <div className="rounded-xl border border-[#CAC4CE]/25 bg-[#242038]/92 backdrop-blur-md shadow-xl px-3 py-2 text-[10px] font-mono text-[#CAC4CE]">
                <div className="flex items-center justify-between gap-3">
                  <span className="uppercase font-bold tracking-wider text-[#F7ECE1]">Legend</span>
                  <button
                    type="button"
                    onClick={() => setIsLegendOpen((prev) => !prev)}
                    className="text-[#C5B0E6] hover:text-[#F7ECE1] flex items-center gap-0.5 cursor-pointer"
                    aria-expanded={isLegendOpen}
                  >
                    <span>{isLegendOpen ? 'Hide' : 'Show'}</span>
                    {isLegendOpen ? <ChevronDown className="w-3 h-3" /> : <ChevronUp className="w-3 h-3" />}
                  </button>
                </div>
                {isLegendOpen && (
                  <div className="mt-2 pt-2 border-t border-[#CAC4CE]/15 flex flex-wrap items-center gap-x-4 gap-y-1.5">
                    <span className="flex items-center gap-1.5 text-[#F7ECE1]">
                      <span className="w-2.5 h-2.5 rounded-full bg-[#9067C6]" />
                      Decision
                    </span>
                    <span className="flex items-center gap-1.5 text-[#F7ECE1]">
                      <span className="w-2.5 h-2.5 rounded-full bg-[#8D86C9]" />
                      Source File
                    </span>
                    <span className="flex items-center gap-1.5 text-[#F7ECE1]">
                      <span className="w-2.5 h-2.5 rounded-full bg-[#E06C75]" />
                      Commit
                    </span>
                    <span className="flex items-center gap-1.5 text-[#F7ECE1]">
                      <span className="w-2.5 h-2.5 rounded-full bg-[#AFD2FA]" />
                      Pull Request
                    </span>
                    <span className="flex items-center gap-1.5 text-[#F7ECE1]">
                      <span className="w-4 border-t-2 border-dashed border-[#9067C6]" />
                      SUPERSEDES
                    </span>
                    <span className="flex items-center gap-1.5 text-[#F7ECE1]">
                      <span className="w-4 border-t-2 border-[#8D86C9]" />
                      GOVERNS
                    </span>
                    <span className="flex items-center gap-1.5 text-[#F7ECE1]">
                      <span className="w-4 border-t-2 border-[#E06C75]" />
                      DECIDED_IN
                    </span>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* 4. Collapsible Node Detail Inspector Slide-Over Panel */}
        {selectedNode && (
          <aside className="absolute right-4 top-4 bottom-4 w-80 sm:w-96 max-w-[calc(100%-2rem)] border border-[#CAC4CE]/25 rounded-2xl bg-[#242038]/95 backdrop-blur-xl p-5 overflow-y-auto space-y-5 z-30 flex flex-col justify-between shadow-2xl">
            <div className="space-y-4">
              <div className="flex items-center justify-between border-b border-[#CAC4CE]/20 pb-3">
                <span className="text-[10px] font-mono uppercase tracking-wider text-[#CAC4CE] flex items-center gap-1.5 font-bold">
                  <Workflow className="w-3.5 h-3.5 text-[#9067C6]" />
                  Node Inspection
                </span>
                <button
                  onClick={() => setSelectedNode(null)}
                  aria-label="Collapse node inspector"
                  className="p-1 rounded-lg hover:bg-[#322D4D] text-[#CAC4CE] hover:text-[#F7ECE1] transition-colors cursor-pointer"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              {/* Title & Badge */}
              <div className="space-y-1.5">
                <div className="flex items-center gap-2">
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#161324] text-[#F7ECE1] border border-[#CAC4CE]/25">
                    {selectedNode.type}
                  </span>
                  {selectedNode.props?.state && (
                    <span
                      className={`text-[10px] font-mono px-2 py-0.5 rounded font-bold ${
                        selectedNode.props.state === 'ACTIVE'
                          ? 'bg-[#9067C6]/20 text-[#F7ECE1] border border-[#9067C6]/45'
                          : selectedNode.props.state === 'SUPERSEDED'
                          ? 'bg-[#161324] text-[#CAC4CE] border border-[#CAC4CE]/25'
                          : 'bg-[#f85149]/15 text-[#f85149] border border-[#f85149]/40'
                      }`}
                    >
                      {selectedNode.props.state}
                    </span>
                  )}
                </div>

                <h3 className="text-sm font-bold font-mono text-[#F7ECE1] leading-snug">
                  {selectedNode.label}
                </h3>
                <div className="text-[11px] font-mono text-[#CAC4CE] break-all">
                  ID: <code className="text-[#C5B0E6]">{selectedNode.id}</code>
                </div>
              </div>

              {/* Properties table */}
              <div className="space-y-2">
                <span className="text-[10px] font-mono uppercase tracking-wider text-[#CAC4CE] block font-bold">
                  Returned Properties
                </span>
                <div className="p-3 rounded-xl bg-[#161324] border border-[#CAC4CE]/20 space-y-1.5 text-xs font-mono">
                  {Object.entries(selectedNode.props || {}).length > 0 ? (
                    Object.entries(selectedNode.props).map(([k, v]) => (
                      <div key={k} className="flex items-start justify-between gap-2 border-b border-[#CAC4CE]/15 pb-1 last:border-0 last:pb-0">
                        <span className="text-[#CAC4CE] text-[11px]">{k}:</span>
                        <span className="text-[#F7ECE1] text-right truncate max-w-[180px]" title={String(v)}>
                          {String(v)}
                        </span>
                      </div>
                    ))
                  ) : (
                    <span className="text-[#CAC4CE]/70 text-[11px]">No extra properties recorded</span>
                  )}
                </div>
              </div>

              {/* Connected Relationships */}
              <div className="space-y-2">
                <span className="text-[10px] font-mono uppercase tracking-wider text-[#CAC4CE] block font-bold">
                  Relationships ({connectedDetails.inbound.length + connectedDetails.outbound.length})
                </span>

                <div className="space-y-2 max-h-48 overflow-y-auto text-xs font-mono">
                  {connectedDetails.inbound.map((edge, i) => (
                    <div key={`in-${i}`} className="p-2 rounded-lg bg-[#161324] border border-[#CAC4CE]/20 flex items-center justify-between text-[11px]">
                      <span className="text-[#CAC4CE] truncate max-w-[120px]">{edge.source}</span>
                      <span className="text-[#C5B0E6] font-bold px-1.5 py-0.5 rounded bg-[#8D86C9]/20 border border-[#8D86C9]/35 text-[9px]">
                        ──({edge.type})──►
                      </span>
                      <span className="text-[#F7ECE1] font-semibold">this</span>
                    </div>
                  ))}

                  {connectedDetails.outbound.map((edge, i) => (
                    <div key={`out-${i}`} className="p-2 rounded-lg bg-[#161324] border border-[#CAC4CE]/20 flex items-center justify-between text-[11px]">
                      <span className="text-[#F7ECE1] font-semibold">this</span>
                      <span className="text-[#C5B0E6] font-bold px-1.5 py-0.5 rounded bg-[#9067C6]/20 border border-[#9067C6]/35 text-[9px]">
                        ──({edge.type})──►
                      </span>
                      <span className="text-[#CAC4CE] truncate max-w-[120px]">{edge.target}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* Action Buttons */}
            <div className="space-y-2 pt-4 border-t border-[#CAC4CE]/20 text-xs font-mono">
              {selectedNode.type === 'Decision' && (
                <button
                  onClick={() => setActiveDecisionDrawerId(selectedNode.id)}
                  className="w-full py-2 px-3 rounded-xl bg-[#9067C6] hover:bg-[#7B52B3] text-white border border-[#9067C6] font-semibold flex items-center justify-center gap-1.5 transition-all cursor-pointer"
                >
                  <Layers className="w-3.5 h-3.5 text-white" />
                  <span>Open Full Decision Drawer</span>
                </button>
              )}

              {selectedNode.type === 'CodeEntity' && (
                <button
                  onClick={() => {
                    setFocusEntityId(selectedNode.id);
                  }}
                  className="w-full py-2 px-3 rounded-xl bg-[#8D86C9]/25 hover:bg-[#8D86C9]/40 text-[#F7ECE1] border border-[#8D86C9]/50 font-semibold flex items-center justify-center gap-1.5 transition-all cursor-pointer"
                >
                  <Workflow className="w-3.5 h-3.5 text-[#8D86C9]" />
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
