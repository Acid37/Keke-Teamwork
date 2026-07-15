// Agent definition types (mirrors backend AgentDefinition)
export interface AgentPermissions {
  allowed_paths: string[] | null;
  denied_paths: string[] | null;
  max_command_risk: 'read_only' | 'normal' | 'dangerous';
  allow_delegation: boolean;
  allow_handoff: boolean;
}

export interface AgentDefinition {
  agent_id: string;
  name: string;
  role: string;
  system_prompt: string;
  provider: string | null;
  model: string | null;
  temperature: number;
  tools: string[];
  max_tool_rounds: number;
  max_context: number | null;
  color: string;
  description: string;
  permissions: AgentPermissions | null;
}

// ─── 多 provider / 多 model ───

export interface APIProvider {
  name: string;
  client_type: 'openai' | 'anthropic' | 'gemini';
  base_url: string;
  api_key?: string;
  api_key_masked?: string;
  enabled: boolean;
}

export interface ModelInfo {
  name: string;
  model_id: string;
  provider_name: string;
  max_context: number | null;
  extra_params: Record<string, any>;
}

export interface ToolInfo {
  name: string;
  description: string;
  parameters: Record<string, any>;
}

// Active agent tracking (for multi-agent status display)
export interface ActiveAgent {
  agent_id: string;
  agent_name: string;
  role: string;
  color: string;
  status: 'running' | 'completed';
}

// Downstream events (server -> client)
export interface WSEvent {
  type: string;
  payload: any;
  session_id: string;
}

export interface SessionReadyPayload {
  session_id: string;
  title: string;
  phase: string;
  history: Message[];
  work_dir?: string;
  auto_review?: boolean;
  yolo_mode?: boolean;
  solo_mode?: boolean;
}

export interface SessionListPayload {
  sessions: SessionInfo[];
}

export interface AgentTextPayload {
  text: string;
  source: string;
  is_final: boolean;
  agent_id?: string;
  agent_name?: string;
  role?: string;
  color?: string;
}

export interface AgentThinkingPayload {
  text: string;
  source: string;
  agent_id?: string;
  agent_name?: string;
}

export interface AgentStatusPayload {
  phase: string;
  detail: string | null;
}

export interface AgentStartedPayload {
  agent_id: string;
  agent_name: string;
  role: string;
  color: string;
}

export interface AgentCompletedPayload {
  agent_id: string;
  agent_name: string;
  role: string;
  summary: string;
  usage: { input_tokens: number; output_tokens: number };
}

export interface ResearchStartedPayload {
  agent_id: string;
  agent_name: string;
  role: string;
  parent_agent_id: string;
  task: string;
}

export interface ResearchResultPayload extends ResearchStartedPayload {
  text: string;
  timed_out: boolean;
  error: string | null;
}

export interface ResearchCompletedPayload {
  parent_agent_id: string;
  task: string;
  merged_text: string;
  successful_sources: string[];
  timed_out_sources: string[];
  errored_sources: string[];
  result_count: number;
}

export interface HandoffStartedPayload {
  agent_id: string;
  agent_name: string;
  role: string;
  parent_agent_id: string;
  task: string;
}

export interface HandoffCompletedPayload extends HandoffStartedPayload {
  text: string;
}

export interface HandoffFailedPayload extends HandoffStartedPayload {
  error: string;
}

export interface ToolCallPayload {
  name: string;
  args: Record<string, any>;
  stage: 'running' | 'completed';
  source: string;
  call_id: string;
  agent_id?: string;
}

export interface ConsoleOutputPayload {
  output: string;
  exit_code: number | null;
  call_id: string;
}

export interface FileChangePayload {
  path: string;
  action: 'create' | 'modify' | 'delete';
  diff_text: string;
}

export interface FilesChangedPayload {
  summary: string;
  combined_diff: string;
  files: FileChangePayload[];
}

export interface ApprovalRequestPayload {
  request_id: string;
  command: string;
  timeout_seconds: number;
}

export interface ErrorPayload {
  message: string;
  recoverable: boolean;
}

// Upstream commands (client -> server)
export interface WSCommand {
  type: string;
  payload?: any;
}

// UI state types
export interface Message {
  id: string;
  role: 'user' | 'assistant' | 'tool' | 'system';
  content: string;
  source?: string;
  agent_id?: string;
  agent_name?: string;
  agent_color?: string;
  tool_calls?: ToolCallInfo[];
  file_changes?: FilesChangedPayload[];
  thinking?: string;
  timestamp: number;
}

export interface ToolCallInfo {
  name: string;
  args: Record<string, any>;
  result?: string;
  success?: boolean;
  call_id: string;
  stage: 'running' | 'completed';
  console_output?: string;
}

export interface SessionInfo {
  session_id: string;
  title: string;
  phase: string;
  created_at: number;
  last_active_at: number;
  work_dir?: string;
}

export type Phase = 'init' | 'researching' | 'thinking' | 'coding' | 'ready' | 'error';

// Appearance configuration (mirrors backend AppearanceConfig)
export interface AppearanceConfig {
  mode: string;            // "dark" | "light" | "auto"
  theme_color: string;     // hex color e.g. "#4a9eff"
  wallpaper: string | null;
  wallpaper_blur: number;  // 0-30
  wallpaper_opacity: number; // 0-1
  font_size: number;       // 12-20
  accent_preset: string;   // preset name or "custom"
}

/** Structured wallpaper state (mirrors GET /api/wallpaper/status). */
export interface WallpaperStatus {
  has_wallpaper: boolean;
  wallpaper_type: 'image' | 'video' | 'none';
  wallpaper_filename: string | null;
  wallpaper_blur: number;
  wallpaper_opacity: number;
}

/** Wallpaper preset (from GET /api/wallpaper/presets). */
export interface WallpaperPreset {
  id: string;
  label: string;
  category: 'dark' | 'light' | 'colorful';
  filename: string;
}

/** Theme color preset (matches Neo-MoFox MD3 palette). */
export interface ThemeColorPreset {
  id: string;
  label: string;
  hex: string;
}
