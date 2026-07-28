import { useState } from 'react';
import { TimelineEvent } from '../types';
import { ChevronDown, ChevronUp, Search, GitBranch, CheckCircle2, XCircle, AlertCircle, UserPlus, UserCheck } from 'lucide-react';

interface TimelineProps {
  events: TimelineEvent[];
}

const ICONS: Record<string, typeof Search> = {
  'research.started': Search,
  'research.result': CheckCircle2,
  'research.failed': XCircle,
  'research.completed': GitBranch,
  'handoff.started': GitBranch,
  'handoff.completed': CheckCircle2,
  'handoff.failed': XCircle,
  'agent.started': UserPlus,
  'agent.completed': UserCheck,
};

const LABELS: Record<string, string> = {
  'research.started': '开始研究',
  'research.result': '研究返回',
  'research.failed': '研究失败',
  'research.completed': '研究完成',
  'handoff.started': '开始交接',
  'handoff.completed': '交接完成',
  'handoff.failed': '交接失败',
  'agent.started': 'Agent 启动',
  'agent.completed': 'Agent 完成',
};

function formatTime(ts: number): string {
  return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function truncate(text: string, max: number = 200): string {
  if (text.length <= max) return text;
  return text.slice(0, max).trimEnd() + '…';
}

export function Timeline({ events }: TimelineProps) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  if (events.length === 0) return null;

  function toggle(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div className="timeline">
      <div className="timeline-header">
        <span className="timeline-title">活动时间线</span>
        <span className="timeline-count">{events.length}</span>
      </div>
      <div className="timeline-list">
        {events.map((event) => {
          const Icon = ICONS[event.type] || AlertCircle;
          const label = LABELS[event.type] || event.type;
          const color = event.agent_color || 'var(--accent)';
          const isExpanded = expanded.has(event.id);
          const hasDetail = !!(event.text || event.error);
          const isError = event.type.endsWith('.failed');
          const isCompleted = event.type.endsWith('.completed') || event.type.endsWith('.result');

          return (
            <div key={event.id} className={`timeline-item ${isError ? 'error' : isCompleted ? 'success' : ''}`}>
              <div
                className="timeline-item-header"
                onClick={() => hasDetail && toggle(event.id)}
                role={hasDetail ? 'button' : undefined}
              >
                <div className="timeline-dot" style={{ borderColor: color }}>
                  <Icon size={12} style={{ color }} />
                </div>
                <div className="timeline-item-info">
                  <span className="timeline-item-label">{label}</span>
                  <span className="timeline-item-agent" style={{ color }}>
                    {event.agent_name}
                  </span>
                  {event.task && (
                    <span className="timeline-item-task">{truncate(event.task, 60)}</span>
                  )}
                </div>
                <span className="timeline-item-time">{formatTime(event.timestamp)}</span>
                {hasDetail && (
                  <span className="timeline-item-toggle">
                    {isExpanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                  </span>
                )}
              </div>
              {isExpanded && hasDetail && (
                <div className="timeline-item-detail">
                  {event.error && (
                    <div className="timeline-detail-error">{event.error}</div>
                  )}
                  {event.text && (
                    <pre className="timeline-detail-text">{event.text}</pre>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
