import React, { useState, useMemo } from 'react';
import type { GraphResponse } from '../types';
import {
  GitFork,
  ZoomIn,
  ZoomOut,
  Maximize2,
  Filter,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';

interface InlineGraphViewerProps {
  graph: GraphResponse | null;
  onSelectDecision?: (decisionId: string) => void;
  activeDecisionId?: string | null;
}

export const InlineGraphViewer: React.FC<InlineGraphViewerProps> = ({
  graph,
  onSelectDecision,
  activeDecisionId,
}) => {
  const [zoom, setZoom] = useState(1);
  const [filterType, setFilterType] = useState<string>('ALL');
  const [isExpanded, setIsExpanded] = useState(false);

  // Node type categories
  const nodeTypes = useMemo(() => {
    if (!graph || !graph.nodes || graph.nodes.length === 0) return ['ALL'];
    const types = new Set(graph.nodes.map((n) => n.type));
    return ['ALL', ...Array.from(types)];
  }, [graph]);

  // Compute simple radial/layered layout positions for nodes
  const layout = useMemo(() => {
    if (!graph || !graph.nodes || graph.nodes.length === 0) return { positions: {}, width: 800, height: 480 };
    const nodes = graph.nodes;
    const width = 800;
    const height = 480;
    const centerX = width / 2;
    const centerY = height / 2;

    // Separate nodes by primary category for concentric circles
    const repoNodes = nodes.filter((n) => n.type === 'Repository');
    const entityNodes = nodes.filter((n) => n.type === 'CodeEntity' || n.type === 'Module' || n.type === 'File' || n.type === 'ConfigKey');
    const decisionNodes = nodes.filter((n) => n.type === 'Decision');
    const prNodes = nodes.filter((n) => n.type === 'PullRequest');
    const otherNodes = nodes.filter(
      (n) => !repoNodes.includes(n) && !entityNodes.includes(n) && !decisionNodes.includes(n) && !prNodes.includes(n)
    );

    const positions: Record<string, { x: number; y: number }> = {};

    // Center: Repository
    repoNodes.forEach((n) => {
      positions[n.id] = { x: centerX, y: centerY };
    });

    // Ring 1: Entities (radius 130)
    const r1 = 130;
    entityNodes.forEach((n, idx) => {
      const angle = (idx / (entityNodes.length || 1)) * 2 * Math.PI;
      positions[n.id] = {
        x: centerX + r1 * Math.cos(angle),
        y: centerY + r1 * Math.sin(angle),
      };
    });

    // Ring 2: Decisions (radius 220)
    const r2 = 220;
    decisionNodes.forEach((n, idx) => {
      const angle = (idx / (decisionNodes.length || 1)) * 2 * Math.PI + 0.3;
      positions[n.id] = {
        x: centerX + r2 * Math.cos(angle),
        y: centerY + r2 * Math.sin(angle),
      };
    });

    // Ring 3: PRs and Others (radius 310)
    const outer = [...prNodes, ...otherNodes];
    const r3 = 310;
    outer.forEach((n, idx) => {
      const angle = (idx / (outer.length || 1)) * 2 * Math.PI + 0.6;
      positions[n.id] = {
        x: centerX + r3 * Math.cos(angle),
        y: centerY + r3 * Math.sin(angle),
      };
    });

    return { positions, width, height };
  }, [graph]);

  if (!graph || !graph.nodes || graph.nodes.length === 0) {
    return null;
  }

  const getNodeColor = (type: string) => {
    if (type === 'Decision') {
      return '#3b82f6';
    }
    switch (type) {
      case 'Repository':
        return '#3b82f6';
      case 'CodeEntity':
      case 'File':
      case 'Module':
      case 'ConfigKey':
        return '#3b82f6';
      case 'Commit':
        return '#3b82f6';
      case 'PullRequest':
        return '#3b82f6';
      case 'Person':
        return '#3b82f6';
      case 'Evidence':
        return '#3b82f6';
      default:
        return '#60a5fa';
    }
  };

  const filteredNodes = graph.nodes.filter((n) => {
    if (filterType === 'ALL') return true;
    return n.type === filterType;
  });

  const visibleNodeIds = new Set(filteredNodes.map((n) => n.id));

  const filteredEdges = graph.edges.filter(
    (e) => visibleNodeIds.has(e.source) && visibleNodeIds.has(e.target)
  );

  return (
    <div className="rounded-2xl border border-[#d7d2c6] bg-[#fffdf8] overflow-hidden shadow-xl transition-all">
      {/* Header Bar */}
      <div className="p-4 border-b border-[#d7d2c6]/80 bg-[#fffdf8]/60 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <div className="p-1.5 rounded-lg bg-cyan-500/10 text-[#54734f] border border-cyan-500/20">
            <GitFork className="w-4 h-4" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-xs font-mono font-bold uppercase tracking-wider text-[#292b25]">
                Decision & Provenance Graph
              </h3>
              <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-cyan-500/15 text-[#54734f] border border-cyan-500/30">
                {graph.nodes.length} nodes • {graph.edges.length} edges
              </span>
            </div>
            <p className="text-[11px] font-mono text-[#77776e]">
              Interactive structural traversal of code entities, decisions, PRs and citations
            </p>
          </div>
        </div>

        {/* Controls */}
        <div className="flex items-center gap-2 text-xs font-mono">
          {/* Node Type Filter */}
          <div className="flex items-center gap-1 bg-[#f5f3ed] p-1 rounded-lg border border-[#d7d2c6]">
            <Filter className="w-3.5 h-3.5 text-[#77776e] ml-1" />
            <select
              value={filterType}
              onChange={(e) => setFilterType(e.target.value)}
              className="bg-transparent text-[#51534b] text-xs px-2 py-0.5 rounded focus:outline-none cursor-pointer"
            >
              {nodeTypes.map((t) => (
                <option key={t} value={t} className="bg-[#fffdf8] text-[#292b25]">
                  {t}
                </option>
              ))}
            </select>
          </div>

          <div className="flex items-center gap-1 bg-[#f5f3ed] p-1 rounded-lg border border-[#d7d2c6]">
            <button
              onClick={() => setZoom((z) => Math.min(z + 0.15, 2))}
              className="p-1 rounded hover:bg-[#efede5] text-[#77776e] hover:text-[#292b25]"
              title="Zoom In"
            >
              <ZoomIn className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={() => setZoom((z) => Math.max(z - 0.15, 0.6))}
              className="p-1 rounded hover:bg-[#efede5] text-[#77776e] hover:text-[#292b25]"
              title="Zoom Out"
            >
              <ZoomOut className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={() => setZoom(1)}
              className="p-1 rounded hover:bg-[#efede5] text-[#77776e] hover:text-[#292b25]"
              title="Reset Zoom"
            >
              <Maximize2 className="w-3.5 h-3.5" />
            </button>
          </div>

          <button
            onClick={() => setIsExpanded((exp) => !exp)}
            className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-[#efede5] hover:bg-slate-700 text-[#51534b] hover:text-[#292b25] transition-colors"
          >
            <span>{isExpanded ? 'Collapse' : 'Expand'}</span>
            {isExpanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
          </button>
        </div>
      </div>

      {/* SVG Canvas Area */}
      <div
        className={`relative w-full bg-[#f5f3ed] transition-all overflow-hidden ${
          isExpanded ? 'h-[540px]' : 'h-[320px]'
        }`}
      >
        <svg
          viewBox={`0 0 ${layout.width} ${layout.height}`}
          className="w-full h-full select-none cursor-grab active:cursor-grabbing"
          style={{ transform: `scale(${zoom})`, transformOrigin: 'center center' }}
        >
          <defs>
            <marker
              id="arrow"
              viewBox="0 0 10 10"
              refX="18"
              refY="5"
              markerWidth="6"
              markerHeight="6"
              orient="auto-start-reverse"
            >
              <path d="M 0 0 L 10 5 L 0 10 z" fill="#77776e" />
            </marker>
          </defs>

          {/* Edges */}
          <g className="edges">
            {filteredEdges.map((e, idx) => {
              const src = layout.positions[e.source];
              const tgt = layout.positions[e.target];
              if (!src || !tgt) return null;

              const isSupersedes = e.type === 'SUPERSEDES';
              const strokeColor = isSupersedes ? '#60a5fa' : '#3b82f6';

              return (
                <g key={idx}>
                  <line
                    x1={src.x}
                    y1={src.y}
                    x2={tgt.x}
                    y2={tgt.y}
                    stroke={strokeColor}
                    strokeWidth={isSupersedes ? 2 : 1.2}
                    strokeDasharray={isSupersedes ? '4 2' : undefined}
                    markerEnd="url(#arrow)"
                    opacity={0.7}
                  />
                </g>
              );
            })}
          </g>

          {/* Nodes */}
          <g className="nodes">
            {filteredNodes.map((n) => {
              const pos = layout.positions[n.id] || { x: 400, y: 240 };
              const color = getNodeColor(n.type);
              const isDecision = n.type === 'Decision';
              const isSelected = activeDecisionId === n.id;

              return (
                <g
                  key={n.id}
                  transform={`translate(${pos.x}, ${pos.y})`}
                  onClick={() => {
                    if (isDecision) {
                      onSelectDecision?.(n.id);
                    }
                  }}
                  className={`${isDecision ? 'cursor-pointer group' : ''}`}
                >
                  {/* Glow ring if selected */}
                  {isSelected && (
                    <circle r="22" fill="none" stroke="#617c50" strokeWidth="3" className="animate-pulse" />
                  )}

                  {/* Node Circle */}
                  <circle
                    r={isDecision ? 16 : 12}
                    fill="#f5f3ed"
                    stroke={color}
                    strokeWidth={isDecision ? 2.5 : 1.5}
                    className="transition-transform group-hover:scale-125"
                  />

                  {/* Center Dot */}
                  <circle r={isDecision ? 5 : 3.5} fill={color} />

                  {/* Label */}
                  <text
                    y={isDecision ? 28 : 22}
                    textAnchor="middle"
                    fill="#51534b"
                    fontSize="9"
                    fontFamily="monospace"
                    className="pointer-events-none drop-shadow"
                  >
                    {n.label.length > 20 ? n.label.slice(0, 18) + '…' : n.label}
                  </text>
                </g>
              );
            })}
          </g>
        </svg>

        {/* Legend */}
        <div className="absolute bottom-2 left-3 flex flex-wrap items-center gap-3 bg-[#f5f3ed]/80 backdrop-blur-md px-3 py-1.5 rounded-lg border border-[#d7d2c6] text-[10px] font-mono text-[#51534b]">
          <span className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-cyan-400" /> Repo
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-blue-500" /> Entity
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-emerald-500" /> Active Dec.
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-slate-500" /> Superseded
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-rose-500" /> Rejected
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-purple-500" /> PR
          </span>
        </div>
      </div>
    </div>
  );
};

