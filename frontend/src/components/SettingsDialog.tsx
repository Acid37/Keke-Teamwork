import { useState, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { X, Loader2 } from 'lucide-react';
import { AgentManager } from './AgentManager';
import { AppearanceSettings } from './AppearanceSettings';
import { ModelSettings } from './ModelSettings';
import type { AppearanceConfig, APIProvider, ModelInfo } from '../types';

interface ConfigData {
  providers: APIProvider[];
  models: ModelInfo[];
  main_model: string;
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
  { id: 'model', label: '模型' },
  { id: 'agents', label: 'Agent 管理' },
  { id: 'appearance', label: '外观' },
];

export function SettingsDialog({ open, onClose, appearance, onAppearanceChange }: SettingsDialogProps) {
  const [activeTab, setActiveTab] = useState<TabId>('model');
  const [config, setConfig] = useState<ConfigData | null>(null);
  const [loading, setLoading] = useState(false);
  const [models, setModels] = useState<string[]>([]);
  const [loadingModels, setLoadingModels] = useState(false);
  const [toast, setToast] = useState<{ kind: 'success' | 'error'; text: string } | null>(null);

  const showToast = useCallback((kind: 'success' | 'error', text: string) => {
    setToast({ kind, text });
    setTimeout(() => setToast(null), 2500);
  }, []);

  const fetchConfig = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/config');
      const data = await res.json();
      setConfig({
        providers: data.providers || [],
        models: data.models || [],
        main_model: data.main_model || 'main',
        title_model: data.title_model ?? null,
        host: data.host,
        port: data.port,
      });
    } catch {
      showToast('error', '加载配置失败');
    } finally {
      setLoading(false);
    }
  }, [showToast]);

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
    }
  }, [open, fetchConfig, fetchModels]);

  function handleConfigChange(partial: Partial<ConfigData>) {
    setConfig(prev => prev ? { ...prev, ...partial } : prev);
  }

  if (!open) return null;
  if (!config) {
    return createPortal(
      <div className="settings-overlay" onClick={onClose}>
        <div className="settings-dialog" onClick={(e) => e.stopPropagation()}>
          <div className="settings-header">
            <h2>设置</h2>
            <button className="settings-close" onClick={onClose}>
              <X size={18} />
            </button>
          </div>
          <div className="settings-loading">
            {loading ? <Loader2 size={20} className="spinner" /> : '加载中...'}
          </div>
        </div>
      </div>,
      document.body
    );
  }

  return createPortal(
    <div className="settings-overlay" onClick={onClose}>
      <div className="settings-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="settings-header">
          <h2>设置</h2>
          <button className="settings-close" onClick={onClose}>
            <X size={18} />
          </button>
        </div>

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

        {toast && (
          <div className={`settings-toast settings-toast-${toast.kind}`}>
            {toast.text}
          </div>
        )}

        <div className="settings-body">
          {activeTab === 'model' && (
            <ModelSettings
              config={config}
              onConfigChange={handleConfigChange}
              onMessage={showToast}
            />
          )}
          {activeTab === 'agents' && (
            <AgentManager
              models={models}
              onFetchModels={fetchModels}
              loadingModels={loadingModels}
            />
          )}
          {activeTab === 'appearance' && (
            <AppearanceSettings
              config={appearance}
              onChange={onAppearanceChange}
            />
          )}
        </div>
      </div>
    </div>,
    document.body
  );
}