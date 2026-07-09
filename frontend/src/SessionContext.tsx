import React, { createContext, useContext, useReducer, useEffect, useRef, useCallback } from 'react';
import { WSClient } from './ws-client';
import {
  Message,
  SessionInfo,
  Phase,
  ToolCallInfo,
  AgentTextPayload,
  AgentThinkingPayload,
  AgentStatusPayload,
  AgentStartedPayload,
  AgentCompletedPayload,
  ResearchStartedPayload,
  ResearchResultPayload,
  ResearchCompletedPayload,
  ToolCallPayload,
  ConsoleOutputPayload,
  FilesChangedPayload,
  ApprovalRequestPayload,
  ErrorPayload,
  SessionReadyPayload,
  SessionListPayload,
  WSCommand,
  ActiveAgent,
} from './types';

interface SessionState {
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
}

// Try-expr for localStorage init
function loadRecentProjects(): string[] {
  try { return JSON.parse(localStorage.getItem('ct-recent-projects') || '[]'); } catch { return []; }
}

type Action =
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
  | { type: 'SET_PENDING_APPROVAL'; approval: ApprovalRequestPayload | null };

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
};

function generateId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

function normalizeHistory(history: any[] | undefined): Message[] {
  if (!history) return [];
  return history
    .filter((item) => item?.role === 'user' || item?.role === 'assistant')
    .filter((item) => typeof item.content === 'string' && item.content.trim().length > 0)
    .map((item) => ({
      id: item.id || generateId(),
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

function addSystemMessage(dispatch: React.Dispatch<Action>, content: string): void {
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
      return { ...state, sessionId: null, messages: [], streamingMessageId: null, currentToolCall: null, isProcessing: false };

    case 'SET_AUTO_REVIEW':
      return { ...state, autoReview: action.enabled };

    case 'SET_YOLO_MODE':
      return { ...state, yoloMode: action.enabled };

    case 'SET_SOLO_MODE':
      return { ...state, soloMode: action.enabled };

    case 'SET_PENDING_APPROVAL':
      return { ...state, pendingApproval: action.approval };

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

    ws.on('open', () => {
      dispatch({ type: 'SET_CONNECTED', connected: true });
      // Request session list on connect
      ws.send({ type: 'session.list' });
    });

    ws.on('close', () => {
      dispatch({ type: 'SET_CONNECTED', connected: false });
    });

    ws.on('session.list', (payload: SessionListPayload) => {
      dispatch({ type: 'SET_SESSIONS', sessions: payload.sessions });
    });

    ws.on('session.ready', (payload: SessionReadyPayload) => {
      dispatch({
        type: 'SET_SESSION',
        sessionId: payload.session_id,
        title: payload.title,
        phase: payload.phase,
        history: payload.history,
        workDir: payload.work_dir,
        autoReview: payload.auto_review,
        yoloMode: payload.yolo_mode,
        soloMode: payload.solo_mode,
      });
      dispatch({ type: 'SET_PROCESSING', isProcessing: false });
      ws.send({ type: 'session.list' });
      // Persist recent projects
      const wd = payload.work_dir;
      if (wd) {
        try {
          const prev = JSON.parse(localStorage.getItem('ct-recent-projects') || '[]');
          const next = [wd, ...prev.filter((p: string) => p !== wd)].slice(0, 10);
          localStorage.setItem('ct-recent-projects', JSON.stringify(next));
          dispatch({ type: 'SET_RECENT_PROJECTS', projects: next });
        } catch {}
      }
    });

    ws.on('agent.text', (payload: AgentTextPayload) => {
      const current = stateRef.current;

      if (current.streamingMessageId) {
        // Append to existing streaming message
        dispatch({ type: 'APPEND_MESSAGE', messageId: current.streamingMessageId, text: payload.text });
      } else {
        // Create new assistant message with agent identity
        const id = generateId();
        dispatch({
          type: 'ADD_MESSAGE',
          message: {
            id,
            role: 'assistant',
            content: payload.text,
            source: payload.source,
            agent_id: payload.agent_id,
            agent_name: payload.agent_name,
            agent_color: payload.color,
            timestamp: Date.now(),
          },
        });
        dispatch({ type: 'SET_STREAMING_ID', messageId: id });
      }

      dispatch({ type: 'SET_PROCESSING', isProcessing: true });

      if (payload.is_final) {
        dispatch({ type: 'SET_STREAMING_ID', messageId: null });
        dispatch({ type: 'SET_PROCESSING', isProcessing: false });
      }
    });

    ws.on('agent.thinking', (payload: AgentThinkingPayload) => {
      const current = stateRef.current;
      let targetId = current.streamingMessageId;

      if (!targetId) {
        const id = generateId();
        dispatch({
          type: 'ADD_MESSAGE',
          message: {
            id,
            role: 'assistant',
            content: '',
            source: payload.source,
            thinking: '',
            timestamp: Date.now(),
          },
        });
        dispatch({ type: 'SET_STREAMING_ID', messageId: id });
        targetId = id;
      }

      dispatch({ type: 'ADD_THINKING', messageId: targetId, text: payload.text });
    });

    ws.on('agent.status', (payload: AgentStatusPayload) => {
      dispatch({ type: 'SET_PHASE', phase: payload.phase as Phase });

      if (payload.phase === 'ready') {
        dispatch({ type: 'SET_PROCESSING', isProcessing: false });
        dispatch({ type: 'SET_STREAMING_ID', messageId: null });
      } else {
        dispatch({ type: 'SET_PROCESSING', isProcessing: true });
      }
    });

    ws.on('tool.call', (payload: ToolCallPayload) => {
      const current = stateRef.current;
      let targetId = current.streamingMessageId;

      if (!targetId) {
        const id = generateId();
        dispatch({
          type: 'ADD_MESSAGE',
          message: {
            id,
            role: 'assistant',
            content: '',
            source: payload.source,
            timestamp: Date.now(),
          },
        });
        dispatch({ type: 'SET_STREAMING_ID', messageId: id });
        targetId = id;
      }

      if (payload.stage === 'running') {
        dispatch({
          type: 'ADD_TOOL_CALL',
          messageId: targetId,
          toolCall: {
            name: payload.name,
            args: payload.args,
            call_id: payload.call_id,
            stage: 'running',
          },
        });
      } else {
        dispatch({
          type: 'UPDATE_TOOL_CALL',
          messageId: targetId,
          callId: payload.call_id,
          updates: { stage: 'completed', result: payload.args?.result },
        });
      }
    });

    ws.on('console.output', (payload: ConsoleOutputPayload) => {
      const current = stateRef.current;
      // Find the message containing this tool call
      for (const msg of current.messages) {
        if (msg.tool_calls?.some((tc) => tc.call_id === payload.call_id)) {
          dispatch({
            type: 'UPDATE_TOOL_CALL',
            messageId: msg.id,
            callId: payload.call_id,
            updates: {
              console_output: (
                (msg.tool_calls.find((tc) => tc.call_id === payload.call_id)?.console_output || '') +
                payload.output
              ),
            },
          });
          break;
        }
      }
    });

    ws.on('files.changed', (payload: FilesChangedPayload) => {
      const current = stateRef.current;
      let targetId = current.streamingMessageId;

      if (!targetId) {
        const id = generateId();
        dispatch({
          type: 'ADD_MESSAGE',
          message: {
            id,
            role: 'assistant',
            content: '',
            timestamp: Date.now(),
          },
        });
        targetId = id;
      }

      dispatch({ type: 'ADD_FILE_CHANGES', messageId: targetId, changes: payload });
    });

    ws.on('approval.request', (payload: ApprovalRequestPayload) => {
      dispatch({ type: 'SET_PENDING_APPROVAL', approval: payload });
    });

    ws.on('agent.started', (payload: AgentStartedPayload) => {
      dispatch({
        type: 'AGENT_STARTED',
        agent: {
          agent_id: payload.agent_id,
          agent_name: payload.agent_name,
          role: payload.role,
          color: payload.color,
          status: 'running',
        },
      });
    });

    ws.on('agent.completed', (payload: AgentCompletedPayload) => {
      dispatch({ type: 'AGENT_COMPLETED', agentId: payload.agent_id });
    });

    ws.on('research.started', (payload: ResearchStartedPayload) => {
      addSystemMessage(dispatch, `Researcher ${payload.agent_name} 开始研究：${payload.task}`);
    });

    ws.on('research.result', (payload: ResearchResultPayload) => {
      const text = payload.text?.trim() || '(无文本结果)';
      addSystemMessage(dispatch, `Researcher ${payload.agent_name} 返回结果：\n\n${text}`);
    });

    ws.on('research.failed', (payload: ResearchResultPayload) => {
      const reason = payload.timed_out ? '超时' : (payload.error || '未知错误');
      addSystemMessage(dispatch, `Researcher ${payload.agent_name} 失败：${reason}`);
    });

    ws.on('research.completed', (payload: ResearchCompletedPayload) => {
      const status = [
        `完成 ${payload.result_count} 个 researcher`,
        payload.successful_sources.length ? `成功：${payload.successful_sources.join(', ')}` : '',
        payload.timed_out_sources.length ? `超时：${payload.timed_out_sources.join(', ')}` : '',
        payload.errored_sources.length ? `异常：${payload.errored_sources.join(', ')}` : '',
      ].filter(Boolean).join('；');
      addSystemMessage(dispatch, `并行研究完成：${status}\n\n${payload.merged_text}`);
    });

    ws.on('error', (payload: ErrorPayload) => {
      dispatch({
        type: 'ADD_MESSAGE',
        message: {
          id: generateId(),
          role: 'system',
          content: `Error: ${payload.message}`,
          timestamp: Date.now(),
        },
      });
      dispatch({ type: 'SET_PROCESSING', isProcessing: false });
      dispatch({ type: 'SET_STREAMING_ID', messageId: null });
    });

    ws.connect();

    return () => {
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
