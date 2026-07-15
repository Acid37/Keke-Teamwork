import { useState } from 'react';
import { createPortal } from 'react-dom';
import { Check, ChevronRight, ChevronLeft, Zap, Bot, Loader2, Key } from 'lucide-react';
import { QUICK_PRESETS } from '../constants';
import { useAsyncAction } from '../utils/useAsyncAction';
import { apiPost, apiPut } from '../utils/api';

interface SetupWizardProps {
  open: boolean;
  onComplete: () => void;
}

const STEP_TITLES = ['选择服务商', '配置 API Key', '确认默认角色'];

export function SetupWizard({ open, onComplete }: SetupWizardProps) {
  const [step, setStep] = useState(0);
  const [providerName, setProviderName] = useState('deepseek');
  const [baseUrl, setBaseUrl] = useState('https://api.deepseek.com');
  const [apiKey, setApiKey] = useState('');
  const [modelId, setModelId] = useState('deepseek-v4-flash');
  const [customModelId, setCustomModelId] = useState('');
  const [fetchingModels, setFetchingModels] = useState(false);
  const [availableModels, setAvailableModels] = useState<string[]>([]);
  const { busy, run } = useAsyncAction((msg) => setError(msg));
  const [error, setError] = useState('');
  const [showCustomModel, setShowCustomModel] = useState(false);

  // Step 0: Select provider
  function selectPreset(preset: typeof QUICK_PRESETS[0]) {
    setProviderName(preset.name.toLowerCase());
    setBaseUrl(preset.url);
    const models = preset.models ?? [];
    setAvailableModels(models);
    setModelId(models[0] ?? '');
    setShowCustomModel(false);
  }

  // Step 1: Fetch available models
  async function fetchModels() {
    if (!baseUrl || !apiKey) return;
    setFetchingModels(true);
    try {
      const base = baseUrl.replace(/\/+$/, '');
      const res = await fetch(`${base}/models`, {
        headers: { Authorization: `Bearer ${apiKey}` },
      });
      if (res.ok) {
        const data = await res.json();
        const ids: string[] = (data.data || []).map((m: { id: string }) => m.id).sort();
        setAvailableModels(ids.length > 0 ? ids : QUICK_PRESETS.find(p => p.url === baseUrl)?.models || []);
      }
    } catch {
      // Keep preset models on failure
    } finally {
      setFetchingModels(false);
    }
  }

  // Step 2: Submit setup
  async function handleComplete() {
    setError('');
    await run(async () => {
      await apiPost('/api/config/providers', {
        name: providerName,
        client_type: 'openai',
        base_url: baseUrl,
        api_key: apiKey,
        enabled: true,
      });

      const modelName = showCustomModel && customModelId ? customModelId : modelId;
      await apiPost('/api/config/models', {
        name: 'main',
        model_id: modelName,
        provider_name: providerName,
      });

      await apiPut('/api/config', { main_model: 'main' });
      await apiPost('/api/setup/complete');
      onComplete();
    });
  }

  function canNext(): boolean {
    if (step === 0) return true;
    if (step === 1) return apiKey.trim().length > 0;
    return true;
  }

  if (!open) return null;

  return createPortal(
    <div className="setup-overlay">
      <div className="setup-dialog">
        {/* Header */}
        <div className="setup-header">
          <div className="setup-logo">
            <Zap size={28} />
            <h1>Keke Teamwork</h1>
          </div>
          <p className="setup-subtitle">初次使用，请完成以下配置</p>
        </div>

        {/* Step indicator */}
        <div className="setup-steps">
          {STEP_TITLES.map((title, i) => (
            <div key={i} className={`setup-step ${i === step ? 'active' : i < step ? 'done' : ''}`}>
              <div className="setup-step-number">
                {i < step ? <Check size={14} /> : i + 1}
              </div>
              <span>{title}</span>
            </div>
          ))}
        </div>

        {/* Error */}
        {error && <div className="settings-error">{error}</div>}

        {/* Step 0: Provider selection */}
        {step === 0 && (
          <div className="setup-body">
            <h3>选择 AI 服务商</h3>
            <p className="setup-hint">选择你使用的 AI 服务商，我们将自动填充 API 地址。</p>
            <div className="provider-preset-grid">
              {QUICK_PRESETS.map((p) => (
                <button
                  key={p.name}
                  className={`provider-preset-card ${providerName === p.name.toLowerCase() ? 'active' : ''}`}
                  onClick={() => selectPreset(p)}
                >
                  <div className="provider-preset-name">{p.name}</div>
                  <div className="provider-preset-url">{p.url}</div>
                </button>
              ))}
            </div>
            <div className="settings-field" style={{ marginTop: 16 }}>
              <label>或自定义 API 地址</label>
              <input
                type="text"
                value={baseUrl}
                onChange={(e) => { setBaseUrl(e.target.value); setProviderName('custom'); }}
                placeholder="https://api.example.com/v1"
              />
            </div>
          </div>
        )}

        {/* Step 1: API Key + Model */}
        {step === 1 && (
          <div className="setup-body">
            <h3>配置 API Key</h3>
            <p className="setup-hint">输入你的 API Key，我们将安全地存储在本地。</p>
            <div className="settings-field">
              <label>API Key</label>
              <div className="api-key-input-wrap">
                <Key size={16} className="api-key-icon" />
                <input
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder="sk-..."
                  autoFocus
                />
              </div>
            </div>

            {apiKey.length > 0 && (
              <>
                <div className="settings-field" style={{ marginTop: 16 }}>
                  <label>默认模型</label>
                  <div className="model-select-row">
                    <select
                      value={showCustomModel ? '__custom__' : modelId}
                      onChange={(e) => {
                        if (e.target.value === '__custom__') {
                          setShowCustomModel(true);
                        } else {
                          setShowCustomModel(false);
                          setModelId(e.target.value);
                        }
                      }}
                    >
                      {availableModels.map((m) => (
                        <option key={m} value={m}>{m}</option>
                      ))}
                      <option value="__custom__">自定义模型...</option>
                    </select>
                    <button
                      className="btn-icon"
                      onClick={fetchModels}
                      disabled={fetchingModels}
                      title="刷新模型列表"
                    >
                      {fetchingModels ? <Loader2 size={14} className="spinner" /> : '🔄'}
                    </button>
                  </div>
                </div>
                {showCustomModel && (
                  <div className="settings-field">
                    <input
                      type="text"
                      value={customModelId}
                      onChange={(e) => setCustomModelId(e.target.value)}
                      placeholder="输入模型 ID，如 gpt-4o"
                      autoFocus
                    />
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {/* Step 2: Role overview */}
        {step === 2 && (
          <div className="setup-body">
            <h3>默认角色一览</h3>
            <p className="setup-hint">
              Keke Teamwork 预置了四个角色，各自拥有不同的工具权限和职责范围。
              你可以随时在设置中自定义或新增角色。
            </p>
            <div className="role-overview-grid">
              <div className="role-overview-card">
                <div className="role-overview-icon" style={{ background: '#4a9eff' }}><Bot size={18} /></div>
                <div>
                  <strong>通用助手 (main)</strong>
                  <p>全功能，可读写、执行命令、委派任务</p>
                </div>
              </div>
              <div className="role-overview-card">
                <div className="role-overview-icon" style={{ background: '#f0a040' }}>📋</div>
                <div>
                  <strong>方案规划师 (planner)</strong>
                  <p>只读探索 + 委派，产出结构化计划</p>
                </div>
              </div>
              <div className="role-overview-card">
                <div className="role-overview-icon" style={{ background: '#50c878' }}>💻</div>
                <div>
                  <strong>编码专家 (coder)</strong>
                  <p>读写代码、执行命令，不委派</p>
                </div>
              </div>
              <div className="role-overview-card">
                <div className="role-overview-icon" style={{ background: '#d080f0' }}>🔍</div>
                <div>
                  <strong>代码审查员 (reviewer)</strong>
                  <p>只读审查，检查质量与安全性</p>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Footer */}
        <div className="setup-footer">
          {step > 0 && (
            <button className="btn-secondary" onClick={() => setStep(step - 1)} disabled={busy}>
              <ChevronLeft size={16} /> 上一步
            </button>
          )}
          <div className="setup-footer-spacer" />
          {step < 2 ? (
            <button className="btn-primary" onClick={() => setStep(step + 1)} disabled={busy || !canNext()}>
              下一步 <ChevronRight size={16} />
            </button>
          ) : (
            <button className="btn-primary setup-finish-btn" onClick={handleComplete} disabled={busy}>
              {busy ? <Loader2 size={16} className="spinner" /> : <Check size={16} />}
              {busy ? '配置中...' : '完成配置'}
            </button>
          )}
        </div>
      </div>
    </div>,
    document.body
  );
}
