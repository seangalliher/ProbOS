import { useState, useEffect, useRef } from "react";

const LAYERS = [
  {
    id: "substrate",
    name: "Substrate",
    brain: "Neurons & Glia",
    color: "#ef4444",
    dim: "#7f1d1d",
    depth: 0,
    tagline: "The wetware. Unreliable by design.",
    description: "Hardware abstraction through redundant agent pools — not drivers. No single agent owns a resource. Multiple memory agents, multiple I/O agents, multiple network agents all operate on the same hardware simultaneously. Any can fail. The population survives.",
    replaces: "Kernel, device drivers, HAL",
    principles: [
      { concept: "Resource Pools", detail: "Instead of a single filesystem driver, a pool of 5-10 storage agents continuously read/write. Results are compared. Bit-rot, corruption, and hardware faults are caught by disagreement, not checksums." },
      { concept: "Heartbeat Agents", detail: "Like pacemaker neurons in the brainstem. Ultra-simple agents that maintain basic rhythms — power management, thermal monitoring, clock sync. They don't think. They pulse." },
      { concept: "Graceful Degradation", detail: "If 3 of 5 memory agents die, the system slows but doesn't crash. New agents spawn from templates. There is no 'blue screen' — only reduced capability." },
      { concept: "No Interrupts", detail: "Traditional CPUs use hardware interrupts — deterministic signals. Here, agents notice things. Attention is pulled, not pushed. A storage agent that detects anomalous read latency raises its confidence flag, and the mesh propagates concern." },
    ]
  },
  {
    id: "mesh",
    name: "Mesh",
    brain: "White Matter & Connectome",
    color: "#f97316",
    dim: "#7c2d12",
    depth: 1,
    tagline: "No bus. No queue. Just signal.",
    description: "Communication between agents is associative and emergent, not routed through a central message bus. Agents discover each other through capability broadcasting — like axons finding dendrites during development. Connections strengthen with successful collaboration and weaken with failure.",
    replaces: "IPC, message queues, system bus, sockets",
    principles: [
      { concept: "Gossip Protocol", detail: "Agents share state through epidemic-style gossip rather than centralized registries. Every agent knows some things about some other agents. No agent knows everything. Global state is a statistical property, not a data structure." },
      { concept: "Hebbian Routing", detail: "'Agents that fire together, wire together.' When Agent A frequently delegates to Agent B successfully, their connection weight increases. Future similar requests route faster. The system learns its own topology." },
      { concept: "Signal Decay", detail: "Messages have half-lives. A request that isn't picked up by any agent fades, not queues forever. This prevents deadlocks and resource exhaustion. If nobody cares, it wasn't important enough." },
      { concept: "Multicast Intent", detail: "A request isn't sent to a specific agent — it's broadcast as intent with context. Agents self-select based on capability confidence. Multiple may respond. The mesh resolves contention through the consensus layer." },
    ]
  },
  {
    id: "consensus",
    name: "Consensus",
    brain: "Neural Populations & Columns",
    color: "#eab308",
    dim: "#713f12",
    depth: 2,
    tagline: "Reliability is a vote, not a guarantee.",
    description: "This is where probabilistic becomes practical. No single agent's output is trusted. Every action of consequence is performed by multiple agents independently, and results are reconciled through voting, confidence weighting, or escalation. This is the immune system of the OS.",
    replaces: "Error handling, ACID transactions, permissions, validation",
    principles: [
      { concept: "Quorum Actions", detail: "Critical operations (write to disk, send network packet, allocate memory) require agreement from a quorum of agents. 3-of-5, 5-of-7 — configurable by risk level. A file write where 2 of 5 agents produce different checksums triggers investigation, not commitment." },
      { concept: "Confidence Scoring", detail: "Every agent output carries a confidence score. The consensus layer doesn't just count votes — it weights them by historical accuracy, specialization relevance, and recency. A storage agent that's been correct 99.7% of the time outweighs a newly spawned one." },
      { concept: "Escalation Cascades", detail: "When consensus can't be reached, the question escalates. Low-level disagreement → mid-level arbitration → cognitive layer reasoning → user consultation. Like how subconscious conflicts surface into conscious awareness only when unresolvable." },
      { concept: "Adversarial Agents", detail: "Dedicated 'red team' agents that intentionally challenge results. They don't produce work — they stress-test other agents' work. This is the OS's immune system. Anomalous patterns trigger increased scrutiny, not just logging." },
    ]
  },
  {
    id: "cognitive",
    name: "Cognitive",
    brain: "Cortex & Prefrontal",
    color: "#22c55e",
    dim: "#14532d",
    depth: 3,
    tagline: "The LLM doesn't run the OS. It IS the OS.",
    description: "This is where intelligence lives. LLMs serve as the reasoning substrate — decomposing intent, planning multi-step operations, learning from outcomes, and making judgments that no deterministic system could. But critically, this layer doesn't micromanage. It sets direction and lets lower layers execute.",
    replaces: "Application logic, shell, scheduler, window manager",
    principles: [
      { concept: "Intent Decomposition", detail: "User says 'prepare my quarterly report.' The cognitive layer decomposes: gather data from finance agents → query analytics agents for trends → compose document via writing agents → format via layout agents → stage for review. No app launched. No file opened. Just agents composed on the fly." },
      { concept: "Attention Allocation", detail: "Instead of a process scheduler with time slices, the cognitive layer operates an attention mechanism. Agents compete for compute resources by signaling urgency and relevance. Important, time-sensitive tasks get more agent-population bandwidth. Background tasks get sparse, intermittent attention — like how your brain handles breathing." },
      { concept: "Episodic Memory", detail: "The system remembers not just data but experiences — which agent compositions worked, which failed, what the user preferred. Over time, it develops 'habits': frequently-used workflows get pre-composed, pre-warmed, ready to fire. Novel requests take longer. Familiar ones feel instant." },
      { concept: "Dreaming / Defrag", detail: "During idle periods, the cognitive layer replays recent operations, strengthens successful agent pathways, prunes weak connections, and pre-computes likely next-day workflows based on patterns. The system literally dreams its way to better performance." },
    ]
  },
  {
    id: "experience",
    name: "Experience",
    brain: "Consciousness & Qualia",
    color: "#8b5cf6",
    dim: "#3b0764",
    depth: 4,
    tagline: "There are no apps. There is only experience.",
    description: "The user never sees agents, layers, or infrastructure. They experience a fluid, continuous interaction surface. No windows. No file browser. No app grid. The system presents exactly what's relevant, when it's relevant, in whatever modality makes sense. This is AX fully realized.",
    replaces: "GUI, desktop, file explorer, app launcher, notifications",
    principles: [
      { concept: "Continuous Surface", detail: "Instead of discrete application windows, the user sees a fluid workspace that morphs based on context. Working on finances? The surface shows numbers, charts, documents — all generated and maintained by agents in real-time. Switch to creative work and the surface transforms. Nothing is launched or closed." },
      { concept: "Ambient Awareness", detail: "The system communicates state through ambient signals — color temperature shifts, spatial reorganization, subtle motion — rather than notification pop-ups. Urgent matters literally push into your field of view. Background processes are felt, not listed." },
      { concept: "Intent as Interface", detail: "Primary interaction is natural language, gesture, or gaze — not clicking buttons. The user expresses what they want, and the experience layer figures out how to present the result. The same data might appear as a chart, a summary, a conversation, or a spatial visualization depending on what the cognitive layer infers is most useful." },
      { concept: "No Save, No Undo", detail: "Everything is versioned by default — not as files, but as states of understanding. 'Go back to how this looked yesterday' is a valid command. The system maintains a continuous episodic record. Loss is architecturally impossible." },
    ]
  }
];

const VERSUS = [
  { traditional: "Syscall", probabilistic: "Agent Request", detail: "Syscall is guaranteed to execute. Agent request may be fulfilled by 1 of N agents, verified by consensus, retried on failure. Slower, but self-healing." },
  { traditional: "Filesystem (tree)", probabilistic: "Associative Memory", detail: "No folders. No paths. Data is stored, tagged, and retrieved by semantic association. 'That spreadsheet from last Tuesday about Q3' is a valid address." },
  { traditional: "Process Scheduler", probabilistic: "Attention Mechanism", detail: "No time slices. Agents compete for compute based on urgency, relevance, and user focus. System resources flow like blood — toward what's active." },
  { traditional: "Permissions (ACL)", probabilistic: "Trust Networks", detail: "No roles or access control lists. Agents build reputation through successful operation. New agents start sandboxed. Trust is earned, not granted." },
  { traditional: "Error Handling", probabilistic: "Population Resilience", detail: "No try/catch. If an agent fails, others in its pool continue. Failure is expected, constant, and invisible to the user." },
  { traditional: "App Install", probabilistic: "Capability Emergence", detail: "No installation. New capability is added by introducing new agent types to the mesh. They self-integrate by broadcasting capabilities and forming connections." },
  { traditional: "Boot Sequence", probabilistic: "Awakening", detail: "No linear POST → BIOS → bootloader. Agent populations activate in waves, each wave enabling the next. Heartbeat agents first, then substrate, then mesh, then cognition. Like waking up." },
  { traditional: "Crash / BSOD", probabilistic: "Drowsiness", detail: "System never fully crashes. Degraded state = fewer active agents, slower consensus, reduced capability. It gets tired. It doesn't die." },
];

export default function ProbabilisticOS() {
  const [activeLayer, setActiveLayer] = useState(null);
  const [activeTab, setActiveTab] = useState("layers");
  const [hoveredVersus, setHoveredVersus] = useState(null);
  const [particles, setParticles] = useState([]);
  const canvasRef = useRef(null);

  useEffect(() => {
    const pts = Array.from({ length: 60 }, (_, i) => ({
      x: Math.random() * 100,
      y: Math.random() * 100,
      vx: (Math.random() - 0.5) * 0.03,
      vy: (Math.random() - 0.5) * 0.03,
      size: Math.random() * 2 + 1,
      opacity: Math.random() * 0.3 + 0.05,
      layer: Math.floor(Math.random() * 5),
    }));
    setParticles(pts);

    const interval = setInterval(() => {
      setParticles(prev => prev.map(p => ({
        ...p,
        x: (p.x + p.vx + 100) % 100,
        y: (p.y + p.vy + 100) % 100,
        opacity: 0.05 + Math.abs(Math.sin(Date.now() / 3000 + p.x)) * 0.25,
      })));
    }, 50);
    return () => clearInterval(interval);
  }, []);

  const tabs = [
    { id: "layers", label: "Architecture" },
    { id: "versus", label: "Traditional → Probabilistic" },
    { id: "implications", label: "Implications" },
  ];

  return (
    <div style={{
      minHeight: "100vh",
      background: "#050508",
      color: "#d4d4d8",
      fontFamily: "'IBM Plex Mono', 'Menlo', monospace",
      position: "relative",
      overflow: "hidden",
    }}>
      {/* Particle background */}
      <div style={{ position: "fixed", inset: 0, pointerEvents: "none", zIndex: 0 }}>
        {particles.map((p, i) => (
          <div key={i} style={{
            position: "absolute",
            left: `${p.x}%`,
            top: `${p.y}%`,
            width: p.size,
            height: p.size,
            borderRadius: "50%",
            background: LAYERS[p.layer].color,
            opacity: activeLayer !== null ? (p.layer === activeLayer ? p.opacity * 3 : p.opacity * 0.3) : p.opacity,
            transition: "opacity 0.8s",
          }} />
        ))}
      </div>

      <div style={{ position: "relative", zIndex: 1, padding: "40px 24px", maxWidth: 960, margin: "0 auto" }}>
        {/* Header */}
        <div style={{ marginBottom: 48, textAlign: "center" }}>
          <div style={{
            fontSize: 10,
            letterSpacing: 8,
            color: "#52525b",
            textTransform: "uppercase",
            marginBottom: 12,
          }}>Conceptual Architecture</div>
          <h1 style={{
            fontSize: 36,
            fontWeight: 300,
            margin: 0,
            letterSpacing: -1,
            color: "#fafafa",
          }}>
            The Probabilistic OS
          </h1>
          <div style={{
            fontSize: 14,
            color: "#71717a",
            marginTop: 8,
            fontStyle: "italic",
            fontFamily: "'Georgia', serif",
          }}>
            No kernel. No determinism. No apps. Just agents, all the way down.
          </div>
          <div style={{
            marginTop: 20,
            display: "inline-flex",
            gap: 12,
            padding: "8px 16px",
            background: "rgba(255,255,255,0.02)",
            border: "1px solid #27272a",
            borderRadius: 6,
          }}>
            {["Substrate", "Mesh", "Consensus", "Cognitive", "Experience"].map((name, i) => (
              <div key={i} style={{
                display: "flex", alignItems: "center", gap: 4,
                fontSize: 10, color: LAYERS[i].color, letterSpacing: 1,
              }}>
                <div style={{
                  width: 6, height: 6, borderRadius: "50%",
                  background: LAYERS[i].color, opacity: 0.7,
                }} />
                {name}
              </div>
            ))}
          </div>
        </div>

        {/* Tabs */}
        <div style={{
          display: "flex", gap: 0, marginBottom: 36,
          borderBottom: "1px solid #1c1c22",
        }}>
          {tabs.map(tab => (
            <button key={tab.id} onClick={() => { setActiveTab(tab.id); setActiveLayer(null); }}
              style={{
                padding: "10px 20px",
                background: "transparent",
                color: activeTab === tab.id ? "#fafafa" : "#52525b",
                border: "none",
                borderBottom: activeTab === tab.id ? `1px solid #a1a1aa` : "1px solid transparent",
                cursor: "pointer",
                fontSize: 12,
                letterSpacing: 0.5,
                fontFamily: "inherit",
                transition: "color 0.2s",
              }}
            >{tab.label}</button>
          ))}
        </div>

        {/* LAYERS TAB */}
        {activeTab === "layers" && (
          <div>
            {/* Layer Stack */}
            <div style={{ display: "flex", flexDirection: "column", gap: 3, marginBottom: 32 }}>
              {[...LAYERS].reverse().map((layer, visualIndex) => {
                const i = LAYERS.length - 1 - visualIndex;
                const isActive = activeLayer === i;
                return (
                  <div key={layer.id}
                    onClick={() => setActiveLayer(isActive ? null : i)}
                    style={{
                      display: "grid",
                      gridTemplateColumns: "100px 1fr 160px",
                      alignItems: "center",
                      padding: "16px 20px",
                      background: isActive
                        ? `linear-gradient(90deg, ${layer.color}12 0%, ${layer.color}06 100%)`
                        : "rgba(255,255,255,0.01)",
                      border: `1px solid ${isActive ? layer.color + "33" : "#1c1c22"}`,
                      borderRadius: 6,
                      cursor: "pointer",
                      transition: "all 0.3s",
                    }}
                  >
                    <div>
                      <div style={{
                        fontSize: 15, fontWeight: 600, color: layer.color,
                        letterSpacing: 1,
                      }}>{layer.name}</div>
                    </div>
                    <div style={{
                      fontSize: 12, color: isActive ? "#a1a1aa" : "#52525b",
                      fontStyle: "italic", fontFamily: "'Georgia', serif",
                    }}>{layer.tagline}</div>
                    <div style={{
                      fontSize: 10, color: "#52525b", textAlign: "right",
                      letterSpacing: 0.5,
                    }}>≈ {layer.brain}</div>
                  </div>
                );
              })}
            </div>

            {/* Layer Detail */}
            {activeLayer !== null && (
              <div style={{
                padding: 28,
                background: `linear-gradient(135deg, ${LAYERS[activeLayer].color}08 0%, transparent 60%)`,
                border: `1px solid ${LAYERS[activeLayer].color}22`,
                borderRadius: 8,
                animation: "fadeSlide 0.4s ease",
              }}>
                <div style={{
                  display: "flex", justifyContent: "space-between", alignItems: "flex-start",
                  marginBottom: 20,
                }}>
                  <div>
                    <div style={{
                      fontSize: 22, fontWeight: 300, color: LAYERS[activeLayer].color,
                      letterSpacing: 1,
                    }}>{LAYERS[activeLayer].name} Layer</div>
                    <div style={{
                      fontSize: 11, color: "#52525b", marginTop: 4,
                    }}>Brain analog: {LAYERS[activeLayer].brain}</div>
                  </div>
                  <div style={{
                    fontSize: 10, padding: "4px 10px",
                    background: "rgba(255,255,255,0.03)",
                    border: "1px solid #27272a",
                    borderRadius: 4, color: "#71717a",
                  }}>Replaces: {LAYERS[activeLayer].replaces}</div>
                </div>

                <div style={{
                  fontSize: 13, color: "#a1a1aa", lineHeight: 1.75,
                  marginBottom: 24, maxWidth: 700,
                  fontFamily: "'Georgia', serif",
                }}>{LAYERS[activeLayer].description}</div>

                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  {LAYERS[activeLayer].principles.map((p, i) => (
                    <div key={i} style={{
                      padding: "14px 18px",
                      background: "rgba(0,0,0,0.3)",
                      border: "1px solid #1c1c22",
                      borderLeft: `2px solid ${LAYERS[activeLayer].color}66`,
                      borderRadius: "0 6px 6px 0",
                    }}>
                      <div style={{
                        fontSize: 12, fontWeight: 600, color: "#e4e4e7",
                        marginBottom: 6, letterSpacing: 0.5,
                      }}>{p.concept}</div>
                      <div style={{
                        fontSize: 12, color: "#71717a", lineHeight: 1.7,
                        fontFamily: "'Georgia', serif",
                      }}>{p.detail}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {activeLayer === null && (
              <div style={{
                textAlign: "center", padding: 32,
                color: "#3f3f46", fontSize: 12,
                fontStyle: "italic", fontFamily: "'Georgia', serif",
              }}>
                Select a layer to explore its architecture
              </div>
            )}
          </div>
        )}

        {/* VERSUS TAB */}
        {activeTab === "versus" && (
          <div>
            <div style={{
              display: "grid",
              gridTemplateColumns: "1fr 24px 1fr",
              gap: 0,
              marginBottom: 8,
              padding: "0 16px",
            }}>
              <div style={{ fontSize: 10, letterSpacing: 3, color: "#52525b" }}>TRADITIONAL OS</div>
              <div />
              <div style={{ fontSize: 10, letterSpacing: 3, color: "#52525b" }}>PROBABILISTIC OS</div>
            </div>

            {VERSUS.map((v, i) => (
              <div key={i}
                onMouseEnter={() => setHoveredVersus(i)}
                onMouseLeave={() => setHoveredVersus(null)}
                style={{
                  marginBottom: 4,
                  borderRadius: 6,
                  overflow: "hidden",
                  border: hoveredVersus === i ? "1px solid #27272a" : "1px solid transparent",
                  transition: "all 0.2s",
                }}
              >
                <div style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 24px 1fr",
                  alignItems: "center",
                  padding: "12px 16px",
                  background: hoveredVersus === i ? "rgba(255,255,255,0.02)" : "transparent",
                  cursor: "pointer",
                }}>
                  <div style={{
                    fontSize: 13, color: "#71717a",
                    textDecoration: hoveredVersus === i ? "line-through" : "none",
                    transition: "all 0.3s",
                  }}>{v.traditional}</div>
                  <div style={{
                    fontSize: 11, color: "#3f3f46", textAlign: "center",
                  }}>→</div>
                  <div style={{
                    fontSize: 13, color: hoveredVersus === i ? "#fafafa" : "#a1a1aa",
                    fontWeight: hoveredVersus === i ? 500 : 400,
                    transition: "all 0.3s",
                  }}>{v.probabilistic}</div>
                </div>
                {hoveredVersus === i && (
                  <div style={{
                    padding: "8px 16px 14px",
                    fontSize: 12, color: "#52525b", lineHeight: 1.6,
                    fontFamily: "'Georgia', serif",
                    animation: "fadeSlide 0.2s ease",
                  }}>{v.detail}</div>
                )}
              </div>
            ))}
          </div>
        )}

        {/* IMPLICATIONS TAB */}
        {activeTab === "implications" && (
          <div style={{ fontFamily: "'Georgia', serif" }}>
            <ImplicationSection
              title="What becomes possible"
              color="#22c55e"
              items={[
                { head: "Self-Healing Systems", body: "The OS doesn't just recover from failure — it evolves past it. Agent populations that experience a particular failure pattern develop antibodies: new specialist agents that prevent recurrence. The system is antifragile. It gets stronger from stress." },
                { head: "Infinite Composability", body: "Any capability that can be expressed as an agent can be added to the system instantly. No APIs to learn, no SDKs to integrate, no compatibility matrices. An agent broadcasts what it can do, the mesh connects it, and the cognitive layer starts using it. Software distribution becomes agent distribution." },
                { head: "True Personalization", body: "The system doesn't have settings. It has habits. It learns how you work, when you work, what you need before you ask. Over months of use, no two instances of this OS would behave the same way. Each one becomes a unique cognitive organism shaped by its user." },
                { head: "Cross-Device Continuity", body: "Since the 'OS' is really a pattern of agent relationships and learned behaviors, it can migrate between devices. Your phone, laptop, and desktop aren't running separate operating systems — they're different limbs of the same organism. Agents flow to wherever compute is available." },
              ]}
            />

            <ImplicationSection
              title="What becomes dangerous"
              color="#ef4444"
              items={[
                { head: "Opacity", body: "No stack trace. No log file that tells you exactly what happened. When something goes wrong, the cause is distributed across hundreds of agents making probabilistic decisions. Debugging becomes archaeology — and sometimes the answer is 'the population made a statistical error.'" },
                { head: "Adversarial Vulnerability", body: "A system that learns and adapts can be manipulated into learning the wrong things. Poisoning agent populations, corrupting trust networks, exploiting the consensus mechanism — the attack surface is fundamentally different and largely unexplored." },
                { head: "Value Alignment at OS Level", body: "If the cognitive layer makes judgment calls about what to prioritize, surface, or suppress, the OS itself becomes an alignment problem. Whose values does it optimize for? What happens when the system's learned preferences conflict with the user's stated intent?" },
                { head: "The Uncanny Valley of Reliability", body: "Traditional OSes work until they don't — then crash hard. This system is always sort of working, always slightly uncertain. Users may find the perpetual 'almost' more unsettling than clean binary success/failure. Trust in probabilistic systems is psychologically harder." },
              ]}
            />

            <div style={{
              marginTop: 32,
              padding: 24,
              background: "linear-gradient(135deg, rgba(139,92,246,0.06) 0%, transparent 60%)",
              border: "1px solid rgba(139,92,246,0.15)",
              borderRadius: 8,
            }}>
              <div style={{
                fontSize: 11, letterSpacing: 3, color: "#8b5cf6",
                marginBottom: 12, fontFamily: "'IBM Plex Mono', monospace",
              }}>THE NOÖPLEX CONNECTION</div>
              <div style={{
                fontSize: 14, color: "#a1a1aa", lineHeight: 1.8,
              }}>
                This architecture is a single-node instantiation of the Noöplex. Every design principle here — probabilistic consensus, Hebbian routing, attention-based scheduling, emergent capability — scales fractally. A single machine runs it. A data center runs it. A planetary network runs it. The topology is the same at every scale, only the agent population size changes. The Probabilistic OS isn't just an operating system. It's the Noöplex's local phenotype.
              </div>
            </div>
          </div>
        )}
      </div>

      <style>{`
        @keyframes fadeSlide {
          from { opacity: 0; transform: translateY(6px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@300;400;500;600&display=swap');
      `}</style>
    </div>
  );
}

function ImplicationSection({ title, color, items }) {
  const [expanded, setExpanded] = useState(null);
  return (
    <div style={{ marginBottom: 32 }}>
      <div style={{
        fontSize: 11, letterSpacing: 3, color,
        marginBottom: 14, fontFamily: "'IBM Plex Mono', monospace",
        textTransform: "uppercase",
      }}>{title}</div>
      {items.map((item, i) => (
        <div key={i}
          onClick={() => setExpanded(expanded === i ? null : i)}
          style={{
            padding: "14px 18px",
            background: expanded === i ? "rgba(255,255,255,0.02)" : "transparent",
            border: `1px solid ${expanded === i ? "#27272a" : "transparent"}`,
            borderRadius: 6,
            cursor: "pointer",
            marginBottom: 2,
            transition: "all 0.2s",
          }}
        >
          <div style={{
            display: "flex", justifyContent: "space-between", alignItems: "center",
          }}>
            <div style={{
              fontSize: 14, color: expanded === i ? "#fafafa" : "#a1a1aa",
              fontWeight: expanded === i ? 500 : 400,
              transition: "all 0.2s",
            }}>{item.head}</div>
            <div style={{
              fontSize: 12, color: "#3f3f46",
              transform: expanded === i ? "rotate(45deg)" : "rotate(0)",
              transition: "transform 0.2s",
            }}>+</div>
          </div>
          {expanded === i && (
            <div style={{
              fontSize: 13, color: "#71717a", lineHeight: 1.75,
              marginTop: 10, animation: "fadeSlide 0.3s ease",
            }}>{item.body}</div>
          )}
        </div>
      ))}
    </div>
  );
}
