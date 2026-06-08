/* HXI TypeScript types matching Python event schema (AD-255) */

export interface Agent {
  id: string;
  agentType: string;
  callsign: string;  // BF-013
  displayName: string;  // crew role from profile YAML
  pool: string;
  state: 'spawning' | 'active' | 'degraded' | 'recycling';
  confidence: number;
  trust: number;
  tier: 'core' | 'utility' | 'domain';
  isCrew: boolean;
  position: [number, number, number];
  createdAt?: number;
  activatedAt?: number;
  // AD-718c: optional per-agent wake phrase (mirrors AgentProfileData.voiceProfile.
  // wake_phrase). Empty/undefined means no per-agent wake registered.
  voice_profile?: {
    wake_phrase?: string;
  };
}

export interface Connection {
  source: string;
  target: string;
  relType: string;
  weight: number;
}

export interface PoolInfo {
  name: string;
  agentType: string;
  size: number;
  targetSize: number;
}

export interface PoolGroupInfo {
  name: string;
  display_name: string;
  total_agents: number;
  healthy_agents: number;
  health_ratio: number;
  pools: Record<string, { current_size: number; target_size: number; agent_type: string }>;
}

export type SystemMode = 'active' | 'idle' | 'dreaming';

export interface DagNode {
  id: string;
  intent: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  params: Record<string, unknown>;
  dependsOn: string[];
}

export interface SelfModProposal {
  intent_name: string;
  intent_description: string;
  parameters: Record<string, string>;
  original_message: string;
  status: 'proposed' | 'approved' | 'rejected';
}

export interface BuildProposal {
  build_id: string;
  title: string;
  description: string;
  ad_number: number;
  file_changes: Array<{
    path: string;
    content: string;
    mode: 'create' | 'modify';
    after_line: string | null;
  }>;
  change_count: number;
  llm_output: string;
  status: 'generating' | 'review' | 'approved' | 'rejected';
  builder_source?: 'native' | 'visiting';
}

export interface BuildFailureReport {
  build_id: string;
  ad_number: number;
  title: string;
  branch_name: string;
  files_written: string[];
  files_modified: string[];
  failure_category: string;
  failure_summary: string;
  raw_error: string;
  failed_tests: string[];
  error_locations: string[];
  fix_attempts: number;
  fix_descriptions: string[];
  review_result: string;
  review_issues: string[];
  resolution_options: Array<{
    id: string;
    label: string;
    description: string;
  }>;
}

export interface TransporterChunkStatus {
  chunk_id: string;
  description: string;
  target_file: string;
  status: 'pending' | 'executing' | 'done' | 'failed';
}

export interface TransporterProgress {
  phase: 'decomposed' | 'executing' | 'executed' | 'assembled' | 'valid' | 'invalid';
  chunks: TransporterChunkStatus[];
  waves_completed: number;
  total_chunks: number;
  successful: number;
  failed: number;
}

export interface BuildQueueItem {
  id: string;
  title: string;
  ad_number: number;
  status: 'queued' | 'dispatched' | 'building' | 'reviewing' | 'merged' | 'failed';
  priority: number;
  worktree_path: string;
  builder_id: string;
  error: string;
  file_footprint: string[];
  commit_hash: string;
}

export interface MissionControlTask {
  id: string;
  type: 'build' | 'design' | 'diagnostic' | 'assessment';
  title: string;
  department: string;
  status: 'queued' | 'working' | 'review' | 'done' | 'failed';
  agent_type: string;
  agent_id: string;
  started_at: number;
  completed_at: number;
  priority: number;
  ad_number: number;
  error: string;
  metadata: Record<string, unknown>;
}

export interface TaskStepView {
  label: string;
  status: 'pending' | 'in_progress' | 'done' | 'failed';
  started_at: number;
  duration_ms: number;
}

export interface AgentTaskView {
  id: string;
  agent_id: string;
  agent_type: string;
  department: string;
  type: 'build' | 'design' | 'diagnostic' | 'assessment' | 'query';
  title: string;
  status: 'queued' | 'working' | 'review' | 'done' | 'failed';
  steps: TaskStepView[];
  requires_action: boolean;
  action_type: string;
  started_at: number;
  completed_at: number;
  error: string;
  priority: number;
  ad_number: number;
  metadata: Record<string, unknown>;
  step_current: number;
  step_total: number;
}

export interface ArchitectProposalView {
  design_id: string;
  title: string;
  summary: string;
  rationale: string;
  roadmap_ref: string;
  priority: 'high' | 'medium' | 'low';
  dependencies: string[];
  risks: string[];
  build_spec: {
    title: string;
    description: string;
    target_files: string[];
    reference_files: string[];
    test_files: string[];
    ad_number: number;
    constraints: string[];
  };
  llm_output: string;
  status: 'analyzing' | 'review' | 'approved' | 'rejected';
}

export interface ChatAttachment {
  attachment_id: string;
  url: string;
  mime: string;
  sha256: string;
  size_bytes: number;
  // AD-720a (Wave 139): original filename for non-image attachments
  // (drag-drop / file picker). Optional for back-compat with paste path.
  filename?: string;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'agent' | 'system';   // AD-719: was 'user' | 'system'
  text: string;
  timestamp: number;
  // AD-719: per-reply attribution for multi-agent fan-out turns.
  agent_id?: string;
  callsign?: string;
  // AD-720: image attachments paste-uploaded with this turn.
  attachments?: ChatAttachment[];
  selfModProposal?: SelfModProposal;
  buildProposal?: BuildProposal;
  buildFailureReport?: BuildFailureReport;
  architectProposal?: ArchitectProposalView;
}

export interface WSEvent {
  type: string;
  data: Record<string, unknown>;
  timestamp: number;
}

export interface StateSnapshot {
  agents: Array<{
    id: string;
    agent_type: string;
    callsign: string;  // BF-013
    display_name: string;  // BF-026
    pool: string;
    state: string;
    confidence: number;
    trust: number;
    tier: string;
  }>;
  connections: Array<{
    source: string;
    target: string;
    rel_type: string;
    weight: number;
  }>;
  pools: Array<{
    name: string;
    agent_type: string;
    size: number;
    target_size: number;
  }>;
  system_mode: string;
  tc_n: number;
  routing_entropy: number;
  fresh_boot?: boolean;
  pool_groups?: Record<string, PoolGroupInfo>;
  pool_to_group?: Record<string, string>;
  workforce?: {
    work_items: WorkItemView[];
    bookings: BookingView[];
    resources?: BookableResourceView[];
  };
}

// Animation event types for the canvas
export interface TrustUpdateEvent {
  agent_id: string;
  new_score: number;
  success: boolean;
}

export interface HebbianUpdateEvent {
  source: string;
  target: string;
  weight: number;
  rel_type: string;
}

export interface ConsensusEvent {
  intent: string;
  outcome: string;
  approval_ratio: number;
  votes: number;
  shapley: Record<string, number>;
}

export interface SystemModeEvent {
  mode: SystemMode;
  previous: string;
}

export interface AgentStateEvent {
  agent_id: string;
  pool: string;
  state: string;
  confidence: number;
  trust: number;
}

export interface NotificationView {
  id: string;
  agent_id: string;
  agent_type: string;
  department: string;
  notification_type: 'info' | 'action_required' | 'error';
  title: string;
  detail: string;
  action_url: string;
  created_at: number;
  acknowledged: boolean;
}

// Agent Profile Panel types (AD-406)

export interface AgentProfileMessage {
  id: string;
  // AD-809: 'system' added so the /personality slash-command reply
  // can render with distinct styling (subtle dim italic) — see
  // ProfileChatTab message render.
  role: 'user' | 'agent' | 'system';
  text: string;
  timestamp: number;
}

export interface AgentConversation {
  agentId: string;
  messages: AgentProfileMessage[];
  unreadCount: number;
  minimized: boolean;
}

export interface AgentProfileData {
  id: string;
  agentType: string;
  callsign: string;
  displayName: string;
  rank: string;
  agencyLevel: string;
  department: string;
  personality: Record<string, number>;
  specialization: string[];
  trust: number;
  trustHistory: number[];
  confidence: number;
  state: string;
  tier: string;
  pool: string;
  hebbianConnections: { targetId: string; weight: number; relType: string }[];
  memoryCount: number;
  uptime: number;
  proactiveCooldown: number | null;  // Phase 28b: per-agent proactive think cooldown (seconds), null for non-crew (BF-017)
  isCrew: boolean;  // BF-017: true for crew agents, false for utility/infrastructure
  voiceProfile?: {
    voice_name: string;
    pitch: number;
    rate: number;
    volume: number;
    // AD-718c: optional per-agent wake phrase (≤ 50 chars).
    wake_phrase?: string;
  };  // AD-718: per-agent TTS profile
  appearance?: {
    vrm_url: string;
    expression_overrides: Record<string, number>;
    color_palette_hint: string;
    // AD-721d: agent-authored DSL artifact (dict form). Null = not yet proposed
    // OR not yet approved. Captain reviews via CrewAvatarPopout's approval bar.
    dsl?: AvatarDSLDict | null;
  };  // AD-721: per-agent 3D avatar
}

// AD-721d: AvatarDSL — agent-authored appearance artifact (data, not code).
// Mirrors src/probos/avatars/dsl.py. The UI never executes any DSL value;
// it only displays the structured fields and POSTs the dict back on approve.
export interface AvatarDSLDict {
  body: { type: 'slim' | 'average' | 'stocky'; height_cm: number };
  hair: {
    style: 'short' | 'medium' | 'long' | 'ponytail' | 'bun' | 'shaved';
    color_hsl: [number, number, number];
  };
  face: {
    warmth: number;
    jaw: 'soft' | 'neutral' | 'strong';
    eyes: 'round' | 'almond' | 'narrow';
  };
  outfit: {
    style: 'uniform' | 'casual' | 'formal' | 'robe' | 'tactical';
    primary_color: string;
    accents: string[];
  };
  expression_resting: 'neutral' | 'gentle_smile' | 'focused' | 'alert';
  notes: string;
}

// Ward Room types (AD-407)

export interface WardRoomChannel {
  id: string;
  name: string;
  channel_type: 'ship' | 'department' | 'custom' | 'dm';
  department: string;
  created_by: string;
  created_at: number;
  archived: boolean;
  description: string;
}

// AD-574b: in-flight indicator for synchronous DM replies via /api/agent/{id}/chat.
export interface WardRoomDmPending {
  threadId: string;
  captainText: string;
  startedAt: number;
}

export interface WardRoomThread {
  id: string;
  channel_id: string;
  author_id: string;
  title: string;
  body: string;
  created_at: number;
  last_activity: number;
  pinned: boolean;
  locked: boolean;
  thread_mode: 'inform' | 'discuss' | 'action' | 'multi_agent';  // AD-424, AD-719a
  max_responders: number;                          // AD-424
  reply_count: number;
  net_score: number;
  author_callsign: string;
  channel_name: string;
}

export interface WardRoomPost {
  id: string;
  thread_id: string;
  parent_id: string | null;
  author_id: string;
  body: string;
  created_at: number;
  edited_at: number | null;
  deleted: boolean;
  delete_reason: string;
  deleted_by: string;
  net_score: number;
  author_callsign: string;
  children?: WardRoomPost[];
}

export interface WardRoomCredibility {
  agent_id: string;
  total_posts: number;
  total_endorsements: number;
  credibility_score: number;
  restrictions: string[];
}

// Assignment types (AD-408)

export interface Assignment {
  id: string;
  name: string;
  assignment_type: 'bridge' | 'away_team' | 'working_group';
  members: string[];
  created_by: string;
  created_at: number;
  completed_at: number | null;
  mission: string;
  ward_room_channel_id: string;
  status: 'active' | 'completed' | 'dissolved';
}

// Scheduled Task types (Phase 25a)

export interface ScheduledTaskView {
  id: string;
  name: string;
  intent_text: string;
  created_at: number;
  schedule_type: 'once' | 'interval' | 'cron';
  execute_at: number | null;
  interval_seconds: number | null;
  cron_expr: string | null;
  channel_id: string | null;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
  last_result: string | null;
  last_run_at: number | null;
  next_run_at: number | null;
  run_count: number;
  max_runs: number | null;
  created_by: string;
  webhook_name: string | null;
  enabled: boolean;
}

// AD-497: Workforce types (mirrors workforce.py to_dict() shapes)

export interface WorkItemView {
  id: string;
  title: string;
  description: string;
  work_type: string;           // card | task | work_order | duty | incident
  status: string;              // draft | open | scheduled | in_progress | review | done | failed | cancelled | blocked
  priority: number;            // 1 (critical) - 5 (low)
  parent_id: string | null;
  depends_on: string[];
  assigned_to: string | null;  // resource_id (= agent UUID)
  created_by: string;
  created_at: number;
  updated_at: number;
  due_at: number | null;
  estimated_tokens: number;
  actual_tokens: number;
  trust_requirement: number;
  required_capabilities: string[];
  tags: string[];
  metadata: Record<string, unknown>;
  steps: Array<{ label: string; status: string }>;
  verification: string | null;
  schedule: string | null;
  ttl_seconds: number | null;
  template_id: string | null;
}

export interface BookingView {
  id: string;
  resource_id: string;
  work_item_id: string;
  requirement_id: string | null;
  status: string;              // scheduled | active | on_break | completed | cancelled
  start_time: number;
  end_time: number | null;
  actual_start: number | null;
  actual_end: number | null;
  total_tokens_consumed: number;
}

export interface BookableResourceView {
  resource_id: string;
  resource_type: string;       // crew | infrastructure | utility
  agent_type: string;
  callsign: string;
  capacity: number;
  calendar_id: string | null;
  department: string;
  characteristics: Array<{ name: string; value: string }>;
  display_on_board: boolean;
  active: boolean;
}

export type ScrumbanColumn = 'backlog' | 'ready' | 'in_progress' | 'review' | 'done';

// Work Type Registry (AD-498)

export interface WorkTypeDefinitionView {
  type_id: string;
  display_name: string;
  description: string;
  initial_status: string;
  terminal_statuses: string[];
  valid_transitions: Array<{
    from_status: string;
    to_status: string;
    requires_assignment: boolean;
  }>;
  supports_children: boolean;
  verification_required: boolean;
  default_priority: number;
}

export interface WorkItemTemplateView {
  template_id: string;
  name: string;
  description: string;
  work_type: string;
  title_pattern: string;
  category: string;
  estimated_tokens: number;
  default_priority: number;
  tags: string[];
  default_steps: Array<{ label: string; status: string }>;
  variables: string[];
  ttl_seconds: number | null;
}

// Service status (AD-436)

export interface ServiceStatus {
  name: string;
  status: 'online' | 'offline' | 'degraded';
}

// AD-526b: Recreation Game state (Captain vs Crew)
export interface GameState {
  gameId: string;
  gameType: string;
  board: string[];           // 9 cells: "" | "X" | "O"
  currentPlayer: string;     // callsign whose turn ("Captain" or agent callsign)
  status: 'in_progress' | 'won' | 'draw' | 'forfeited';
  winner: string;
  validMoves: string[];
  movesCount: number;
  opponent: string;          // agent callsign
  opponentAgentId: string;
  threadId: string;
}

// AD-513: Crew manifest entry from /api/ontology/crew-manifest
export interface CrewManifestEntry {
  agentType: string;
  callsign: string;
  department: string;
  post: string;
  rank: string;
  trustScore: number;
  agentId: string;
}

// AD-930: crew presence layer
export type PresenceState = 'offline' | 'online' | 'working' | 'in_meeting';
export type CrewPresenceMap = Record<string, PresenceState>;

// AD-618d: Bill System types

export interface BillDefinitionView {
  bill_id: string;
  title: string;
  description: string;
  version: number;
  activation: {
    trigger: string;
    authority: string;
  } | null;
  roles: BillRoleView[];
  steps: BillStepView[];
  step_count: number;
  role_count: number;
}

export interface BillRoleView {
  role_id: string;
  department: string;
  count: string;
  qualifications: string[];
}

export interface BillStepView {
  step_id: string;
  name: string;
  role: string;
  action: string;
  gateway_type: string;
  timeout: number;
}

export interface BillInstanceView {
  id: string;
  bill_id: string;
  bill_title: string;
  bill_version: number;
  status: 'pending' | 'active' | 'completed' | 'failed' | 'cancelled';
  activated_by: string;
  activated_at: number;
  completed_at: number | null;
  activation_data: Record<string, unknown>;
  role_assignments: Record<string, BillRoleAssignmentView>;
  step_states: Record<string, BillStepStateView>;
}

export interface BillRoleAssignmentView {
  agent_id: string;
  agent_type: string;
  callsign: string;
  department: string;
}

export interface BillStepStateView {
  status: 'pending' | 'active' | 'completed' | 'skipped' | 'failed' | 'blocked';
  assigned_agent_id: string | null;
  assigned_agent_callsign: string | null;
  started_at: number | null;
  completed_at: number | null;
  error: string | null;
}

// AD-523b: Crew Notebooks Browser
export interface NotebookFrontmatter {
  author?: string;
  department?: string;
  topic?: string;
  tags?: string[];
  classification?: 'private' | 'department' | 'ship' | 'fleet';
  created?: string;
  updated?: string;
  status?: string;
}

export interface NotebookEntry {
  path: string;                     // e.g. "notebooks/atlas/topic-slug.md"
  frontmatter: NotebookFrontmatter;
}

export interface NotebookAuthor {
  callsign: string;                 // path segment after "notebooks/"
  department: string;               // most common department in this author's entries
  entryCount: number;
}

export interface NotebookDetail {
  path: string;
  frontmatter: NotebookFrontmatter;
  content: string;                  // markdown body
}

export interface NotebookSearchResult {
  path: string;
  frontmatter: NotebookFrontmatter;
  score: number;
  snippet: string;
}

// AD-520: Spatial Knowledge Explorer
export type SpatialViewMode = 'graph' | 'ship';

export interface SpatialSelection {
  kind: 'agent' | 'department' | 'edge';
  id: string;
  payload: Record<string, unknown>;
}

export interface SpatialGraphData {
  nodes: Array<Record<string, unknown>>;
  edges: Array<Record<string, unknown>>;
  generated_at: number;
}

export interface SpatialLayoutData {
  schema_version: number;
  decks: Array<{
    deck_id: string;
    name: string;
    department_id: string | null;
    position: [number, number, number];
    dimensions: [number, number, number];
    accent_color: string;
    post_offsets: Record<string, [number, number, number]>;
  }>;
}

// AD-569g: Behavioral Metrics Dashboard
export interface BehavioralSnapshot {
  timestamp: number;
  frame_diversity_score: number;
  frame_diversity_threads: number;
  department_representation: Record<string, number>;
  synthesis_rate: number;
  synthesis_threads: number;
  total_novel_elements: number;
  cross_dept_trigger_rate: number;
  trigger_pairs: Array<[string, string, number]>;
  trigger_events: number;
  convergence_events: number;
  verified_correct: number;
  verified_incorrect: number;
  unverified: number;
  convergence_correctness_rate: number | null;
  anchor_grounded_rate: number;
  anchor_independence_score: number;
  anchor_analyzed_threads: number;
  threads_analyzed: number;
  behavioral_quality_score: number;
}
