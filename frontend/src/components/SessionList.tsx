import { useState } from 'react';
import { useSession } from '../SessionContext';
import { ChevronDown, ChevronRight, Folder, Plus, MessageSquare, Settings, Trash2 } from 'lucide-react';
import { SettingsDialog } from './SettingsDialog';
import type { AppearanceConfig } from '../types';

interface SessionListProps {
  appearance: AppearanceConfig;
  onAppearanceChange: (config: AppearanceConfig) => void;
}

export function SessionList({ appearance, onAppearanceChange }: SessionListProps) {
  const { state, dispatch, sendCommand, initSession } = useSession();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [collapsedProjects, setCollapsedProjects] = useState<Set<string>>(new Set());

  const handleNewSession = () => {
    if (!state.workDir) return;
    dispatch({ type: 'CLEAR_MESSAGES' });
    initSession(null, state.workDir);
  };

  const handleSelectSession = (sessionId: string) => {
    if (sessionId === state.sessionId) return;
    dispatch({ type: 'CLEAR_MESSAGES' });
    initSession(sessionId);
  };

  const handleDeleteSession = (e: React.MouseEvent, sessionId: string) => {
    e.stopPropagation();
    if (!confirm('确定删除此会话？')) return;
    sendCommand({ type: 'session.delete', payload: { session_id: sessionId } });
    if (state.sessionId === sessionId) {
      dispatch({ type: 'CLEAR_MESSAGES' });
    }
  };

  // Group sessions by work_dir for project-level listing
  const byProject = new Map<string, typeof state.sessions>();
  for (const s of state.sessions) {
    const dir = s.work_dir || '未指定目录';
    const arr = byProject.get(dir) || [];
    arr.push(s);
    byProject.set(dir, arr);
  }

  const toggleProject = (workDir: string) => {
    setCollapsedProjects((prev) => {
      const next = new Set(prev);
      if (next.has(workDir)) next.delete(workDir);
      else next.add(workDir);
      return next;
    });
  };

  const getProjectName = (workDir: string) => (
    workDir.split('\\').pop() || workDir.split('/').pop() || workDir
  );

  return (
    <div className="sidebar">
      <div className="sidebar-header">
        <h2>会话</h2>
        <button
          className="btn-icon"
          onClick={handleNewSession}
          title={state.workDir ? '新建会话' : '请先打开项目'}
          disabled={!state.workDir}
        >
          <Plus size={18} />
        </button>
      </div>

      <div className="session-list">
        {state.sessions.length === 0 && (
          <div style={{ padding: '16px', color: 'var(--text-muted)', fontSize: '13px', textAlign: 'center' }}>
            暂无会话
          </div>
        )}
        {Array.from(byProject.entries()).map(([workDir, sessions]) => {
          const isCollapsed = collapsedProjects.has(workDir);
          const hasActiveSession = sessions.some((session) => session.session_id === state.sessionId);
          return (
            <div key={workDir} className={`session-group ${hasActiveSession ? 'active-project' : ''}`}>
              <button className="session-group-header" onClick={() => toggleProject(workDir)} title={workDir}>
                {isCollapsed ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
                <Folder size={14} className="session-group-icon" />
                <div className="session-group-main">
                  <div className="session-group-name">{getProjectName(workDir)}</div>
                  <div className="session-group-path">{workDir}</div>
                </div>
                <span className="session-group-count">{sessions.length}</span>
              </button>
              {!isCollapsed && (
                <div className="session-group-children">
                  {sessions.map((session) => (
                    <div
                      key={session.session_id}
                      className={`session-item ${session.session_id === state.sessionId ? 'active' : ''}`}
                      onClick={() => handleSelectSession(session.session_id)}
                    >
                      <div className="session-item-main">
                        <MessageSquare size={14} className="session-item-icon" />
                        <span className="session-item-title">{session.title || '未命名'}</span>
                      </div>
                      <button
                        className="session-delete-btn"
                        onClick={(e) => handleDeleteSession(e, session.session_id)}
                        title="删除会话"
                      >
                        <Trash2 size={12} />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div className="sidebar-footer">
        <span className={`connection-dot ${state.connected ? 'connected' : 'disconnected'}`} />
        <span style={{ flex: 1 }}>{state.connected ? '已连接' : '未连接'}</span>
        <button className="btn-icon" onClick={() => setSettingsOpen(true)} title="设置">
          <Settings size={16} />
        </button>
      </div>

      <SettingsDialog
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        appearance={appearance}
        onAppearanceChange={onAppearanceChange}
      />
    </div>
  );
}
