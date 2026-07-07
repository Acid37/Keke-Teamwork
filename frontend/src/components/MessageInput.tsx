import { useState, useRef, useCallback, useEffect } from 'react';
import { Send, Square, ChevronDown } from 'lucide-react';
import { useSession } from '../SessionContext';
import type { AgentDefinition } from '../types';

export function MessageInput() {
  const { state, dispatch, sendCommand } = useSession();
  const [text, setText] = useState('');
  const [agents, setAgents] = useState<AgentDefinition[]>([]);
  const [showAgentMenu, setShowAgentMenu] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const autoResize = useCallback(() => {
    const el = textareaRef.current;
    if (el) {
      el.style.height = 'auto';
      el.style.height = Math.min(el.scrollHeight, 200) + 'px';
    }
  }, []);

  useEffect(() => {
    autoResize();
  }, [text, autoResize]);

  // Fetch agents list
  useEffect(() => {
    async function fetchAgents() {
      try {
        const res = await fetch('/api/agents');
        const data = await res.json();
        setAgents(data.agents || []);
      } catch {
        // silent
      }
    }
    fetchAgents();
  }, []);

  // Close menu when clicking outside
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setShowAgentMenu(false);
      }
    }
    if (showAgentMenu) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [showAgentMenu]);

  const selectedAgent = agents.find((a) => a.agent_id === state.selectedAgentId) || agents[0];

  const handleSend = () => {
    const trimmed = text.trim();
    if (!trimmed || state.isProcessing) return;

    // Add user message to local state
    dispatch({
      type: 'ADD_MESSAGE',
      message: {
        id: Date.now().toString(36) + Math.random().toString(36).slice(2, 8),
        role: 'user',
        content: trimmed,
        timestamp: Date.now(),
      },
    });

    const sendUserMessage = () => {
      sendCommand({
        type: 'user.message',
        payload: { text: trimmed, agent_id: state.selectedAgentId },
      });
    };

    if (!state.sessionId) return;
    sendUserMessage();

    setText('');
    dispatch({ type: 'SET_PROCESSING', isProcessing: true });
  };

  const handleStop = () => {
    sendCommand({ type: 'user.interrupt' });
    dispatch({ type: 'SET_PROCESSING', isProcessing: false });
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const selectAgent = (agentId: string) => {
    dispatch({ type: 'SET_SELECTED_AGENT', agentId });
    setShowAgentMenu(false);
  };

  const placeholder = state.isProcessing
    ? '正在执行...'
    : !state.sessionId
      ? '请先打开项目或选择会话...'
    : '输入消息... (Enter 发送, Shift+Enter 换行)';

  const canSend = Boolean(text.trim()) && Boolean(state.sessionId) && !state.isProcessing;

  return (
    <div className="input-area">
      <div className="input-wrapper">
        {/* Agent selector */}
        {agents.length > 1 && (
          <div className="agent-selector" ref={menuRef}>
            <button
              className="agent-selector-btn"
              onClick={() => setShowAgentMenu(!showAgentMenu)}
              title="选择 Agent"
            >
              <div
                className="agent-selector-dot"
                style={{ background: selectedAgent?.color || 'var(--accent)' }}
              />
              <span className="agent-selector-name">
                {selectedAgent?.name || '助手'}
              </span>
              <ChevronDown size={12} />
            </button>
            {showAgentMenu && (
              <div className="agent-selector-menu">
                {agents.map((agent) => (
                  <button
                    key={agent.agent_id}
                    className={`agent-selector-item ${agent.agent_id === state.selectedAgentId ? 'active' : ''}`}
                    onClick={() => selectAgent(agent.agent_id)}
                  >
                    <div
                      className="agent-selector-dot"
                      style={{ background: agent.color }}
                    />
                    <div className="agent-selector-item-info">
                      <span>{agent.name}</span>
                      {agent.description && (
                        <span className="agent-selector-item-desc">{agent.description}</span>
                      )}
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        <textarea
          ref={textareaRef}
          className="message-input"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={state.isProcessing}
          rows={1}
        />
        <div className="input-actions">
          {state.isProcessing ? (
            <button className="btn-icon stop" onClick={handleStop} title="停止">
              <Square size={18} />
            </button>
          ) : (
            <button
              className="btn-icon send"
              onClick={handleSend}
              disabled={!canSend}
              title="发送"
            >
              <Send size={18} />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
