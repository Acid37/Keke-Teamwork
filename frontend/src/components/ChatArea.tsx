import { useEffect, useRef, useState } from 'react';
import { useSession } from '../SessionContext';
import { MessageBubble } from './MessageBubble';
import { DirectoryPicker } from './DirectoryPicker';
import { ApprovalDialog } from './ApprovalDialog';
import { Loader2, FolderOpen, Folder, Shield, Zap, User } from 'lucide-react';
import { useToast } from './Toast';

export function ChatArea() {
  const { state, initSession, openProject, sendCommand, dispatch } = useSession();
  const bottomRef = useRef<HTMLDivElement>(null);
  const toast = useToast();
  const [showDirPicker, setShowDirPicker] = useState(false);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [state.messages]);

  function toggleMode(mode: 'auto_review' | 'yolo' | 'solo') {
    const map: any = {
      auto_review: { type: 'auto_review.toggle', key: 'SET_AUTO_REVIEW', next: !state.autoReview },
      yolo: { type: 'yolo.toggle', key: 'SET_YOLO_MODE', next: !state.yoloMode },
      solo: { type: 'solo.toggle', key: 'SET_SOLO_MODE', next: !state.soloMode },
    };
    const m = map[mode];
    dispatch({ type: m.key, enabled: m.next });
    sendCommand({ type: m.type, payload: { enabled: m.next } });
  }

  function respondToApproval(approved: boolean) {
    const request = state.pendingApproval;
    if (!request) return;
    sendCommand({
      type: 'approval.response',
      payload: { request_id: request.request_id, approved },
    });
    dispatch({ type: 'SET_PENDING_APPROVAL', approval: null });
  }

  // Welcome screen
  if (state.messages.length === 0 && !state.isProcessing) {
    const recent = state.recentProjects || [];
    return (
      <div className="chat-area">
        <div className="chat-welcome">
          <h1 className="welcome-title">Keke Teamwork</h1>
          <p className="welcome-subtitle">自研的多 Agent 编码助手 · 打开本地项目开始工作</p>
          <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
            <button className="text-btn primary" style={{ padding: '10px 24px', fontSize: 14, fontWeight: 600 }} onClick={() => setShowDirPicker(true)}>
              <FolderOpen size={18} /> 打开项目
            </button>
          </div>
          {state.workDir && !recent.includes(state.workDir) && (
            <button className="welcome-workdir" onClick={() => setShowDirPicker(true)} title="点击切换">
              <span className="welcome-workdir-label">当前</span>
              <span className="welcome-workdir-path">{state.workDir}</span>
            </button>
          )}
          {recent.length > 0 && (
            <div style={{ width: '100%', maxWidth: 500, marginBottom: 28 }}>
              <div className="recent-projects-title">最近打开</div>
              <div className="recent-projects-list">
                {recent.slice(0, 5).map(dir => (
                  <button key={dir} className="recent-project-item" onClick={() => openProject(dir)} title={dir}>
                    <Folder size={16} style={{ color: 'var(--accent)', flexShrink: 0 }} />
                    <span className="recent-project-path">{dir}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
        {showDirPicker && <DirectoryPicker initialPath={state.workDir || ''} onSelect={(dir) => { setShowDirPicker(false); openProject(dir); toast.success('已打开项目'); }} onCancel={() => setShowDirPicker(false)} />}
        <ApprovalDialog open={!!state.pendingApproval} command={state.pendingApproval?.command || ''} onApprove={() => respondToApproval(true)} onDeny={() => respondToApproval(false)} />
      </div>
    );
  }

  return (
    <div className="chat-area">
      {/* Project header */}
      {state.workDir && (
        <div className="project-header">
          <div className="project-header-left">
            <Folder size={16} className="project-header-icon" />
            <span className="project-header-name">{state.workDir.split('\\').pop() || state.workDir.split('/').pop()}</span>
            <span className="project-header-path" title={state.workDir}>{state.workDir}</span>
          </div>
          <div className="project-header-modes">
            <button className={`mode-pill ${state.autoReview ? 'active' : ''}`} onClick={() => toggleMode('auto_review')} title="自动审查命令"><Shield size={12} /> Auto</button>
            <button className={`mode-pill danger ${state.yoloMode ? 'active' : ''}`} onClick={() => toggleMode('yolo')} title="跳过所有审批（谨慎）"><Zap size={12} /> YOLO</button>
            <button className={`mode-pill ${state.soloMode ? 'active' : ''}`} onClick={() => toggleMode('solo')} title="单模型模式"><User size={12} /> Solo</button>
          </div>
        </div>
      )}

      {state.isProcessing && (
        <div className="chat-status-bar">
          <Loader2 size={14} className="spinner" style={{ color: 'var(--accent)' }} />
          <span className={`phase-badge ${state.phase}`}>{state.phase}</span>
          {state.phase === 'researching' && <span>正在研究代码库...</span>}
          {state.phase === 'thinking' && <span>正在规划方案...</span>}
          {state.phase === 'coding' && <span>正在编写代码...</span>}
        </div>
      )}

      {state.messages.map((message) => {
        const toolCalls = message.tool_calls || [];
        const foldTools = toolCalls.length > 4;
        return <MessageBubble key={message.id} message={message} foldTools={foldTools} />;
      })}

      <div ref={bottomRef} />
      {showDirPicker && <DirectoryPicker initialPath={state.workDir || ''} onSelect={(dir) => { setShowDirPicker(false); openProject(dir); toast.success('已打开项目'); }} onCancel={() => setShowDirPicker(false)} />}
      <ApprovalDialog open={!!state.pendingApproval} command={state.pendingApproval?.command || ''} onApprove={() => respondToApproval(true)} onDeny={() => respondToApproval(false)} />
    </div>
  );
}
