/**
 * 从 SessionContext.tsx 拆分出来的 WS 事件处理器。
 *
 * 每个函数对应一个 WS 事件类型，接收 dispatch / stateRef / 辅助工具，
 * 返回一个 payload 处理闭包。这样做的目的：
 * - 让 SessionContext 的 useEffect 不再是 300 行的巨型函数
 * - 每个 handler 可独立测试
 * - 使用 generated/events.ts 的类型保证前后端协议一致
 */

import type { Dispatch } from 'react';
import type { Message, ToolCallInfo, TimelineEvent, PersistedTimelineEvent, WorkflowPlan, WorkflowTaskProgress, WorkflowTaskResult, WorkflowReviewResult, WorkflowCompleted } from './types';
import type { Action, SessionState } from './SessionContext';
import type { EventMap, EventType } from './generated/events';

// ─── 辅助工具 ───

export function generateId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

function addSystemMessage(dispatch: Dispatch<Action>, content: string): void {
  dispatch({
    type: 'ADD_MESSAGE',
    message: {
      id: generateId(),
      role: 'system',
      content,
      timestamp: Date.now(),
    },
  });
}

function addTimelineEvent(dispatch: Dispatch<Action>, event: Omit<TimelineEvent, 'id' | 'timestamp'>): void {
  dispatch({
    type: 'ADD_TIMELINE_EVENT',
    event: {
      ...event,
      id: generateId(),
      timestamp: Date.now(),
    },
  });
}

/** 确保有一个 streaming message，没有则创建。返回 message id。 */
function ensureStreamingMessage(
  state: SessionState,
  dispatch: Dispatch<Action>,
  source?: string,
): string {
  if (state.streamingMessageId) {
    return state.streamingMessageId;
  }
  const id = generateId();
  const msg: Message = {
    id,
    role: 'assistant',
    content: '',
    source,
    timestamp: Date.now(),
  };
  dispatch({ type: 'ADD_MESSAGE', message: msg });
  dispatch({ type: 'SET_STREAMING_ID', messageId: id });
  return id;
}

// ─── Handler 类型 ───

export interface HandlerContext {
  dispatch: Dispatch<Action>;
  getState: () => SessionState;
  wsSend: (command: { type: string; payload?: unknown }) => void;
}

type Handler<K extends EventType> = (ctx: HandlerContext, payload: EventMap[K]) => void;

// ─── 会话生命周期 ───

const onSessionReady: Handler<'session.ready'> = (ctx, p) => {
  ctx.dispatch({
    type: 'SET_SESSION',
    sessionId: p.session_id,
    title: p.title,
    phase: p.phase,
    history: p.history as unknown as Message[],
    workDir: p.work_dir,
    autoReview: p.auto_review,
    yoloMode: p.yolo_mode,
    soloMode: p.solo_mode,
  });
  ctx.dispatch({ type: 'SET_PROCESSING', isProcessing: false });
  ctx.wsSend({ type: 'session.list' });

  // 从持久化事件恢复 timeline
  const persisted = (p as unknown as { timeline_events?: PersistedTimelineEvent[] }).timeline_events;
  if (persisted && persisted.length > 0) {
    const restored: TimelineEvent[] = persisted.map((e) => {
      const pl = e.payload || {};
      return {
        id: generateId(),
        type: e.type,
        agent_id: pl.agent_id ?? pl.parent_agent_id ?? '',
        agent_name: pl.agent_name ?? pl.parent_agent_id ?? '',
        agent_color: pl.color,
        role: pl.role,
        parent_agent_id: pl.parent_agent_id,
        task: pl.task,
        text: pl.text ?? pl.merged_text,
        error: pl.error,
        timed_out: pl.timed_out,
        timestamp: (e.timestamp ?? Date.now()) * 1000,
      };
    });
    ctx.dispatch({ type: 'SET_TIMELINE_EVENTS', events: restored });
  } else {
    ctx.dispatch({ type: 'CLEAR_TIMELINE' });
  }

  // 持久化 recent projects
  if (p.work_dir) {
    try {
      const prev = JSON.parse(localStorage.getItem('ct-recent-projects') || '[]');
      const next = [p.work_dir, ...prev.filter((q: string) => q !== p.work_dir)].slice(0, 10);
      localStorage.setItem('ct-recent-projects', JSON.stringify(next));
      ctx.dispatch({ type: 'SET_RECENT_PROJECTS', projects: next });
    } catch { /* ignore */ }
  }
};

const onSessionList: Handler<'session.list'> = (ctx, p) => {
  ctx.dispatch({ type: 'SET_SESSIONS', sessions: p.sessions as never });
};

const onSessionTitleUpdated: Handler<'session.title.updated'> = (ctx, p) => {
  ctx.dispatch({ type: 'UPDATE_SESSION_TITLE', sessionId: p.session_id, title: p.title });
};

// ─── Agent 执行 ───

const onAgentStatus: Handler<'agent.status'> = (ctx, p) => {
  ctx.dispatch({ type: 'SET_PHASE', phase: p.phase as SessionState['phase'] });
  // Phases where agent/workflow is idle or paused waiting for user input
  const idlePhases = ['ready', 'completed', 'error', 'init', 'plan_review', 'code_review', 'feedback'];
  if (idlePhases.includes(p.phase)) {
    ctx.dispatch({ type: 'SET_PROCESSING', isProcessing: false });
    ctx.dispatch({ type: 'SET_STREAMING_ID', messageId: null });
  } else {
    ctx.dispatch({ type: 'SET_PROCESSING', isProcessing: true });
  }
};

const onAgentStarted: Handler<'agent.started'> = (ctx, p) => {
  ctx.dispatch({
    type: 'AGENT_STARTED',
    agent: {
      agent_id: p.agent_id,
      agent_name: p.agent_name,
      role: p.role,
      color: p.color,
      status: 'running',
    },
  });
  addTimelineEvent(ctx.dispatch, {
    type: 'agent.started',
    agent_id: p.agent_id,
    agent_name: p.agent_name,
    agent_color: p.color,
    role: p.role,
    parent_agent_id: p.parent_agent_id ?? undefined,
  });
};

const onAgentText: Handler<'agent.text'> = (ctx, p) => {
  const state = ctx.getState();

  if (state.streamingMessageId) {
    ctx.dispatch({ type: 'APPEND_MESSAGE', messageId: state.streamingMessageId, text: p.text });
  } else {
    const id = generateId();
    ctx.dispatch({
      type: 'ADD_MESSAGE',
      message: {
        id,
        role: 'assistant',
        content: p.text,
        source: p.source,
        agent_id: p.agent_id ?? undefined,
        agent_name: p.agent_name ?? undefined,
        agent_color: p.color ?? undefined,
        timestamp: Date.now(),
      },
    });
    ctx.dispatch({ type: 'SET_STREAMING_ID', messageId: id });
  }

  ctx.dispatch({ type: 'SET_PROCESSING', isProcessing: true });

  if (p.is_final) {
    ctx.dispatch({ type: 'SET_STREAMING_ID', messageId: null });
    ctx.dispatch({ type: 'SET_PROCESSING', isProcessing: false });
  }
};

const onAgentThinking: Handler<'agent.thinking'> = (ctx, p) => {
  const state = ctx.getState();
  const targetId = ensureStreamingMessage(state, ctx.dispatch, p.source);
  ctx.dispatch({ type: 'ADD_THINKING', messageId: targetId, text: p.text });
};

const onAgentCompleted: Handler<'agent.completed'> = (ctx, p) => {
  ctx.dispatch({ type: 'AGENT_COMPLETED', agentId: p.agent_id });
  addTimelineEvent(ctx.dispatch, {
    type: 'agent.completed',
    agent_id: p.agent_id,
    agent_name: p.agent_name,
    role: p.role,
    parent_agent_id: p.parent_agent_id ?? undefined,
  });
};

// ─── 工具调用 ───

const onToolCall: Handler<'tool.call'> = (ctx, p) => {
  const state = ctx.getState();
  const targetId = ensureStreamingMessage(state, ctx.dispatch, p.source);

  if (p.stage === 'running') {
    ctx.dispatch({
      type: 'ADD_TOOL_CALL',
      messageId: targetId,
      toolCall: {
        name: p.name,
        args: p.args as Record<string, unknown>,
        call_id: p.call_id,
        stage: 'running',
      },
    });
  } else {
    ctx.dispatch({
      type: 'UPDATE_TOOL_CALL',
      messageId: targetId,
      callId: p.call_id,
      updates: {
        stage: 'completed',
        result: (p.args as Record<string, unknown>)?.result as string | undefined,
        success: p.success ?? undefined,
      },
    });
  }
};

const onConsoleOutput: Handler<'console.output'> = (ctx, p) => {
  const state = ctx.getState();
  for (const msg of state.messages) {
    if (msg.tool_calls?.some((tc: ToolCallInfo) => tc.call_id === p.call_id)) {
      const tc = msg.tool_calls.find((t: ToolCallInfo) => t.call_id === p.call_id);
      ctx.dispatch({
        type: 'UPDATE_TOOL_CALL',
        messageId: msg.id,
        callId: p.call_id,
        updates: {
          console_output: (tc?.console_output || '') + p.output,
        },
      });
      break;
    }
  }
};

// ─── 文件变更 ───

const onFilesChanged: Handler<'files.changed'> = (ctx, p) => {
  const state = ctx.getState();
  const targetId = ensureStreamingMessage(state, ctx.dispatch);
  ctx.dispatch({
    type: 'ADD_FILE_CHANGES',
    messageId: targetId,
    changes: {
      summary: p.summary,
      combined_diff: p.combined_diff,
      files: p.files as never[],
    },
  });
};

// ─── 并行研究 ───

const onResearchStarted: Handler<'research.started'> = (ctx, p) => {
  addTimelineEvent(ctx.dispatch, {
    type: 'research.started',
    agent_id: p.agent_id,
    agent_name: p.agent_name,
    role: p.role,
    parent_agent_id: p.parent_agent_id,
    task: p.task,
  });
};

const onResearchResult: Handler<'research.result'> = (ctx, p) => {
  addTimelineEvent(ctx.dispatch, {
    type: 'research.result',
    agent_id: p.agent_id,
    agent_name: p.agent_name,
    role: p.role,
    parent_agent_id: p.parent_agent_id,
    task: p.task,
    text: p.text,
    timed_out: p.timed_out,
  });
};

const onResearchFailed: Handler<'research.failed'> = (ctx, p) => {
  addTimelineEvent(ctx.dispatch, {
    type: 'research.failed',
    agent_id: p.agent_id,
    agent_name: p.agent_name,
    role: p.role,
    parent_agent_id: p.parent_agent_id,
    task: p.task,
    error: p.error ?? undefined,
    timed_out: p.timed_out,
  });
};

const onResearchCompleted: Handler<'research.completed'> = (ctx, p) => {
  addTimelineEvent(ctx.dispatch, {
    type: 'research.completed',
    agent_id: p.parent_agent_id,
    agent_name: p.parent_agent_id,
    parent_agent_id: p.parent_agent_id,
    task: p.task,
    text: `成功: ${p.successful_sources.join(', ') || '无'} | 超时: ${p.timed_out_sources.join(', ') || '无'} | 异常: ${p.errored_sources.join(', ') || '无'}\n\n${p.merged_text}`,
  });
};

// ─── Handoff ───

const onHandoffStarted: Handler<'handoff.started'> = (ctx, p) => {
  addTimelineEvent(ctx.dispatch, {
    type: 'handoff.started',
    agent_id: p.agent_id,
    agent_name: p.agent_name,
    role: p.role,
    parent_agent_id: p.parent_agent_id,
    task: p.task,
  });
};

const onHandoffCompleted: Handler<'handoff.completed'> = (ctx, p) => {
  addTimelineEvent(ctx.dispatch, {
    type: 'handoff.completed',
    agent_id: p.agent_id,
    agent_name: p.agent_name,
    role: p.role,
    parent_agent_id: p.parent_agent_id,
    task: p.task,
    text: p.text,
  });
};

const onHandoffFailed: Handler<'handoff.failed'> = (ctx, p) => {
  addTimelineEvent(ctx.dispatch, {
    type: 'handoff.failed',
    agent_id: p.agent_id,
    agent_name: p.agent_name,
    role: p.role,
    parent_agent_id: p.parent_agent_id,
    task: p.task,
    error: p.error,
  });
};

// ─── 审批 ───

const onApprovalRequest: Handler<'approval.request'> = (ctx, p) => {
  ctx.dispatch({
    type: 'SET_PENDING_APPROVAL',
    approval: {
      request_id: p.request_id,
      command: p.command,
      risk_level: p.risk_level ?? undefined,
      timeout_seconds: p.timeout_seconds,
    },
  });
};

// ─── 错误 ───

const onError: Handler<'error'> = (ctx, p) => {
  ctx.dispatch({
    type: 'ADD_MESSAGE',
    message: {
      id: generateId(),
      role: 'system',
      content: `Error: ${p.message}`,
      timestamp: Date.now(),
    },
  });
  ctx.dispatch({ type: 'SET_PROCESSING', isProcessing: false });
  ctx.dispatch({ type: 'SET_STREAMING_ID', messageId: null });
};

// ─── 目录浏览 ───

const onBrowseDirectoryResult: Handler<'browse.directory_result'> = (_ctx, _p) => {
  // 目录浏览结果由 UI 组件直接处理，这里不做状态更新
  // 保留 handler 以满足类型完整性
};

// ─── 工作流引擎 ───

const onWorkflowPlanShown: Handler<'workflow.plan_shown'> = (ctx, p) => {
  const plan: WorkflowPlan = {
    overview: p.overview,
    tasks: (p.tasks as unknown as WorkflowPlan['tasks']) || [],
    risks: p.risks || [],
    total_count: p.total_count,
  };
  ctx.dispatch({ type: 'SET_WORKFLOW_PLAN', plan });
  addTimelineEvent(ctx.dispatch, {
    type: 'workflow.plan_shown',
    agent_id: 'planner',
    agent_name: '方案规划师',
    agent_color: '#4a9eff',
    role: 'planner',
    task: plan.overview,
    workflow_plan: plan,
  });
};

const onWorkflowTaskStarted: Handler<'workflow.task_started'> = (ctx, p) => {
  const progress: WorkflowTaskProgress = {
    task_id: p.task_id,
    title: p.title,
    description: p.description,
    task_index: p.task_index,
    total_count: p.total_count,
    retry_count: p.retry_count,
  };
  ctx.dispatch({ type: 'SET_WORKFLOW_TASK_PROGRESS', progress });
  addTimelineEvent(ctx.dispatch, {
    type: 'workflow.task_started',
    agent_id: 'coder',
    agent_name: '编码专家',
    agent_color: '#4caf50',
    role: 'coder',
    task: `${p.title}（任务 ${p.task_index}/${p.total_count}${p.retry_count > 0 ? `，重试第${p.retry_count}次` : ''}）`,
    workflow_task_progress: progress,
  });
};

const onWorkflowTaskCompleted: Handler<'workflow.task_completed'> = (ctx, p) => {
  const result: WorkflowTaskResult = {
    task_id: p.task_id,
    title: p.title,
    status: p.status as 'done' | 'skipped',
    files_changed: p.files_changed,
    completed_count: p.completed_count,
    total_count: p.total_count,
  };
  ctx.dispatch({ type: 'SET_WORKFLOW_TASK_RESULT', result });
  addTimelineEvent(ctx.dispatch, {
    type: 'workflow.task_completed',
    agent_id: 'workflow',
    agent_name: p.status === 'skipped' ? '已跳过' : '已完成',
    agent_color: p.status === 'skipped' ? '#ff9800' : '#4caf50',
    task: `${p.title}（${p.completed_count}/${p.total_count}）`,
    workflow_task_result: result,
  });
};

const onWorkflowReviewResult: Handler<'workflow.review_result'> = (ctx, p) => {
  const review: WorkflowReviewResult = {
    task_id: p.task_id,
    verdict: p.verdict as 'approved' | 'needs_changes' | 'rejected',
    summary: p.summary,
    should_retry: p.should_retry,
    retry_count: p.retry_count,
  };
  ctx.dispatch({ type: 'SET_WORKFLOW_REVIEW', review });
  const colorMap: Record<string, string> = {
    approved: '#4caf50',
    needs_changes: '#ff9800',
    rejected: '#f44336',
  };
  addTimelineEvent(ctx.dispatch, {
    type: 'workflow.review_result',
    agent_id: 'reviewer',
    agent_name: '代码审查员',
    agent_color: colorMap[review.verdict] || '#ffc107',
    role: 'reviewer',
    task: review.summary,
    workflow_review: review,
  });
};

const onWorkflowCompleted: Handler<'workflow.completed'> = (ctx, p) => {
  const completed: WorkflowCompleted = {
    total_count: p.total_count,
    completed_count: p.completed_count,
    skipped_count: p.skipped_count,
    files_changed: p.files_changed,
  };
  ctx.dispatch({ type: 'SET_WORKFLOW_COMPLETED', completed });
  addTimelineEvent(ctx.dispatch, {
    type: 'workflow.completed',
    agent_id: 'workflow',
    agent_name: '工作流完成',
    agent_color: '#4caf50',
    task: `完成 ${p.completed_count}/${p.total_count} 个任务，${p.files_changed} 个文件变更`,
    workflow_completed: completed,
  });
};

// ─── 注册表 ───

/**
 * 所有事件 handler 的注册表。
 * key 是事件类型字符串，value 是 handler 函数。
 * 类型安全由 EventMap 保证。
 */
export const eventHandlers: { [K in EventType]: Handler<K> } = {
  'session.ready': onSessionReady,
  'session.list': onSessionList,
  'session.title.updated': onSessionTitleUpdated,
  'agent.status': onAgentStatus,
  'agent.started': onAgentStarted,
  'agent.text': onAgentText,
  'agent.thinking': onAgentThinking,
  'agent.completed': onAgentCompleted,
  'tool.call': onToolCall,
  'console.output': onConsoleOutput,
  'files.changed': onFilesChanged,
  'research.started': onResearchStarted,
  'research.result': onResearchResult,
  'research.failed': onResearchFailed,
  'research.completed': onResearchCompleted,
  'handoff.started': onHandoffStarted,
  'handoff.completed': onHandoffCompleted,
  'handoff.failed': onHandoffFailed,
  'approval.request': onApprovalRequest,
  'error': onError,
  'browse.directory_result': onBrowseDirectoryResult,
  'workflow.plan_shown': onWorkflowPlanShown,
  'workflow.task_started': onWorkflowTaskStarted,
  'workflow.task_completed': onWorkflowTaskCompleted,
  'workflow.review_result': onWorkflowReviewResult,
  'workflow.completed': onWorkflowCompleted,
} as const;

// ─── 注册入口 ───

/**
 * 将所有事件 handler 注册到 WSClient。
 * 返回一个 unregister 函数，在 useEffect cleanup 时调用。
 */
export function registerEventHandlers(
  ws: {
    on: (eventType: string, handler: (payload: unknown) => void) => () => void;
  },
  ctx: HandlerContext,
): () => void {
  const unregistrators: Array<() => void> = [];

  for (const [eventType, handler] of Object.entries(eventHandlers) as [EventType, Handler<EventType>][]) {
    const unreg = ws.on(eventType, (payload: unknown) => {
      handler(ctx, payload as EventMap[typeof eventType]);
    });
    unregistrators.push(unreg);
  }

  return () => {
    for (const unreg of unregistrators) unreg();
  };
}
