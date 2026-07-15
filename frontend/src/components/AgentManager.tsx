import { useState, useEffect, useCallback } from 'react';
import { Plus, Trash2, Edit3, Save, X, ChevronDown, ChevronUp, Loader2, Shield } from 'lucide-react';
import type { AgentDefinition, AgentPermissions, ToolInfo } from '../types';

const COLOR_PRESETS = [
  '#4a9eff', '#7c3aed', '#10b981', '#f59e0b', '#ef4444',
  '#ec4899', '#06b6d4', '#8b5cf6', '#f97316', '#14b8a6',
];

const ROLE_PRESETS = [
  { role: 'assistant', label: '助手' },
  { role: 'coder', label: '编码' },
  { role: 'researcher', label: '研究' },
  { role: 'reviewer', label: '审查' },
  { role: 'architect', label: '架构' },
  { role: 'custom', label: '自定义' },
];

interface AgentManagerProps {
  models: string[];
  onFetchModels: () => void;
  loadingModels: boolean;
}

export function AgentManager({ models, onFetchModels, loadingModels }: AgentManagerProps) {
  const [agents, setAgents] = useState<AgentDefinition[]>([]);
  const [tools, setTools] = useState<ToolInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<AgentDefinition | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  // Form state
  const [formId, setFormId] = useState('');
  const [formName, setFormName] = useState('');
  const [formRole, setFormRole] = useState('assistant');
  const [formDescription, setFormDescription] = useState('');
  const [formModel, setFormModel] = useState('');
  const [formTemperature, setFormTemperature] = useState(0.7);
  const [formSystemPrompt, setFormSystemPrompt] = useState('');
  const [formTools, setFormTools] = useState<string[]>([]);
  const [formMaxRounds, setFormMaxRounds] = useState(50);
  const [formMaxContext, setFormMaxContext] = useState<number | ''>('');
  const [formColor, setFormColor] = useState(COLOR_PRESETS[0]);

  // Permission form state
  const [formAllowedPaths, setFormAllowedPaths] = useState('');
  const [formDeniedPaths, setFormDeniedPaths] = useState('');
  const [formMaxCommandRisk, setFormMaxCommandRisk] = useState<string>('dangerous');
  const [formAllowDelegation, setFormAllowDelegation] = useState(true);
  const [formAllowHandoff, setFormAllowHandoff] = useState(true);
  const [showPerms, setShowPerms] = useState(false);

  const fetchAgents = useCallback(async () => {
    try {
      const res = await fetch('/api/agents');
      const data = await res.json();
      setAgents(data.agents || []);
    } catch {
      setError('加载 Agent 列表失败');
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchTools = useCallback(async () => {
    try {
      const res = await fetch('/api/tools');
      const data = await res.json();
      setTools(data.tools || []);
    } catch {
      // silent
    }
  }, []);

  useEffect(() => {
    fetchAgents();
    fetchTools();
  }, [fetchAgents, fetchTools]);

  function resetForm() {
    setFormId('');
    setFormName('');
    setFormRole('assistant');
    setFormDescription('');
    setFormModel('');
    setFormTemperature(0.7);
    setFormSystemPrompt('');
    setFormTools(tools.map((t) => t.name));
    setFormMaxRounds(50);
    setFormMaxContext('');
    setFormColor(COLOR_PRESETS[0]);
    setFormAllowedPaths('');
    setFormDeniedPaths('');
    setFormMaxCommandRisk('dangerous');
    setFormAllowDelegation(true);
    setFormAllowHandoff(true);
    setShowPerms(false);
  }

  function startCreate() {
    resetForm();
    setFormTools(tools.map((t) => t.name));
    setIsCreating(true);
    setEditing(null);
    setError('');
  }

  function startEdit(agent: AgentDefinition) {
    setFormId(agent.agent_id);
    setFormName(agent.name);
    setFormRole(agent.role);
    setFormDescription(agent.description);
    setFormModel(agent.model || '');
    setFormTemperature(agent.temperature);
    setFormSystemPrompt(agent.system_prompt);
    setFormTools([...agent.tools]);
    setFormMaxRounds(agent.max_tool_rounds);
    setFormMaxContext(agent.max_context ?? '');
    setFormColor(agent.color);
    const perms = agent.permissions;
    setFormAllowedPaths(perms?.allowed_paths?.join('\n') || '');
    setFormDeniedPaths(perms?.denied_paths?.join('\n') || '');
    setFormMaxCommandRisk(perms?.max_command_risk || 'dangerous');
    setFormAllowDelegation(perms?.allow_delegation ?? true);
    setFormAllowHandoff(perms?.allow_handoff ?? true);
    setShowPerms(perms != null);
    setEditing(agent);
    setIsCreating(false);
    setError('');
  }

  function cancelEdit() {
    setEditing(null);
    setIsCreating(false);
    setError('');
  }

  function toggleTool(toolName: string) {
    setFormTools((prev) =>
      prev.includes(toolName) ? prev.filter((t) => t !== toolName) : [...prev, toolName]
    );
  }

  async function handleSave() {
    setError('');
    if (!formId.trim() && isCreating) {
      setError('请输入 Agent ID');
      return;
    }
    if (!formName.trim()) {
      setError('请输入名称');
      return;
    }

    setSaving(true);
    try {
      const body: Record<string, unknown> = {
        agent_id: formId.trim(),
        name: formName.trim(),
        role: formRole,
        description: formDescription,
        model: formModel || null,
        temperature: formTemperature,
        system_prompt: formSystemPrompt,
        tools: formTools,
        max_tool_rounds: formMaxRounds,
        max_context: formMaxContext === '' ? null : formMaxContext,
        color: formColor,
      };

      // Include permissions if enabled
      if (showPerms) {
        const allowed = formAllowedPaths.trim() ? formAllowedPaths.trim().split('\n').map(s => s.trim()).filter(Boolean) : null;
        const denied = formDeniedPaths.trim() ? formDeniedPaths.trim().split('\n').map(s => s.trim()).filter(Boolean) : null;
        body.permissions = {
          allowed_paths: allowed,
          denied_paths: denied,
          max_command_risk: formMaxCommandRisk,
          allow_delegation: formAllowDelegation,
          allow_handoff: formAllowHandoff,
        };
      } else {
        body.permissions = null;
      }

      const url = isCreating ? '/api/agents' : `/api/agents/${formId}`;
      const method = isCreating ? 'POST' : 'PUT';
      const res = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json();

      if (data.error) {
        setError(data.error);
      } else {
        await fetchAgents();
        cancelEdit();
      }
    } catch {
      setError('网络错误');
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(agentId: string) {
    if (!confirm(`确定要删除这个 Agent 吗？`)) return;
    try {
      const res = await fetch(`/api/agents/${agentId}`, { method: 'DELETE' });
      const data = await res.json();
      if (data.error) {
        setError(data.error);
      } else {
        await fetchAgents();
      }
    } catch {
      setError('删除失败');
    }
  }

  if (loading) {
    return (
      <div className="agent-manager-loading">
        <Loader2 size={20} className="spinner" />
        <span>加载中...</span>
      </div>
    );
  }

  const isFormOpen = isCreating || editing !== null;

  return (
    <div className="agent-manager">
      {error && <div className="settings-error">{error}</div>}

      {/* Agent list */}
      <div className="agent-list">
        {agents.map((agent) => (
          <div
            key={agent.agent_id}
            className={`agent-card ${editing?.agent_id === agent.agent_id ? 'active' : ''}`}
          >
            <div className="agent-card-header">
              <div className="agent-card-color" style={{ background: agent.color }} />
              <div className="agent-card-info">
                <div className="agent-card-name">{agent.name}</div>
                <div className="agent-card-meta">
                  <span className="agent-card-role">{agent.role}</span>
                  {agent.model && <span className="agent-card-model">{agent.model}</span>}
                  <span className="agent-card-tools">{agent.tools.length} 个工具</span>
                </div>
              </div>
              <div className="agent-card-actions">
                <button
                  className="btn-icon"
                  onClick={() => startEdit(agent)}
                  title="编辑"
                >
                  <Edit3 size={14} />
                </button>
                {agent.agent_id !== 'main' && (
                  <button
                    className="btn-icon"
                    onClick={() => handleDelete(agent.agent_id)}
                    title="删除"
                  >
                    <Trash2 size={14} />
                  </button>
                )}
              </div>
            </div>
            {agent.description && (
              <div className="agent-card-desc">{agent.description}</div>
            )}
          </div>
        ))}
      </div>

      {!isFormOpen && (
        <button className="agent-add-btn" onClick={startCreate}>
          <Plus size={16} />
          新建 Agent
        </button>
      )}

      {/* Edit / Create form */}
      {isFormOpen && (
        <div className="agent-form">
          <div className="agent-form-header">
            <h4>{isCreating ? '新建 Agent' : '编辑 Agent'}</h4>
            <button className="btn-icon" onClick={cancelEdit}>
              <X size={16} />
            </button>
          </div>

          <div className="agent-form-body">
            {/* ID (only for create) */}
            {isCreating && (
              <div className="settings-field">
                <label>Agent ID</label>
                <input
                  type="text"
                  value={formId}
                  onChange={(e) => setFormId(e.target.value.replace(/[^a-zA-Z0-9_-]/g, ''))}
                  placeholder="唯一标识，如 coder-alpha"
                />
              </div>
            )}

            {/* Name */}
            <div className="settings-field">
              <label>名称</label>
              <input
                type="text"
                value={formName}
                onChange={(e) => setFormName(e.target.value)}
                placeholder="显示名称"
              />
            </div>

            {/* Tag */}
            <div className="settings-field">
              <label>标签</label>
              <div className="role-presets">
                {ROLE_PRESETS.map((r) => (
                  <button
                    key={r.role}
                    className={`preset-btn ${formRole === r.role ? 'active' : ''}`}
                    onClick={() => setFormRole(r.role)}
                  >
                    {r.label}
                  </button>
                ))}
              </div>
              {formRole === 'custom' && (
                <input
                  type="text"
                  value={formRole}
                  onChange={(e) => setFormRole(e.target.value)}
                  placeholder="自定义标签"
                  style={{ marginTop: '6px' }}
                />
              )}
            </div>

            {/* Description */}
            <div className="settings-field">
              <label>描述</label>
              <input
                type="text"
                value={formDescription}
                onChange={(e) => setFormDescription(e.target.value)}
                placeholder="角色描述（可选）"
              />
            </div>

            {/* Model */}
            <div className="settings-field">
              <label>模型 <span className="optional">（留空使用全局模型）</span></label>
              {models.length > 0 ? (
                <select
                  value={formModel}
                  onChange={(e) => setFormModel(e.target.value)}
                >
                  <option value="">同全局模型</option>
                  {models.map((m) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </select>
              ) : (
                <input
                  type="text"
                  value={formModel}
                  onChange={(e) => setFormModel(e.target.value)}
                  placeholder="模型名称（留空使用全局模型）"
                />
              )}
            </div>

            {/* Temperature */}
            <div className="settings-field">
              <label>温度 <span className="optional">({formTemperature})</span></label>
              <input
                type="range"
                min="0"
                max="2"
                step="0.1"
                value={formTemperature}
                onChange={(e) => setFormTemperature(parseFloat(e.target.value))}
                className="temperature-slider"
              />
              <div className="temp-labels">
                <span>精确 0</span>
                <span>创意 2</span>
              </div>
            </div>

            {/* Max tool rounds */}
            <div className="settings-field">
              <label>最大工具轮次</label>
              <input
                type="number"
                min="1"
                max="200"
                value={formMaxRounds}
                onChange={(e) => setFormMaxRounds(parseInt(e.target.value) || 50)}
              />
            </div>

            {/* Max context */}
            <div className="settings-field">
              <label>上下文窗口 <span className="optional">（留空使用模型默认）</span></label>
              <input
                type="number"
                min="0"
                placeholder="如 128000"
                value={formMaxContext}
                onChange={(e) => setFormMaxContext(e.target.value === '' ? '' : parseInt(e.target.value) || '')}
              />
            </div>

            {/* Color */}
            <div className="settings-field">
              <label>颜色</label>
              <div className="color-presets">
                {COLOR_PRESETS.map((c) => (
                  <button
                    key={c}
                    className={`color-dot ${formColor === c ? 'active' : ''}`}
                    style={{ background: c }}
                    onClick={() => setFormColor(c)}
                  />
                ))}
                <input
                  type="color"
                  value={formColor}
                  onChange={(e) => setFormColor(e.target.value)}
                  className="color-picker-input"
                  title="自定义颜色"
                />
              </div>
            </div>

            {/* Tools */}
            <div className="settings-field">
              <label>工具</label>
              <div className="tool-checkboxes">
                {tools.map((tool) => (
                  <label key={tool.name} className="tool-checkbox">
                    <input
                      type="checkbox"
                      checked={formTools.includes(tool.name)}
                      onChange={() => toggleTool(tool.name)}
                    />
                    <span>{tool.name}</span>
                  </label>
                ))}
              </div>
            </div>

            {/* System prompt */}
            <div className="settings-field">
              <label>系统提示词 <span className="optional">（留空使用默认）</span></label>
              <textarea
                className="system-prompt-input"
                value={formSystemPrompt}
                onChange={(e) => setFormSystemPrompt(e.target.value)}
                placeholder="自定义系统提示词（留空使用默认提示词）"
                rows={6}
              />
            </div>

            {/* Permissions */}
            <div className="settings-field">
              <label className="perm-toggle-label">
                <input
                  type="checkbox"
                  checked={showPerms}
                  onChange={(e) => setShowPerms(e.target.checked)}
                />
                <Shield size={14} />
                <span>自定义权限策略</span>
                <span className="optional">（关闭使用默认）</span>
              </label>
            </div>

            {showPerms && (
              <div className="perm-section">
                <div className="settings-field">
                  <label>命令风险预算</label>
                  <select
                    value={formMaxCommandRisk}
                    onChange={(e) => setFormMaxCommandRisk(e.target.value)}
                  >
                    <option value="read_only">仅只读命令</option>
                    <option value="normal">普通命令（默认审批）</option>
                    <option value="dangerous">无限制（含高危命令）</option>
                  </select>
                </div>

                <div className="settings-field">
                  <label>允许路径 <span className="optional">（每行一个 glob，留空 = 全部允许）</span></label>
                  <textarea
                    className="perm-paths-input"
                    value={formAllowedPaths}
                    onChange={(e) => setFormAllowedPaths(e.target.value)}
                    placeholder={"src/**\ntests/**"}
                    rows={3}
                  />
                </div>

                <div className="settings-field">
                  <label>拒绝路径 <span className="optional">（优先级高于允许路径）</span></label>
                  <textarea
                    className="perm-paths-input"
                    value={formDeniedPaths}
                    onChange={(e) => setFormDeniedPaths(e.target.value)}
                    placeholder={"**/*.secret.*\nconfig/**"}
                    rows={3}
                  />
                </div>

                <div className="perm-checks">
                  <label className="perm-check">
                    <input
                      type="checkbox"
                      checked={formAllowDelegation}
                      onChange={(e) => setFormAllowDelegation(e.target.checked)}
                    />
                    <span>允许委派给其他 Agent</span>
                  </label>
                  <label className="perm-check">
                    <input
                      type="checkbox"
                      checked={formAllowHandoff}
                      onChange={(e) => setFormAllowHandoff(e.target.checked)}
                    />
                    <span>允许被其他 Agent Handoff</span>
                  </label>
                </div>
              </div>
            )}
          </div>

          <div className="agent-form-footer">
            <button className="btn-secondary" onClick={cancelEdit}>取消</button>
            <button className="btn-primary" onClick={handleSave} disabled={saving}>
              {saving ? <Loader2 size={14} className="spinner" /> : <Save size={14} />}
              {saving ? '保存中...' : '保存'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
