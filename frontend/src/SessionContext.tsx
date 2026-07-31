import React, { createContext, useContext, useReducer, useEffect, useRef, useCallback } from 'react';
import { WSClient } from './ws-client';
import {
  Message,
  SessionInfo,
  Phase,
  ToolCallInfo,
  FilesChangedPayload,
  ApprovalRequestPayload,
  WSCommand,
  ActiveAgent,
  TimelineEvent,
  WorkflowPlan,
  WorkflowTaskProgress,
  WorkflowTaskResult,
  WorkflowReviewResult,
  WorkflowCompleted,
} from './types';
import { registerEventHandlers } from './eventHandlers';

export interface SessionState {
  sessionId: string | null;
  phase: Phase;
  messages: Message[];
  sessions: SessionInfo[];
  connected: boolean;
  isProcessing: boolean;
  currentToolCall: ToolCallInfo | null;
  streamingMessageId: string | null;
  activeAgents: Map<string, ActiveAgent>;
  selectedAgentId: string;
  workDir: string | null;
  recentProjects: string[];
  autoReview: boolean;
  yoloMode: boolean;
  soloMode: boolean;
  pendingApproval: ApprovalRequestPayload | null;
  timelineEvents: TimelineEvent[];
  workflowPlan: WorkflowPlan | null;
  workflowTaskProgress: WorkflowTaskProgress | null;
  workflowTaskResult: WorkflowTaskResult | null;
  workflowReview: WorkflowReviewResult | null;
  workflowCompleted: WorkflowCompleted | null;
}

// Try-expr for localStorage init
function loadRecentProjects(): string[] {
  try { return JSON.parse(localStorage.getItem('ct-recent-projects') || '[]'); } catch { return []; }
}

export type Action =
  | { type: 'SET_SESSION'; sessionId: string; title: string; phase: string; history?: Message[]; workDir?: string; autoReview?: boolean; yoloMode?: boolean; soloMode?: boolean }
  | { type: 'ADD_MESSAGE'; message: Message }
  | { type: 'UPDATE_MESSAGE'; messageId: string; content: string }
  | { type: 'APPEND_MESSAGE'; messageId: string; text: string }
  | { type: 'ADD_THINKING'; messageId: string; text: string }
  | { type: 'ADD_TOOL_CALL'; messageId: string; toolCall: ToolCallInfo }
  | { type: 'UPDATE_TOOL_CALL'; messageId: string; callId: string; updates: Partial<ToolCallInfo> }
  | { type: 'ADD_FILE_CHANGES'; messageId: string; changes: FilesChangedPayload }
  | { type: 'SET_PHASE'; phase: Phase }
  | { type: 'SET_CONNECTED'; connected: boolean }
  | { type: 'SET_PROCESSING'; isProcessing: boolean }
  | { type: 'SET_SESSIONS'; sessions: SessionInfo[] }
  | { type: 'UPDATE_SESSION_TITLE'; sessionId: string; title: string }
  | { type: 'CLEAR_MESSAGES' }
  | { type: 'SET_STREAMING_ID'; messageId: string | null }
  | { type: 'AGENT_STARTED'; agent: ActiveAgent }
  | { type: 'AGENT_COMPLETED'; agentId: string }
  | { type: 'SET_SELECTED_AGENT'; agentId: string }
  | { type: 'SET_WORK_DIR'; workDir: string | null }
  | { type: 'SET_RECENT_PROJECTS'; projects: string[] }
  | { type: 'RESET_SESSION' }
  | { type: 'SET_AUTO_REVIEW'; enabled: boolean }
  | { type: 'SET_YOLO_MODE'; enabled: boolean }
  | { type: 'SET_SOLO_MODE'; enabled: boolean }
  | { type: 'SET_PENDING_APPROVAL'; approval: ApprovalRequestPayload | null }
  | { type: 'ADD_TIMELINE_EVENT'; event: TimelineEvent }
  | { type: 'SET_TIMELINE_EVENTS'; events: TimelineEvent[] }
  | { type: 'CLEAR_TIMELINE' }
  | { type: 'SET_WORKFLOW_PLAN'; plan: WorkflowPlan }
  | { type: 'SET_WORKFLOW_TASK_PROGRESS'; progress: WorkflowTaskProgress }
  | { type: 'SET_WORKFLOW_TASK_RESULT'; result: WorkflowTaskResult }
  | { type: 'SET_WORKFLOW_REVIEW'; review: WorkflowReviewResult }
  | { type: 'SET_WORKFLOW_COMPLETED'; completed: WorkflowCompleted }
  | { type: 'RESET_WORKFLOW' };

const initialState: SessionState = {
  sessionId: null,
  phase: 'init',
  messages: [],
  sessions: [],
  connected: false,
  isProcessing: false,
  currentToolCall: null,
  streamingMessageId: null,
  activeAgents: new Map(),
  selectedAgentId: 'main',
  workDir: null,
  recentProjects: loadRecentProjects(),
  autoReview: true,
  yoloMode: false,
  soloMode: false,
  pendingApproval: null,
  timelineEvents: [],
  workflowPlan: null,
  workflowTaskProgress: null,
  workflowTaskResult: null,
  workflowReview: null,
  workflowCompleted: null,
};

function normalizeHistory(history: any[] | undefined): Message[] {
  if (!history) return [];
  return history
    .filter((item) => item?.role === 'user' || item?.role === 'assistant')
    .filter((item) => typeof item.content === 'string' && item.content.trim().length > 0)
    .map((item) => ({
      id: item.id || (Date.now().toString(36) + Math.random().toString(36).slice(2, 8)),
      role: item.role,
      content: item.content,
      source: item.source,
      agent_id: item.agent_id,
      agent_name: item.agent_name,
      agent_color: item.agent_color,
      tool_calls: item.tool_calls,
      file_changes: item.file_changes,
      thinking: item.thinking,
      timestamp: typeof item.timestamp === 'number' ? item.timestamp : Date.now(),
    }));
}

function reducer(state: SessionState, action: Action): SessionState {
  switch (action.type) {
    case 'SET_SESSION':
      return {
        ...state,
        sessionId: action.sessionId,
        phase: (action.phase as Phase) || 'init',
        messages: normalizeHistory(action.history),
        streamingMessageId: null,
        isProcessing: false,
        workDir: action.workDir ?? state.workDir,
        autoReview: action.autoReview ?? state.autoReview,
        yoloMode: action.yoloMode ?? state.yoloMode,
        soloMode: action.soloMode ?? state.soloMode,
      };

    case 'ADD_MESSAGE':
      return {
        ...state,
        messages: [...state.messages, action.message],
      };

    case 'UPDATE_MESSAGE':
      return {
        ...state,
        messages: state.messages.map((m) =>
          m.id === action.messageId ? { ...m, content: action.content } : m
        ),
      };

    case 'APPEND_MESSAGE':
      return {
        ...state,
        messages: state.messages.map((m) =>
          m.id === action.messageId ? { ...m, content: m.content + action.text } : m
        ),
      };

    case 'ADD_THINKING':
      return {
        ...state,
        messages: state.messages.map((m) =>
          m.id === action.messageId
            ? { ...m, thinking: (m.thinking || '') + action.text }
            : m
        ),
      };

    case 'ADD_TOOL_CALL': {
      return {
        ...state,
        messages: state.messages.map((m) =>
          m.id === action.messageId
            ? { ...m, tool_calls: [...(m.tool_calls || []), action.toolCall] }
            : m
        ),
        currentToolCall: action.toolCall,
      };
    }

    case 'UPDATE_TOOL_CALL':
      return {
        ...state,
        messages: state.messages.map((m) =>
          m.id === action.messageId
            ? {
                ...m,
                tool_calls: (m.tool_calls || []).map((tc) =>
                  tc.call_id === action.callId ? { ...tc, ...action.updates } : tc
                ),
              }
            : m
        ),
        currentToolCall:
          state.currentToolCall?.call_id === action.callId
            ? { ...state.currentToolCall, ...action.updates }
            : state.currentToolCall,
      };

    case 'ADD_FILE_CHANGES':
      return {
        ...state,
        messages: state.messages.map((m) =>
          m.id === action.messageId
            ? { ...m, file_changes: [...(m.file_changes || []), action.changes] }
            : m
        ),
      };

    case 'SET_PHASE':
      return { ...state, phase: action.phase };

    case 'SET_CONNECTED':
      return { ...state, connected: action.connected };

    case 'SET_PROCESSING':
      return { ...state, isProcessing: action.isProcessing };

    case 'SET_SESSIONS':
      return { ...state, sessions: action.sessions };

    case 'UPDATE_SESSION_TITLE':
      return {
        ...state,
        sessions: state.sessions.map((s) =>
          s.session_id === action.sessionId ? { ...s, title: action.title } : s
        ),
      };

    case 'CLEAR_MESSAGES':
      return { ...state, messages: [], streamingMessageId: null };

    case 'SET_STREAMING_ID':
      return { ...state, streamingMessageId: action.messageId };

    case 'AGENT_STARTED': {
      const newAgents = new Map(state.activeAgents);
      newAgents.set(action.agent.agent_id, { ...action.agent, status: 'running' });
      return { ...state, activeAgents: newAgents };
    }

    case 'AGENT_COMPLETED': {
      const newAgents = new Map(state.activeAgents);
      const existing = newAgents.get(action.agentId);
      if (existing) {
        newAgents.set(action.agentId, { ...existing, status: 'completed' });
      }
      return { ...state, activeAgents: newAgents };
    }

    case 'SET_SELECTED_AGENT':
      return { ...state, selectedAgentId: action.agentId };

    case 'SET_WORK_DIR':
      return { ...state, workDir: action.workDir };

    case 'SET_RECENT_PROJECTS':
      return { ...state, recentProjects: action.projects };

    case 'RESET_SESSION':
      return { ...state, sessionId: null, messages: [], streamingMessageId: null, currentToolCall: null, isProcessing: false, timelineEvents: [], workflowPlan: null, workflowTaskProgress: null, workflowTaskResult: null, workflowReview: null, workflowCompleted: null };

    case 'SET_AUTO_REVIEW':
      return { ...state, autoReview: action.enabled };

    case 'SET_YOLO_MODE':
      return { ...state, yoloMode: action.enabled };

    case 'SET_SOLO_MODE':
      return { ...state, soloMode: action.enabled };

    case 'SET_PENDING_APPROVAL':
      return { ...state, pendingApproval: action.approval };

    case 'ADD_TIMELINE_EVENT':
      return { ...state, timelineEvents: [...state.timelineEvents, action.event] };

    case 'SET_TIMELINE_EVENTS':
      return { ...state, timelineEvents: action.events };

    case 'CLEAR_TIMELINE':
      return { ...state, timelineEvents: [] };

    case 'SET_WORKFLOW_PLAN':
      return { ...state, workflowPlan: action.plan, workflowCompleted: null };

    case 'SET_WORKFLOW_TASK_PROGRESS':
      return { ...state, workflowTaskProgress: action.progress };

    case 'SET_WORKFLOW_TASK_RESULT':
      return { ...state, workflowTaskResult: action.result };

    case 'SET_WORKFLOW_REVIEW':
      return { ...state, workflowReview: action.review };

    case 'SET_WORKFLOW_COMPLETED':
      return { ...state, workflowCompleted: action.completed };

    case 'RESET_WORKFLOW':
      return {
        ...state,
        workflowPlan: null,
        workflowTaskProgress: null,
        workflowTaskResult: null,
        workflowReview: null,
        workflowCompleted: null,
      };

    default:
      return state;
  }
}

interface SessionContextValue {
  state: SessionState;
  dispatch: React.Dispatch<Action>;
  sendCommand: (command: WSCommand) => void;
  initSession: (sessionId: string | null, workDir?: string | null) => void;
  openProject: (dir: string) => void;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState);
  const wsRef = useRef<WSClient | null>(null);
  const stateRef = useRef(state);
  stateRef.current = state;

  const sendCommand = useCallback((command: WSCommand) => {
    wsRef.current?.send(command);
  }, []);

  const initSession = useCallback(
    (sessionId: string | null, workDir?: string | null) => {
      const effectiveWorkDir = sessionId ? workDir : (workDir ?? stateRef.current.workDir);
      if (effectiveWorkDir) {
        dispatch({ type: 'SET_WORK_DIR', workDir: effectiveWorkDir });
      }
      wsRef.current?.send({
        type: 'session.init',
        payload: {
          session_id: sessionId,
          ...(sessionId ? {} : { work_dir: effectiveWorkDir || '.' }),
        },
      });
    },
    []
  );

  const openProject = useCallback(
    (dir: string) => {
      dispatch({ type: 'RESET_SESSION' });
      dispatch({ type: 'SET_WORK_DIR', workDir: dir });
      wsRef.current?.send({
        type: 'project.open',
        payload: { working_directory: dir },
      });
    },
    []
  );

  useEffect(() => {
    const ws = new WSClient();
    wsRef.current = ws;

    // 连接状态
    ws.on('open', () => {
      dispatch({ type: 'SET_CONNECTED', connected: true });
      ws.send({ type: 'session.list' });
    });

    ws.on('close', () => {
      dispatch({ type: 'SET_CONNECTED', connected: false });
    });

    // 注册所有业务事件 handler（从 eventHandlers.ts 导入）
    const unregister = registerEventHandlers(ws, {
      dispatch,
      getState: () => stateRef.current,
      wsSend: (cmd) => ws.send(cmd as WSCommand),
    });

    ws.connect();

    return () => {
      unregister();
      ws.disconnect();
    };
  }, []);

  return (
    <SessionContext.Provider value={{ state, dispatch, sendCommand, initSession, openProject }}>
      {children}
    </SessionContext.Provider>
  );
}

export function useSession(): SessionContextValue {
  const ctx = useContext(SessionContext);
  if (!ctx) {
    throw new Error('useSession must be used within a SessionProvider');
  }
  return ctx;
}
