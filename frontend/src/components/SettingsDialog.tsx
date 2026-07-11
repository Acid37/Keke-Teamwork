import { useState, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { X, Save, Loader2, RefreshCw } from 'lucide-react';
import { AgentManager } from './AgentManager';
import { AppearanceSettings } from './AppearanceSettings';
import type { AppearanceConfig } from '../types';

interface ConfigData {
  provider: string;
  api_key: string;
  api_key_masked: string;
  base_url: string;
  main_model: string;
  coder_model: string | null;
  research_model: string | null;
  title_model: string | null;
  host: string;
  port: number;
}

interface SettingsDialogProps {
  open: boolean;
  onClose: () => void;
  appearance: AppearanceConfig;
  onAppearanceChange: (config: AppearanceConfig) => void;
}

type TabId = 'model' | 'agents' | 'appearance';

const TABS: { id: TabId; label: string }[] = [
  { id: 'model', label: '模型设置' },
  { id: 'agents', label: 'Agent 管理' },
  { id: 'appearance', label: '外观' },
];

const PROVIDERS = [
  { value: 'openai', label: 'OpenAI 兼容' },
  { value: 'anthropic', label: 'Anthropic (Claude)' },
  { value: 'gemini', label: 'Google Gemini' },
];

const PRESETS = [
  { name: 'DeepSeek', url: 'https://api.deepseek.com' },
  { name: '通义千问', url: 'https://dashscope.aliyuncs.com/compatible-mode/v1' },
  { name: 'GLM', url: 'https://open.bigmodel.cn/api/paas/v4' },
  { name: 'Kimi', url: 'https://api.moonshot.cn/v1' },
  { name: 'Step', url: 'https://api.stepfun.com/v1' },
  { name: 'MiniMax', url: 'https://api.minimax.chat/v1' },
  { name: 'OpenAI', url: 'https://api.openai.com/v1' },
];

export function SettingsDialog({ open, onClose, appearance, onAppearanceChange }: SettingsDialogProps) {
  const [activeTab, setActiveTab] = useState<TabId>('model');
  const [config, setConfig] = useState<ConfigData | null>(null);
  const [apiKeyInput, setApiKeyInput] = useState('');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');
  const [models, setModels] = useState<string[]>([]);
  const [loadingModels, setLoadingModels] = useState(false);

  const fetchModels = useCallback(async () => {
    setLoadingModels(true);
    try {
      const res = await fetch('/api/models');
      const data = await res.json();
      setModels(data.models || []);
    } catch {
      setModels([]);
    } finally {
      setLoadingModels(false);
    }
  }, []);

  useEffect(() => {
    if (open) {
      fetchConfig();
      fetchModels();
      setSaved(false);
      setError('');
    }
  }, [open, fetchModels]);

  async function fetchConfig() {
    try {
      const res = await fetch('/api/config');
      const data = await res.json();
      setConfig(data);
      setApiKeyInput('');
    } catch {
      setError('加载配置失败');
    }
  }

  async function handleSave() {
    if (!config) return;
    setSaving(true);
    setError('');

    const body: Record<string, any> = {
      provider: config.provider,
      base_url: config.base_url,
      main_model: config.main_model,
      coder_model: config.coder_model || null,
      research_model: config.research_model || null,
      title_model: config.title_model || null,
    };

    if (apiKeyInput && !apiKeyInput.includes('****')) {
      body.api_key = apiKeyInput;
    }

    try {
      const res = await fetch('/api/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (data.status === 'ok') {
        setConfig(data.config);
        setApiKeyInput('');
        setSaved(true);
        fetchModels();
        setTimeout(() => setSaved(false), 2000);
      } else {
        setError('保存失败');
      }
    } catch {
      setError('网络错误');
    } finally {
      setSaving(false);
    }
  }

  function handlePreset(url: string) {
    if (config) {
      setConfig({ ...config, base_url: url, main_model: '' });
    }
  }

  if (!open || !config) return null;

  const modelOptions = models.length > 0 ? models : [];

  return createPortal(
    <div className="settings-overlay" onClick={onClose}>
      <div className="settings-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="settings-header">
          <h2>设置</h2>
          <button className="settings-close" onClick={onClose}>
            <X size={18} />
          </button>
        </div>

        {/* Tab bar */}
        <div className="settings-tabs">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              className={`settings-tab ${activeTab === tab.id ? 'active' : ''}`}
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <div className="settings-body">
          {error && <div className="settings-error">{error}</div>}
          {saved && <div className="settings-success">保存成功</div>}

          {/* ─── Model Settings Tab ─── */}
          {activeTab === 'model' && (
            <>
              {/* 服务商 */}
              <div className="settings-field">
                <label>服务商</label>
                <select
                  value={config.provider}
                  onChange={(e) => setConfig({ ...config, provider: e.target.value })}
                >
                  {PROVIDERS.map((p) => (
                    <option key={p.value} value={p.value}>{p.label}</option>
                  ))}
                </select>
              </div>

              {/* 快速预设 */}
              <div className="settings-field">
                <label>快速选择</label>
                <div className="settings-presets">
                  {PRESETS.map((p) => (
                    <button
                      key={p.name}
                      className="preset-btn"
                      onClick={() => handlePreset(p.url)}
                    >
                      {p.name}
                    </button>
                  ))}
                </div>
              </div>

              {/* API Key */}
              <div className="settings-field">
                <label>API Key</label>
                <input
                  type="password"
                  placeholder={config.api_key_masked || '输入 API Key'}
                  value={apiKeyInput}
                  onChange={(e) => setApiKeyInput(e.target.value)}
                />
                <span className="settings-hint">
                  {config.api_key_masked ? '留空则保留当前 Key' : '必填'}
                </span>
              </div>

              {/* Base URL */}
              <div className="settings-field">
                <label>API 地址</label>
                <input
                  type="text"
                  value={config.base_url}
                  onChange={(e) => setConfig({ ...config, base_url: e.target.value })}
                  placeholder="https://api.deepseek.com/v1"
                />
              </div>

              {/* 主模型 */}
              <div className="settings-field">
                <div className="model-list-header">
                  <label>主模型</label>
                  <button
                    className="model-refresh-btn"
                    onClick={fetchModels}
                    disabled={loadingModels}
                    title="刷新模型列表"
                  >
                    {loadingModels ? <Loader2 size={12} className="spinner" /> : <RefreshCw size={12} />}
                    {loadingModels ? '加载中' : '刷新'}
                  </button>
                </div>
                {modelOptions.length > 0 ? (
                  <select
                    value={config.main_model}
                    onChange={(e) => setConfig({ ...config, main_model: e.target.value })}
                  >
                    {!modelOptions.includes(config.main_model) && (
                      <option value={config.main_model}>{config.main_model}</option>
                    )}
                    {modelOptions.map((m) => (
                      <option key={m} value={m}>{m}</option>
                    ))}
                  </select>
                ) : (
                  <input
                    type="text"
                    value={config.main_model}
                    onChange={(e) => setConfig({ ...config, main_model: e.target.value })}
                    placeholder="输入模型名称"
                  />
                )}
              </div>

              {/* Coder 模型 */}
              <div className="settings-field">
                <label>编码模型 <span className="optional">（可选，默认同主模型）</span></label>
                {modelOptions.length > 0 ? (
                  <select
                    value={config.coder_model || ''}
                    onChange={(e) => setConfig({ ...config, coder_model: e.target.value || null })}
                  >
                    <option value="">同主模型</option>
                    {modelOptions.map((m) => (
                      <option key={m} value={m}>{m}</option>
                    ))}
                  </select>
                ) : (
                  <input
                    type="text"
                    value={config.coder_model || ''}
                    onChange={(e) => setConfig({ ...config, coder_model: e.target.value || null })}
                    placeholder="同主模型"
                  />
                )}
              </div>

              {/* 研究模型 */}
              <div className="settings-field">
                <label>研究模型 <span className="optional">（可选，默认同主模型）</span></label>
                {modelOptions.length > 0 ? (
                  <select
                    value={config.research_model || ''}
                    onChange={(e) => setConfig({ ...config, research_model: e.target.value || null })}
                  >
                    <option value="">同主模型</option>
                    {modelOptions.map((m) => (
                      <option key={m} value={m}>{m}</option>
                    ))}
                  </select>
                ) : (
                  <input
                    type="text"
                    value={config.research_model || ''}
                    onChange={(e) => setConfig({ ...config, research_model: e.target.value || null })}
                    placeholder="同主模型"
                  />
                )}
              </div>

              {/* 标题模型 */}
              <div className="settings-field">
                <label>标题模型 <span className="optional">（可选，建议选轻量模型）</span></label>
                {modelOptions.length > 0 ? (
                  <select
                    value={config.title_model || ''}
                    onChange={(e) => setConfig({ ...config, title_model: e.target.value || null })}
                  >
                    <option value="">同主模型</option>
                    {modelOptions.map((m) => (
                      <option key={m} value={m}>{m}</option>
                    ))}
                  </select>
                ) : (
                  <input
                    type="text"
                    value={config.title_model || ''}
                    onChange={(e) => setConfig({ ...config, title_model: e.target.value || null })}
                    placeholder="同主模型"
                  />
                )}
              </div>
            </>
          )}

          {/* ─── Agent Management Tab ─── */}
          {activeTab === 'agents' && (
            <AgentManager
              models={models}
              onFetchModels={fetchModels}
              loadingModels={loadingModels}
            />
          )}

          {/* ─── Appearance Tab ─── */}
          {activeTab === 'appearance' && (
            <AppearanceSettings
              config={appearance}
              onChange={onAppearanceChange}
            />
          )}
        </div>

        {/* Footer — only show save button for model tab */}
        {activeTab === 'model' && (
          <div className="settings-footer">
            <button className="btn-secondary" onClick={onClose}>取消</button>
            <button className="btn-primary" onClick={handleSave} disabled={saving}>
              {saving ? <Loader2 size={14} className="spinner" /> : <Save size={14} />}
              {saving ? '保存中...' : '保存'}
            </button>
          </div>
        )}
      </div>
    </div>,
    document.body
  );
}
