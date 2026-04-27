/* AD-611: 3D force-directed memory graph visualization. */

import React, { useRef, useCallback, useMemo, useState, useEffect } from 'react';
import { Close } from '../icons/Glyphs';
import ForceGraph3D from 'react-force-graph-3d';
import * as THREE from 'three';
import type { MemoryGraphNode, MemoryGraphResponse } from './memoryGraphTypes';
import { EDGE_TYPE_CONFIG } from './memoryGraphTypes';

interface MemoryGraph3DProps {
  data: MemoryGraphResponse;
}

interface GraphNode extends MemoryGraphNode {
  x?: number;
  y?: number;
  z?: number;
}

const MemoryGraph3D: React.FC<MemoryGraph3DProps> = React.memo(({ data }) => {
  const fgRef = useRef<any>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [dimensions, setDimensions] = useState({ width: 400, height: 400 });

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const obs = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      if (width > 0 && height > 0) setDimensions({ width, height });
    });
    obs.observe(el);
    // Initial measurement
    const rect = el.getBoundingClientRect();
    if (rect.width > 0 && rect.height > 0) setDimensions({ width: rect.width, height: rect.height });
    return () => obs.disconnect();
  }, []);

  const graphData = useMemo(() => ({
    nodes: data.nodes as GraphNode[],
    links: data.edges.map(e => ({
      ...e,
      // react-force-graph uses 'source'/'target' which can be ID strings
    })),
  }), [data]);

  const handleNodeClick = useCallback((node: any) => {
    setSelectedNode(node as GraphNode);
    // Focus camera on node
    if (fgRef.current) {
      const distance = 60;
      const distRatio = 1 + distance / Math.hypot(node.x || 0, node.y || 0, node.z || 0);
      fgRef.current.cameraPosition(
        { x: (node.x || 0) * distRatio, y: (node.y || 0) * distRatio, z: (node.z || 0) * distRatio },
        node,
        1000,
      );
    }
  }, []);

  const nodeThreeObject = useCallback((node: any) => {
    const gNode = node as GraphNode;
    const geometry = new THREE.SphereGeometry(gNode.size * 0.5, 16, 12);
    const material = new THREE.MeshPhongMaterial({
      color: gNode.color,
      transparent: true,
      opacity: 0.3 + gNode.activation * 0.7,
      emissive: gNode.activation > 0.7 ? new THREE.Color(gNode.color) : new THREE.Color('#000000'),
      emissiveIntensity: gNode.activation > 0.7 ? 0.4 : 0,
    });
    return new THREE.Mesh(geometry, material);
  }, []);

  const nodeLabel = useCallback((node: any) => {
    const gNode = node as GraphNode;
    const date = new Date(gNode.timestamp * 1000).toLocaleString();
    return `<div style="background:rgba(0,0,0,0.85);padding:8px 12px;border-radius:6px;max-width:300px;font-size:12px;color:#e0e0e0">
      <div style="font-weight:bold;margin-bottom:4px;color:${gNode.color}">${gNode.label}</div>
      <div style="color:#999;font-size:10px">${date}</div>
      <div style="margin-top:4px">Channel: ${gNode.channel || 'unknown'} | Importance: ${gNode.importance}/10</div>
      <div>Activation: ${(gNode.activation * 100).toFixed(0)}% | Source: ${gNode.source}</div>
      ${gNode.participants.length ? `<div>Participants: ${gNode.participants.join(', ')}</div>` : ''}
    </div>`;
  }, []);

  const linkWidth = useCallback((link: any) => {
    return (link.weight || 0.5) * 2;
  }, []);

  return (
    <div ref={containerRef} style={{ position: 'relative', width: '100%', height: '100%' }}>
      <ForceGraph3D
        ref={fgRef}
        width={dimensions.width}
        height={dimensions.height}
        graphData={graphData}
        nodeThreeObject={nodeThreeObject}
        nodeLabel={nodeLabel}
        onNodeClick={handleNodeClick}
        linkColor={(link: any) => link.color || '#444'}
        linkWidth={linkWidth}
        linkOpacity={0.5}
        backgroundColor="#0a0a0a"
        warmupTicks={50}
        cooldownTime={3000}
        d3AlphaDecay={0.02}
        enableNodeDrag={true}
        enableNavigationControls={true}
      />

      {/* Legend */}
      <div style={{
        position: 'absolute', bottom: 12, left: 12,
        background: 'rgba(0,0,0,0.75)', padding: '8px 12px',
        borderRadius: 6, fontSize: 11, color: '#ccc',
        display: 'flex', gap: 12,
      }}>
        {Object.entries(EDGE_TYPE_CONFIG).map(([type, cfg]) => (
          <div key={type} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <div style={{ width: 16, height: 3, background: cfg.color, borderRadius: 1 }} />
            <span>{cfg.label}</span>
          </div>
        ))}
      </div>

      {/* Selected node detail */}
      {selectedNode && (
        <div style={{
          position: 'absolute', top: 12, right: 12,
          background: 'rgba(0,0,0,0.9)', padding: 16,
          borderRadius: 8, maxWidth: 350, maxHeight: '60%',
          overflow: 'auto', fontSize: 12, color: '#e0e0e0',
          border: `1px solid ${selectedNode.color}`,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <span style={{ fontWeight: 'bold', color: selectedNode.color }}>Episode Detail</span>
            <button
              onClick={() => setSelectedNode(null)}
              style={{ background: 'none', border: 'none', color: '#888', cursor: 'pointer', fontSize: 16 }}
            >
              <Close size={14} />
            </button>
          </div>
          <div style={{ marginBottom: 6 }}><b>Input:</b> {selectedNode.user_input}</div>
          {selectedNode.reflection && (
            <div style={{ marginBottom: 6 }}><b>Reflection:</b> {selectedNode.reflection}</div>
          )}
          <div style={{ marginBottom: 6 }}>
            <b>Time:</b> {new Date(selectedNode.timestamp * 1000).toLocaleString()}
          </div>
          <div style={{ marginBottom: 6 }}>
            <b>Agents:</b> {selectedNode.agent_ids.join(', ')}
          </div>
          <div style={{ marginBottom: 6 }}>
            <b>Importance:</b> {selectedNode.importance}/10 | <b>Activation:</b> {(selectedNode.activation * 100).toFixed(0)}%
          </div>
          <div>
            <b>Channel:</b> {selectedNode.channel} | <b>Source:</b> {selectedNode.source}
          </div>
        </div>
      )}
    </div>
  );
});

MemoryGraph3D.displayName = 'MemoryGraph3D';

export default MemoryGraph3D;
