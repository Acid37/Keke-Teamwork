import { useSession } from '../SessionContext';
import {
  CheckCircle2, XCircle, Clock, AlertTriangle, SkipForward,
  RefreshCw, Play, FileCode, ListChecks, ChevronDown, ChevronUp,
  Loader2, Flag,
} from 'lucide-react';
import { useState } from 'react';
import type { WorkflowTask } from '../types';

const STATUS_ICON: Record<string, typeof CheckCircle2> = {
  pending: Clock,
  in_progress: Loader2,
  done: CheckCircle2,
  skipped: SkipForward,
};

const STATUS_COLOR: Record<string, string> = {
  pending: 'var(--text-muted, #888)',
  in_progress: 'var(--accent, #4a9eff)',
  done: '#4caf50',
  skipped: '#ff9800',
};

const VERDICT_STYLE: Record<string, { color: string; label: string; icon: typeof CheckCircle2 }> = {
  approved: { color: '#4caf50', label: '通过', icon: CheckCircle2 },
  needs_changes: { color: '#ff9800', label: '需修改', icon: AlertTriangle },
  rejected: { color: '#f44336', label: '驳回', icon: XCircle },
};

export function WorkflowTimeline() {
  const { state, sendCommand, dispatch } = useSession();
  const [tasksExpanded, setTasksExpanded] = useState(true);
  const [reviewExpanded, setReviewExpanded] = useState(true);

  const { workflowPlan, workflowTaskProgress, workflowTaskResult,
          workflowReview, workflowCompleted, phase } = state;

  // Don't render if no workflow data
  if (!workflowPlan && !workflowTaskProgress && !workflowReview && !workflowCompleted) {
    return null;
  }

  function sendWorkflowCommand(command: string, text?: string) {
    sendCommand({ type: 'workflow.command', payload: { command, text } });
  }

  function startWorkflow(text: string) {
    dispatch({ type: 'RESET_WORKFLOW' });
    sendCommand({ type: 'workflow.start', payload: { text } });
  }

  return (
    <div className="workflow-timeline">
      {/* ── Plan Card ── */}
      {workflowPlan && (
        <div className="wf-card wf-plan-card">
          <div className="wf-card-header" onClick={() => setTasksExpanded(!tasksExpanded)}>
            <ListChecks size={16} style={{ color: 'var(--accent, #4a9eff)' }} />
            <span className="wf-card-title">任务计划</span>
            <span className="wf-badge">{workflowPlan.total_count} 个任务</span>
            {tasksExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </div>

          {tasksExpanded && (
            <div className="wf-card-body">
              {workflowPlan.overview && (
                <p className="wf-overview">{workflowPlan.overview}</p>
              )}

              <div className="wf-task-list">
                {workflowPlan.tasks.map((task: WorkflowTask, i: number) => {
                  const Icon = STATUS_ICON[task.status] || Clock;
                  const color = STATUS_COLOR[task.status] || STATUS_COLOR.pending;
                  const isCurrent = workflowTaskProgress?.task_id === task.id;
                  return (
                    <div key={task.id} className={`wf-task-item ${isCurrent ? 'current' : ''}`}>
                      <div className="wf-task-icon" style={{ color }}>
                        <Icon size={14} className={task.status === 'in_progress' ? 'spinner' : ''} />
                      </div>
                      <div className="wf-task-content">
                        <span className="wf-task-title">{i + 1}. {task.title}</span>
                        {task.description && (
                          <span className="wf-task-desc">{task.description}</span>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>

              {workflowPlan.risks.length > 0 && (
                <div className="wf-risks">
                  <AlertTriangle size={12} style={{ color: '#ff9800' }} />
                  <span>{workflowPlan.risks.join('；')}</span>
                </div>
              )}

              {/* Action buttons for plan_review phase */}
              {phase === 'plan_review' && (
                <div className="wf-actions">
                  <button className="wf-btn primary" onClick={() => sendWorkflowCommand('approve_plan')}>
                    <CheckCircle2 size={14} /> 确认计划
                  </button>
                  <button className="wf-btn danger" onClick={() => sendWorkflowCommand('reject_plan')}>
                    <XCircle size={14} /> 拒绝
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── Task Progress Card ── */}
      {workflowTaskProgress && phase !== 'completed' && (
        <div className="wf-card wf-progress-card">
          <div className="wf-card-header">
            <FileCode size={16} style={{ color: '#4caf50' }} />
            <span className="wf-card-title">
              任务 {workflowTaskProgress.task_index}/{workflowTaskProgress.total_count}
            </span>
            {workflowTaskProgress.retry_count > 0 && (
              <span className="wf-badge warn">重试第 {workflowTaskProgress.retry_count} 次</span>
            )}
            <Loader2 size={14} className="spinner" style={{ color: 'var(--accent, #4a9eff)', marginLeft: 'auto' }} />
          </div>
          <div className="wf-card-body">
            <span className="wf-task-title">{workflowTaskProgress.title}</span>
            {workflowTaskProgress.description && (
              <span className="wf-task-desc">{workflowTaskProgress.description}</span>
            )}
          </div>
        </div>
      )}

      {/* ── Review Result Card ── */}
      {workflowReview && (
        <div className="wf-card wf-review-card">
          <div className="wf-card-header" onClick={() => setReviewExpanded(!reviewExpanded)}>
            {(() => {
              const style = VERDICT_STYLE[workflowReview.verdict] || VERDICT_STYLE.approved;
              const Icon = style.icon;
              return <Icon size={16} style={{ color: style.color }} />;
            })()}
            <span className="wf-card-title">审查结果</span>
            {(() => {
              const style = VERDICT_STYLE[workflowReview.verdict] || VERDICT_STYLE.approved;
              return <span className="wf-badge" style={{ background: style.color + '20', color: style.color }}>{style.label}</span>;
            })()}
            {reviewExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </div>
          {reviewExpanded && (
            <div className="wf-card-body">
              <p className="wf-review-summary">{workflowReview.summary}</p>

              {/* Action buttons for feedback phase */}
              {phase === 'feedback' && workflowReview.should_retry && (
                <div className="wf-actions">
                  <button className="wf-btn primary" onClick={() => sendWorkflowCommand('retry')}>
                    <RefreshCw size={14} /> 根据反馈修改
                  </button>
                  <button className="wf-btn warn" onClick={() => sendWorkflowCommand('skip_task')}>
                    <SkipForward size={14} /> 跳过此任务
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── Code Review Pending Actions ── */}
      {phase === 'code_review' && !state.autoReview && (
        <div className="wf-card wf-action-card">
          <div className="wf-card-body">
            <span className="wf-action-prompt">代码已就绪，等待审查</span>
            <div className="wf-actions">
              <button className="wf-btn primary" onClick={() => sendWorkflowCommand('start_review')}>
                <Play size={14} /> 开始审查
              </button>
              <button className="wf-btn warn" onClick={() => sendWorkflowCommand('skip_review')}>
                <SkipForward size={14} /> 跳过审查
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Undo button (available in code_review / feedback) ── */}
      {(phase === 'code_review' || phase === 'feedback') && (
        <button className="wf-btn ghost wf-undo-btn" onClick={() => sendWorkflowCommand('undo')}>
          <RefreshCw size={12} /> 撤销上一个任务
        </button>
      )}

      {/* ── Completion Card ── */}
      {workflowCompleted && (
        <div className="wf-card wf-completed-card">
          <div className="wf-card-header">
            <Flag size={16} style={{ color: '#4caf50' }} />
            <span className="wf-card-title">工作流完成</span>
            <CheckCircle2 size={16} style={{ color: '#4caf50', marginLeft: 'auto' }} />
          </div>
          <div className="wf-card-body">
            <div className="wf-stats">
              <div className="wf-stat">
                <span className="wf-stat-value">{workflowCompleted.completed_count}</span>
                <span className="wf-stat-label">已完成</span>
              </div>
              <div className="wf-stat">
                <span className="wf-stat-value">{workflowCompleted.skipped_count}</span>
                <span className="wf-stat-label">已跳过</span>
              </div>
              <div className="wf-stat">
                <span className="wf-stat-value">{workflowCompleted.files_changed}</span>
                <span className="wf-stat-label">文件变更</span>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
