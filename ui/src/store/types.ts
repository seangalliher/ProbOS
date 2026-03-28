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
  position: [number, number, number];
  createdAt?: number;
  activatedAt?: number;
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

export interface ChatMessage {
  id: string;
  role: 'user' | 'system';
  text: string;
  timestamp: number;
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
  role: 'user' | 'agent';
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
  thread_mode: 'inform' | 'discuss' | 'action';  // AD-424
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

// Service status (AD-436)

export interface ServiceStatus {
  name: string;
  status: 'online' | 'offline' | 'degraded';
}
