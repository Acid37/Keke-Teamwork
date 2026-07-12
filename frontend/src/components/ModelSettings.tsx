import { useState, useEffect, useCallback } from 'react';
import { Plus, Trash2, Edit2, Save, X, Loader2, RefreshCw, Check } from 'lucide-react';
import type { APIProvider, ModelInfo } from '../types';

interface ModelSettingsProps {
  /** 当前完整配置（含 providers/models）*/
  config: {
    providers: APIProvider[];
    models: ModelInfo[];
    main_model: string;
    title_model: string | null;
  };
  /** 触发整体重载（保存后由父组件调用）*/
  onConfigChange: (config: ModelSettingsProps['config']) => void;
  /** Toast 提示（外部传入，避免依赖）*/
  onMessage?: (kind: 'success' | 'error', text: string) => void;
}

const CLIENT_TYPE_OPTIONS = [
  { value: 'openai', label: 'OpenAI 兼容' },
  { value: 'anthropic', label: 'Anthropic' },
  { value: 'gemini', label: 'Google Gemini' },
];

const QUICK_PRESETS = [
  { name: 'DeepSeek', url: 'https://api.deepseek.com' },
  { name: '通义千问', url: 'https://dashscope.aliyuncs.com/compatible-mode/v1' },
  { name: 'GLM', url: 'https://open.bigmodel.cn/api/paas/v4' },
  { name: 'Kimi', url: 'https://api.moonshot.cn/v1' },
  { name: 'Step', url: 'https://api.stepfun.com/v1' },
  { name: 'MiniMax', url: 'https://api.minimax.chat/v1' },
  { name: 'OpenAI', url: 'https://api.openai.com/v1' },
];

export function ModelSettings({ config, onConfigChange, onMessage }: ModelSettingsProps) {
  const [providerDraft, setProviderDraft] = useState<Partial<APIProvider> | null>(null);
  const [editingProviderName, setEditingProviderName] = useState<string | null>(null);
  const [modelDraft, setModelDraft] = useState<Partial<ModelInfo> | null>(null);
  const [editingModelName, setEditingModelName] = useState<string | null>(null);
  const [modelList, setModelList] = useState<string[]>([]);
  const [loadingModels, setLoadingModels] = useState(false);
  const [busy, setBusy] = useState(false);

  const fetchModelsFor = useCallback(async (providerName: string) => {
    setLoadingModels(true);
    try {
      const res = await fetch(`/api/models?provider=${encodeURIComponent(providerName)}`);
      const data = await res.json();
      setModelList(data.models || []);
    } catch {
      setModelList([]);
    } finally {
      setLoadingModels(false);
    }
  }, []);

  // 切换 provider 时自动加载模型列表
  useEffect(() => {
    if (modelDraft?.provider_name) {
      fetchModelsFor(modelDraft.provider_name);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modelDraft?.provider_name]);

  // ─── Provider CRUD ───

  async function handleAddProvider() {
    if (!providerDraft?.name?.trim()) {
      onMessage?.('error', '请填写提供商名称');
      return;
    }
    if (config.providers.find(p => p.name === providerDraft.name)) {
      onMessage?.('error', `提供商 ${providerDraft.name} 已存在`);
      return;
    }
    setBusy(true);
    try {
      const res = await fetch('/api/config/providers', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(providerDraft),
      });
      const data = await res.json();
      if (data.error) {
        onMessage?.('error', data.error);
        return;
      }
      onMessage?.('success', `已添加提供商 ${data.provider.name}`);
      setProviderDraft(null);
      onConfigChange({ ...config, providers: [...config.providers, data.provider] });
    } catch (e) {
      onMessage?.('error', '网络错误：' + (e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function handleUpdateProvider(name: string, body: Partial<APIProvider>) {
    setBusy(true);
    try {
      const res = await fetch(`/api/config/providers/${encodeURIComponent(name)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (data.error) {
        onMessage?.('error', data.error);
        return;
      }
      // 本地同步
      const newProviders = config.providers.map(p =>
        p.name === name ? { ...p, ...data.provider } : p
      );
      onConfigChange({ ...config, providers: newProviders });
      onMessage?.('success', '已更新');
      setEditingProviderName(null);
    } catch (e) {
      onMessage?.('error', '网络错误：' + (e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function handleDeleteProvider(name: string) {
    if (!confirm(`删除提供商 "${name}"？`)) return;
    setBusy(true);
    try {
      const res = await fetch(`/api/config/providers/${encodeURIComponent(name)}`, { method: 'DELETE' });
      const data = await res.json();
      if (data.error) {
        onMessage?.('error', data.error);
        return;
      }
      onConfigChange({ ...config, providers: config.providers.filter(p => p.name !== name) });
      onMessage?.('success', '已删除');
    } catch (e) {
      onMessage?.('error', '网络错误：' + (e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  // ─── Model CRUD ───

  async function handleAddModel() {
    if (!modelDraft?.name?.trim() || !modelDraft?.model_id?.trim() || !modelDraft?.provider_name) {
      onMessage?.('error', '请填写名称、模型 ID 和所属提供商');
      return;
    }
    setBusy(true);
    try {
      const res = await fetch('/api/config/models', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(modelDraft),
      });
      const data = await res.json();
      if (data.error) {
        onMessage?.('error', data.error);
        return;
      }
      onConfigChange({ ...config, models: [...config.models, data.model] });
      onMessage?.('success', `已添加模型 ${data.model.name}`);
      setModelDraft(null);
    } catch (e) {
      onMessage?.('error', '网络错误：' + (e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function handleUpdateModel(name: string, body: Partial<ModelInfo>) {
    setBusy(true);
    try {
      const res = await fetch(`/api/config/models/${encodeURIComponent(name)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (data.error) {
        onMessage?.('error', data.error);
        return;
      }
      onConfigChange({ ...config, models: config.models.map(m =>
        m.name === name ? { ...m, ...data.model } : m
      )});
      onMessage?.('success', '已更新');
      setEditingModelName(null);
    } catch (e) {
      onMessage?.('error', '网络错误：' + (e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function handleDeleteModel(name: string) {
    if (!confirm(`删除模型 "${name}"？`)) return;
    setBusy(true);
    try {
      const res = await fetch(`/api/config/models/${encodeURIComponent(name)}`, { method: 'DELETE' });
      const data = await res.json();
      if (data.error) {
        onMessage?.('error', data.error);
        return;
      }
      onConfigChange({ ...config, models: config.models.filter(m => m.name !== name) });
      onMessage?.('success', '已删除');
    } catch (e) {
      onMessage?.('error', '网络错误：' + (e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  // ─── 模型用途配置 ───

  async function handleModelSettingChange(role: 'main_model' | 'title_model', alias: string) {
    const body = { [role]: alias || null };
    setBusy(true);
    try {
      const res = await fetch('/api/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (data.error) {
        onMessage?.('error', data.error);
        return;
      }
      onConfigChange({ ...config, [role]: alias || null });
    } catch (e) {
      onMessage?.('error', '网络错误：' + (e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  // ─── 渲染 ───

  return (
    <div className="model-settings">
      {/* ─── Provider 列表 ─── */}
      <section className="settings-section">
        <div className="section-header">
          <h3>API 提供商</h3>
          {!providerDraft && (
            <button
              className="btn-text"
              onClick={() => setProviderDraft({
                name: '',
                client_type: 'openai',
                base_url: 'https://api.deepseek.com',
                api_key: '',
                enabled: true,
              })}
            >
              <Plus size={14} /> 添加
            </button>
          )}
        </div>

        {/* 新增 provider 表单 */}
        {providerDraft && (
          <div className="provider-form">
            <div className="form-row">
              <label>名称</label>
              <input
                value={providerDraft.name ?? ''}
                onChange={e => setProviderDraft({ ...providerDraft, name: e.target.value })}
                placeholder="如 deepseek、anthropic"
              />
            </div>
            <div className="form-row">
              <label>类型</label>
              <select
                value={providerDraft.client_type ?? 'openai'}
                onChange={e => setProviderDraft({ ...providerDraft, client_type: e.target.value as any })}
              >
                {CLIENT_TYPE_OPTIONS.map(o => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </div>
            {providerDraft.client_type === 'openai' && (
              <>
                <div className="form-row">
                  <label>API 地址</label>
                  <input
                    value={providerDraft.base_url ?? ''}
                    onChange={e => setProviderDraft({ ...providerDraft, base_url: e.target.value })}
                    placeholder="https://api.deepseek.com"
                  />
                  <div className="quick-presets">
                    {QUICK_PRESETS.map(p => (
                      <button
                        key={p.name}
                        className="chip"
                        onClick={() => setProviderDraft({ ...providerDraft, base_url: p.url })}
                      >{p.name}</button>
                    ))}
                  </div>
                </div>
              </>
            )}
            <div className="form-row">
              <label>API Key</label>
              <input
                type="password"
                value={providerDraft.api_key ?? ''}
                onChange={e => setProviderDraft({ ...providerDraft, api_key: e.target.value })}
                placeholder="sk-..."
              />
            </div>
            <div className="form-actions">
              <button className="btn-secondary" onClick={() => setProviderDraft(null)}>取消</button>
              <button className="btn-primary" onClick={handleAddProvider} disabled={busy}>
                <Save size={14} /> 保存
              </button>
            </div>
          </div>
        )}

        <div className="provider-list">
          {config.providers.length === 0 && !providerDraft && (
            <div className="empty-hint">还没有提供商，点击「添加」配置一个</div>
          )}
          {config.providers.map(p => (
            <ProviderRow
              key={p.name}
              provider={p}
              isEditing={editingProviderName === p.name}
              onEdit={() => setEditingProviderName(p.name)}
              onCancelEdit={() => setEditingProviderName(null)}
              onSave={(body) => handleUpdateProvider(p.name, body)}
              onDelete={() => handleDeleteProvider(p.name)}
              busy={busy}
            />
          ))}
        </div>
      </section>

      {/* ─── Model 列表 ─── */}
      <section className="settings-section">
        <div className="section-header">
          <h3>模型</h3>
          {!modelDraft && (
            <button
              className="btn-text"
              onClick={() => setModelDraft({
                name: '',
                model_id: '',
                provider_name: config.providers[0]?.name || '',
                max_context: null,
              })}
            >
              <Plus size={14} /> 添加
            </button>
          )}
        </div>

        {modelDraft && (
          <div className="model-form">
            <div className="form-row">
              <label>别名</label>
              <input
                value={modelDraft.name ?? ''}
                onChange={e => setModelDraft({ ...modelDraft, name: e.target.value })}
                placeholder="如 main、coder-fast"
              />
            </div>
            <div className="form-row">
              <label>提供商</label>
              <select
                value={modelDraft.provider_name ?? ''}
                onChange={e => setModelDraft({ ...modelDraft, provider_name: e.target.value })}
              >
                {config.providers.map(p => (
                  <option key={p.name} value={p.name}>{p.name}</option>
                ))}
              </select>
            </div>
            <div className="form-row">
              <label>模型 ID</label>
              <div className="model-id-input">
                {modelList.length > 0 ? (
                  <select
                    value={modelDraft.model_id ?? ''}
                    onChange={e => setModelDraft({ ...modelDraft, model_id: e.target.value })}
                  >
                    <option value="">-- 选择模型 --</option>
                    {modelList.map(m => <option key={m} value={m}>{m}</option>)}
                  </select>
                ) : (
                  <input
                    value={modelDraft.model_id ?? ''}
                    onChange={e => setModelDraft({ ...modelDraft, model_id: e.target.value })}
                    placeholder="如 deepseek-chat、gpt-4o"
                  />
                )}
                <button
                  className="chip"
                  onClick={() => modelDraft.provider_name && fetchModelsFor(modelDraft.provider_name)}
                  disabled={loadingModels || !modelDraft.provider_name}
                >
                  {loadingModels ? <Loader2 size={12} className="spinner"/> : <RefreshCw size={12} />}
                  刷新
                </button>
              </div>
            </div>
            <div className="form-row">
              <label>上下文窗口 <span className="optional">（可选，如 128000）</span></label>
              <input
                type="number"
                min="0"
                value={modelDraft.max_context ?? ''}
                onChange={e => setModelDraft({ ...modelDraft, max_context: e.target.value === '' ? null : parseInt(e.target.value) || null })}
                placeholder="留空则使用默认 100000"
              />
            </div>
            <div className="form-actions">
              <button className="btn-secondary" onClick={() => setModelDraft(null)}>取消</button>
              <button className="btn-primary" onClick={handleAddModel} disabled={busy}>
                <Save size={14} /> 保存
              </button>
            </div>
          </div>
        )}

        <div className="model-list">
          {config.models.length === 0 && !modelDraft && (
            <div className="empty-hint">还没有模型，点击「添加」创建</div>
          )}
          {config.models.map(m => (
            <ModelRow
              key={m.name}
              model={m}
              providers={config.providers}
              isDefault={config.main_model === m.name}
              isTitle={config.title_model === m.name}
              isEditing={editingModelName === m.name}
              onEdit={() => setEditingModelName(m.name)}
              onCancelEdit={() => setEditingModelName(null)}
              onSave={(body) => handleUpdateModel(m.name, body)}
              onDelete={() => handleDeleteModel(m.name)}
              onSetDefault={() => handleModelSettingChange('main_model', m.name)}
              onSetTitle={() => handleModelSettingChange('title_model', m.name)}
              onFetchModels={fetchModelsFor}
              busy={busy}
            />
          ))}
        </div>
      </section>
    </div>
  );
}

// ─── 子组件 ───

function ProviderRow({
  provider,
  isEditing,
  onEdit,
  onCancelEdit,
  onSave,
  onDelete,
  busy,
}: {
  provider: APIProvider;
  isEditing: boolean;
  onEdit: () => void;
  onCancelEdit: () => void;
  onSave: (body: Partial<APIProvider>) => void;
  onDelete: () => void;
  busy: boolean;
}) {
  const [draft, setDraft] = useState<Partial<APIProvider>>(provider);

  if (!isEditing) {
    return (
      <div className="provider-row">
        <div className="provider-info">
          <div className="provider-name">
            {provider.name}
            {!provider.enabled && <span className="badge-disabled">已禁用</span>}
          </div>
          <div className="provider-detail">
            <span className="tag">{provider.client_type}</span>
            {provider.base_url && <span className="provider-url">{provider.base_url}</span>}
            {provider.api_key_masked && <span className="provider-key">{provider.api_key_masked}</span>}
          </div>
        </div>
        <div className="row-actions">
          <button className="btn-icon" onClick={onEdit} title="编辑"><Edit2 size={14}/></button>
          <button className="btn-icon" onClick={onDelete} title="删除" disabled={busy}><Trash2 size={14}/></button>
        </div>
      </div>
    );
  }

  return (
    <div className="provider-row editing">
      <div className="form-row">
        <label>名称</label>
        <input value={draft.name ?? provider.name} onChange={e => setDraft({ ...draft, name: e.target.value })} />
      </div>
      <div className="form-row">
        <label>类型</label>
        <select value={draft.client_type} onChange={e => setDraft({ ...draft, client_type: e.target.value as any })}>
          {CLIENT_TYPE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      </div>
      {draft.client_type === 'openai' && (
        <div className="form-row">
          <label>API 地址</label>
          <input value={draft.base_url ?? ''} onChange={e => setDraft({ ...draft, base_url: e.target.value })} />
        </div>
      )}
      <div className="form-row">
        <label>API Key（留空保留当前）</label>
        <input
          type="password"
          value={draft.api_key ?? ''}
          onChange={e => setDraft({ ...draft, api_key: e.target.value })}
          placeholder={provider.api_key_masked || '未设置'}
        />
      </div>
      <div className="form-row">
        <label>
          <input
            type="checkbox"
            checked={draft.enabled ?? true}
            onChange={e => setDraft({ ...draft, enabled: e.target.checked })}
          />
          启用
        </label>
      </div>
      <div className="form-actions">
        <button className="btn-secondary" onClick={onCancelEdit}>取消</button>
        <button className="btn-primary" onClick={() => onSave(draft)} disabled={busy}>
          <Save size={14}/> 保存
        </button>
      </div>
    </div>
  );
}

function ModelRow({
  model,
  providers,
  isDefault,
  isTitle,
  isEditing,
  onEdit,
  onCancelEdit,
  onSave,
  onDelete,
  onSetDefault,
  onSetTitle,
  onFetchModels,
  busy,
}: {
  model: ModelInfo;
  providers: APIProvider[];
  isDefault: boolean;
  isTitle: boolean;
  isEditing: boolean;
  onEdit: () => void;
  onCancelEdit: () => void;
  onSave: (body: Partial<ModelInfo>) => void;
  onDelete: () => void;
  onSetDefault: () => void;
  onSetTitle: () => void;
  onFetchModels: (provider: string) => void;
  busy: boolean;
}) {
  const [draft, setDraft] = useState<Partial<ModelInfo>>(model);
  const [modelList, setModelList] = useState<string[]>([]);
  const [loadingModels, setLoadingModels] = useState(false);

  const refreshModels = useCallback(async () => {
    if (!draft.provider_name) return;
    setLoadingModels(true);
    try {
      const res = await fetch(`/api/models?provider=${encodeURIComponent(draft.provider_name)}`);
      const data = await res.json();
      setModelList(data.models || []);
    } catch {
      setModelList([]);
    } finally {
      setLoadingModels(false);
    }
  }, [draft.provider_name]);

  useEffect(() => {
    if (isEditing) refreshModels();
  }, [isEditing, refreshModels]);

  if (!isEditing) {
    return (
      <div className="model-row">
        <div className="model-info">
          <div className="model-name">{model.name}</div>
          <div className="model-detail">
            <span className="tag">{model.provider_name}</span>
            {isDefault && <span className="tag tag-accent">默认</span>}
            {isTitle && <span className="tag tag-accent">标题</span>}
            <span className="model-id">{model.model_id}</span>
            {model.max_context && <span className="model-ctx">{model.max_context} ctx</span>}
          </div>
        </div>
        <div className="row-actions">
          {!isDefault && (
            <button className="btn-icon btn-mini-text" onClick={onSetDefault} title="设为默认模型" disabled={busy}>
              默认
            </button>
          )}
          {!isTitle && (
            <button className="btn-icon btn-mini-text" onClick={onSetTitle} title="设为标题生成模型" disabled={busy}>
              标题
            </button>
          )}
          <button className="btn-icon" onClick={onEdit} title="编辑"><Edit2 size={14}/></button>
          <button className="btn-icon" onClick={onDelete} title="删除" disabled={busy}><Trash2 size={14}/></button>
        </div>
      </div>
    );
  }

  return (
    <div className="model-row editing">
      <div className="form-row">
        <label>别名</label>
        <input value={draft.name ?? model.name} onChange={e => setDraft({ ...draft, name: e.target.value })} />
      </div>
      <div className="form-row">
        <label>提供商</label>
        <select value={draft.provider_name} onChange={e => setDraft({ ...draft, provider_name: e.target.value })}>
          {providers.map(p => <option key={p.name} value={p.name}>{p.name}</option>)}
        </select>
      </div>
      <div className="form-row">
        <label>模型 ID</label>
        <div className="model-id-input">
          {modelList.length > 0 ? (
            <select value={draft.model_id ?? ''} onChange={e => setDraft({ ...draft, model_id: e.target.value })}>
              <option value="">-- 选择 --</option>
              {modelList.map(m => <option key={m} value={m}>{m}</option>)}
            </select>
          ) : (
            <input value={draft.model_id ?? ''} onChange={e => setDraft({ ...draft, model_id: e.target.value })} />
          )}
          <button className="chip" onClick={refreshModels} disabled={loadingModels}>
            {loadingModels ? <Loader2 size={12} className="spinner"/> : <RefreshCw size={12}/>}
            刷新
          </button>
        </div>
      </div>
      <div className="form-row">
        <label>上下文窗口 <span className="optional">（可选，如 128000）</span></label>
        <input
          type="number"
          min="0"
          value={draft.max_context ?? ''}
          onChange={e => setDraft({ ...draft, max_context: e.target.value === '' ? null : parseInt(e.target.value) || null })}
          placeholder="留空则使用默认 100000"
        />
      </div>
      <div className="form-actions">
        <button className="btn-secondary" onClick={onCancelEdit}>取消</button>
        <button className="btn-primary" onClick={() => onSave(draft)} disabled={busy}>
          <Save size={14}/> 保存
        </button>
      </div>
    </div>
  );
}

