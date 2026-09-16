import type {
  MemoryGraph as MemoryGraphData,
  MemoryGraphNode,
} from "@lifereel/contracts";
import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";
import { useLayoutEffect, useMemo, useRef, useState } from "react";

interface PositionedNode extends MemoryGraphNode, SimulationNodeDatum {
  x: number;
  y: number;
}

interface PositionedLink extends SimulationLinkDatum<PositionedNode> {
  id: string;
  source: PositionedNode;
  target: PositionedNode;
  relationship: string;
  source_claim_ids: string[];
}

const NODE_COLORS: Record<string, string> = {
  subject: "var(--green)",
  person: "#327c72",
  place: "#b66a2d",
  organization: "#6d6a96",
  event: "var(--vermilion)",
};

function seededRandom() {
  let value = 0x2f6e2b1;
  return () => {
    value = (value * 1664525 + 1013904223) >>> 0;
    return value / 4294967296;
  };
}

function nodeRadius(node: MemoryGraphNode) {
  if (node.kind === "subject") return 30;
  if (node.kind === "event") return 18;
  return 22;
}

function graphNodeLabel(node: MemoryGraphNode) {
  if (node.kind === "event")
    return (
      node.time_text ||
      `${node.label.slice(0, 7)}${node.label.length > 7 ? "…" : ""}`
    );
  return `${node.label.slice(0, 8)}${node.label.length > 8 ? "…" : ""}`;
}

function nodeShape(node: PositionedNode, selected: boolean) {
  const common = {
    fill: NODE_COLORS[node.kind] ?? "var(--muted-foreground)",
    stroke: selected ? "var(--ink)" : "var(--paper)",
    strokeWidth: selected ? 4 : 2,
  };
  if (node.kind === "event") {
    return (
      <rect
        x={-17}
        y={-17}
        width={34}
        height={34}
        rx={3}
        transform="rotate(45)"
        {...common}
      />
    );
  }
  if (node.kind === "organization") {
    return <rect x={-23} y={-19} width={46} height={38} rx={4} {...common} />;
  }
  if (node.kind === "place") {
    return <path d="M 0 -25 L 23 18 L -23 18 Z" {...common} />;
  }
  return <circle r={nodeRadius(node)} {...common} />;
}

export function MemoryGraph({
  graph,
  selectedNodeId,
  onSelectNode,
}: {
  graph: MemoryGraphData;
  selectedNodeId: string;
  onSelectNode: (node: MemoryGraphNode) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(760);

  useLayoutEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const update = () =>
      setWidth(Math.max(300, Math.round(container.clientWidth)));
    update();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(update);
    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  const height = width < 560 ? 460 : 600;
  const layout = useMemo(() => {
    const nodes = graph.nodes.map((node, index) => ({
      ...node,
      x: width / 2 + Math.cos(index * 2.2) * Math.min(width, height) * 0.18,
      y: height / 2 + Math.sin(index * 2.2) * height * 0.18,
    })) as PositionedNode[];
    const byId = new Map(nodes.map((node) => [node.id, node]));
    const links = graph.edges.flatMap((edge) => {
      const source = byId.get(edge.source_id);
      const target = byId.get(edge.target_id);
      return source && target ? [{ ...edge, source, target }] : [];
    }) as PositionedLink[];
    const subjectNode = nodes.find((node) => node.kind === "subject");
    if (subjectNode) {
      subjectNode.fx = width / 2;
      subjectNode.fy = height / 2;
    }
    const simulation = forceSimulation(nodes)
      .randomSource(seededRandom())
      .force(
        "link",
        forceLink<PositionedNode, PositionedLink>(links)
          .id((node) => node.id)
          .distance((link) => (link.target.kind === "event" ? 135 : 115))
          .strength(0.65),
      )
      .force("charge", forceManyBody().strength(-430))
      .force(
        "collision",
        forceCollide<PositionedNode>().radius((node) => nodeRadius(node) + 40),
      )
      .force("center", forceCenter(width / 2, height / 2))
      .stop();
    for (let index = 0; index < 220; index += 1) simulation.tick();
    const margin = 54;
    nodes.forEach((node) => {
      node.x = Math.max(margin, Math.min(width - margin, node.x ?? width / 2));
      node.y = Math.max(
        margin,
        Math.min(height - margin, node.y ?? height / 2),
      );
    });
    return { nodes, links };
  }, [graph, height, width]);
  const dense = layout.nodes.length > 12;

  return (
    <div className="memory-graph-canvas" ref={containerRef}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-labelledby="memory-graph-title memory-graph-description"
      >
        <title id="memory-graph-title">
          {graph.nodes[0]?.label ?? "人物"}的记忆关系图
        </title>
        <desc id="memory-graph-description">
          以主人公为中心，展示采访中提到的人物、地点、组织与事件。可选择节点查看来源。
        </desc>
        <g className="memory-graph-edges">
          {layout.links.map((link) => {
            const middleX = (link.source.x + link.target.x) / 2;
            const middleY = (link.source.y + link.target.y) / 2;
            return (
              <g key={link.id}>
                <line
                  x1={link.source.x}
                  y1={link.source.y}
                  x2={link.target.x}
                  y2={link.target.y}
                />
                {(!dense ||
                  link.target.kind !== "event" ||
                  selectedNodeId === link.target.id) && (
                  <text x={middleX} y={middleY - 5} textAnchor="middle">
                    {link.relationship}
                  </text>
                )}
              </g>
            );
          })}
        </g>
        <g className="memory-graph-nodes">
          {layout.nodes.map((node) => (
            <g
              key={node.id}
              className="memory-graph-node"
              transform={`translate(${node.x},${node.y})`}
              role="button"
              tabIndex={0}
              aria-label={`${node.label}，${node.kind === "subject" ? "主人公" : node.kind === "event" ? "事件" : "关系节点"}`}
              aria-pressed={selectedNodeId === node.id}
              onClick={() => onSelectNode(node)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onSelectNode(node);
                }
              }}
            >
              {nodeShape(node, selectedNodeId === node.id)}
              <text y={nodeRadius(node) + 19} textAnchor="middle">
                {graphNodeLabel(node)}
              </text>
            </g>
          ))}
        </g>
      </svg>
    </div>
  );
}
