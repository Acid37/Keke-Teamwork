// ──────────────────────────────────────────────────────────────
// 自动生成文件 — 请勿手动修改
// 生成命令: python -m backend.export_schema
// 源定义:  backend/events.py → EVENT_REGISTRY
// ──────────────────────────────────────────────────────────────

// ─── 事件类型常量 ───

export const SESSION_READY = "session.ready";
export const SESSION_LIST = "session.list";
export const SESSION_TITLE_UPDATED = "session.title.updated";
export const AGENT_STATUS = "agent.status";
export const AGENT_STARTED = "agent.started";
export const AGENT_TEXT = "agent.text";
export const AGENT_THINKING = "agent.thinking";
export const AGENT_COMPLETED = "agent.completed";
export const TOOL_CALL = "tool.call";
export const CONSOLE_OUTPUT = "console.output";
export const FILES_CHANGED = "files.changed";
export const RESEARCH_STARTED = "research.started";
export const RESEARCH_RESULT = "research.result";
export const RESEARCH_FAILED = "research.failed";
export const RESEARCH_COMPLETED = "research.completed";
export const HANDOFF_STARTED = "handoff.started";
export const HANDOFF_COMPLETED = "handoff.completed";
export const HANDOFF_FAILED = "handoff.failed";
export const APPROVAL_REQUEST = "approval.request";
export const ERROR = "error";
export const BROWSE_DIRECTORY_RESULT = "browse.directory_result";
export const WORKFLOW_PLAN_SHOWN = "workflow.plan_shown";
export const WORKFLOW_TASK_STARTED = "workflow.task_started";
export const WORKFLOW_TASK_COMPLETED = "workflow.task_completed";
export const WORKFLOW_REVIEW_RESULT = "workflow.review_result";
export const WORKFLOW_COMPLETED = "workflow.completed";

// ─── Payload 接口 ───

export interface SESSION_READYPayload {
  session_id: string;
  title: string;
  phase: string;
  history: Record<string, unknown>[];
  work_dir: string;
  auto_review: boolean;
  yolo_mode: boolean;
  solo_mode: boolean;
  usage?: Record<string, unknown> | null;
  timeline_events: Record<string, unknown>[];
}

export interface SESSION_LISTPayload {
  sessions: Record<string, unknown>[];
}

export interface SESSION_TITLE_UPDATEDPayload {
  session_id: string;
  title: string;
}

export interface AGENT_STATUSPayload {
  phase: string;
  detail?: string | null;
}

export interface AGENT_STARTEDPayload {
  agent_id: string;
  agent_name: string;
  role: string;
  color: string;
  parent_agent_id?: string | null;
  delegated?: boolean | null;
  handoff?: boolean | null;
}

export interface AGENT_TEXTPayload {
  text: string;
  source: string;
  is_final: boolean;
  agent_id?: string | null;
  agent_name?: string | null;
  role?: string | null;
  color?: string | null;
  parent_agent_id?: string | null;
}

export interface AGENT_THINKINGPayload {
  text: string;
  source: string;
  agent_id?: string | null;
  agent_name?: string | null;
  parent_agent_id?: string | null;
}

export interface AGENT_COMPLETEDPayload {
  agent_id: string;
  agent_name: string;
  role: string;
  summary: string;
  usage?: Record<string, unknown> | null;
  parent_agent_id?: string | null;
  delegated?: boolean | null;
  handoff?: boolean | null;
}

export interface TOOL_CALLPayload {
  name: string;
  args: Record<string, unknown>;
  stage: string;
  source: string;
  call_id: string;
  agent_id?: string | null;
  parent_agent_id?: string | null;
  success?: boolean | null;
}

export interface CONSOLE_OUTPUTPayload {
  output: string;
  exit_code?: number | null;
  call_id: string;
  command?: string | null;
}

export interface FILES_CHANGEDPayload {
  summary: string;
  combined_diff: string;
  files: Record<string, unknown>[];
}

export interface RESEARCH_STARTEDPayload {
  agent_id: string;
  agent_name: string;
  role: string;
  parent_agent_id: string;
  task: string;
}

export interface RESEARCH_RESULTPayload {
  agent_id: string;
  agent_name: string;
  role: string;
  parent_agent_id: string;
  task: string;
  text: string;
  timed_out: boolean;
  error?: string | null;
}

export interface RESEARCH_FAILEDPayload {
  agent_id: string;
  agent_name: string;
  role: string;
  parent_agent_id: string;
  task: string;
  text: string;
  timed_out: boolean;
  error?: string | null;
}

export interface RESEARCH_COMPLETEDPayload {
  parent_agent_id: string;
  task: string;
  merged_text: string;
  successful_sources: string[];
  timed_out_sources: string[];
  errored_sources: string[];
  result_count: number;
}

export interface HANDOFF_STARTEDPayload {
  agent_id: string;
  agent_name: string;
  role: string;
  parent_agent_id: string;
  task: string;
}

export interface HANDOFF_COMPLETEDPayload {
  agent_id: string;
  agent_name: string;
  role: string;
  parent_agent_id: string;
  task: string;
  text: string;
}

export interface HANDOFF_FAILEDPayload {
  agent_id: string;
  agent_name: string;
  role: string;
  parent_agent_id: string;
  task: string;
  error: string;
}

export interface APPROVAL_REQUESTPayload {
  request_id: string;
  command: string;
  risk_level?: string | null;
  timeout_seconds: number;
}

export interface ERRORPayload {
  message: string;
  recoverable: boolean;
}

export interface BROWSE_DIRECTORY_RESULTPayload {
  path: string;
  parent?: string | null;
  entries: Record<string, unknown>[];
  error?: string | null;
}

export interface WORKFLOW_PLAN_SHOWNPayload {
  overview: string;
  tasks: Record<string, unknown>[];
  risks: string[];
  total_count: number;
}

export interface WORKFLOW_TASK_STARTEDPayload {
  task_id: string;
  title: string;
  description: string;
  task_index: number;
  total_count: number;
  retry_count: number;
}

export interface WORKFLOW_TASK_COMPLETEDPayload {
  task_id: string;
  title: string;
  status: string;
  files_changed: number;
  completed_count: number;
  total_count: number;
}

export interface WORKFLOW_REVIEW_RESULTPayload {
  task_id: string;
  verdict: string;
  summary: string;
  should_retry: boolean;
  retry_count: number;
}

export interface WORKFLOW_COMPLETEDPayload {
  total_count: number;
  completed_count: number;
  skipped_count: number;
  files_changed: number;
}

// ─── EventMap：事件类型 → payload ───

export interface EventMap {
  "session.ready": SESSION_READYPayload;
  "session.list": SESSION_LISTPayload;
  "session.title.updated": SESSION_TITLE_UPDATEDPayload;
  "agent.status": AGENT_STATUSPayload;
  "agent.started": AGENT_STARTEDPayload;
  "agent.text": AGENT_TEXTPayload;
  "agent.thinking": AGENT_THINKINGPayload;
  "agent.completed": AGENT_COMPLETEDPayload;
  "tool.call": TOOL_CALLPayload;
  "console.output": CONSOLE_OUTPUTPayload;
  "files.changed": FILES_CHANGEDPayload;
  "research.started": RESEARCH_STARTEDPayload;
  "research.result": RESEARCH_RESULTPayload;
  "research.failed": RESEARCH_FAILEDPayload;
  "research.completed": RESEARCH_COMPLETEDPayload;
  "handoff.started": HANDOFF_STARTEDPayload;
  "handoff.completed": HANDOFF_COMPLETEDPayload;
  "handoff.failed": HANDOFF_FAILEDPayload;
  "approval.request": APPROVAL_REQUESTPayload;
  "error": ERRORPayload;
  "browse.directory_result": BROWSE_DIRECTORY_RESULTPayload;
  "workflow.plan_shown": WORKFLOW_PLAN_SHOWNPayload;
  "workflow.task_started": WORKFLOW_TASK_STARTEDPayload;
  "workflow.task_completed": WORKFLOW_TASK_COMPLETEDPayload;
  "workflow.review_result": WORKFLOW_REVIEW_RESULTPayload;
  "workflow.completed": WORKFLOW_COMPLETEDPayload;
}

// ─── 辅助类型 ───

/** 按事件类型名提取 payload 类型 */
export type EventPayloadOf<K extends keyof EventMap> = EventMap[K];

/** 所有事件类型名 */
export type EventType = keyof EventMap;

/** WS 消息结构 */
export interface WSMessage<T extends EventType = EventType> {
  type: T;
  payload: EventMap[T];
}
