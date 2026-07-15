import { Shield, AlertTriangle, ToggleLeft, ToggleRight, Loader2 } from 'lucide-react';
import { apiPut } from '../utils/api';
import { useAsyncAction } from '../utils/useAsyncAction';

interface SecuritySettingsProps {
  config: {
    yolo_mode?: boolean;
    auto_review?: boolean;
    solo_mode?: boolean;
  };
  onConfigChange: (partial: Record<string, unknown>) => void;
  onMessage?: (kind: 'success' | 'error', text: string) => void;
}

export function SecuritySettings({ config, onConfigChange, onMessage }: SecuritySettingsProps) {
  const { busy, run } = useAsyncAction((msg) => onMessage?.('error', msg));

  async function saveSecuritySetting(key: string, value: unknown) {
    await run(async () => {
      await apiPut('/api/config', { [key]: value });
      onConfigChange({ [key]: value });
      onMessage?.('success', '安全设置已更新');
    });
  }

  return (
    <div className="security-settings">
      <div className="security-card">
        <div className="security-card-header">
          <Shield size={18} />
          <div>
            <h4>YOLO 模式</h4>
            <p className="security-desc">
              开启后所有命令自动执行，无需人工审批。仅建议在完全可信的环境中使用。
            </p>
          </div>
          <button
            className={`toggle-btn ${config.yolo_mode ? 'active' : ''}`}
            onClick={() => saveSecuritySetting('yolo_mode', !config.yolo_mode)}
            disabled={busy}
          >
            {busy ? <Loader2 size={28} className="spinner" /> :
              config.yolo_mode ? <ToggleRight size={28} /> : <ToggleLeft size={28} />}
          </button>
        </div>
        {config.yolo_mode && (
          <div className="security-warning">
            <AlertTriangle size={14} />
            <span>YOLO 模式下所有命令将自动执行，请注意安全风险</span>
          </div>
        )}
      </div>

      <div className="security-card">
        <div className="security-card-header">
          <Shield size={18} />
          <div>
            <h4>自动审查</h4>
            <p className="security-desc">
              代码变更后自动触发审查流程，确保代码质量和安全性。
            </p>
          </div>
          <button
            className={`toggle-btn ${config.auto_review ? 'active' : ''}`}
            onClick={() => saveSecuritySetting('auto_review', !config.auto_review)}
            disabled={busy}
          >
            {busy ? <Loader2 size={28} className="spinner" /> :
              config.auto_review ? <ToggleRight size={28} /> : <ToggleLeft size={28} />}
          </button>
        </div>
      </div>

      <div className="security-card">
        <div className="security-card-header">
          <Shield size={18} />
          <div>
            <h4>单 Agent 模式</h4>
            <p className="security-desc">
              禁用多 Agent 协作，所有任务由主 Agent 独立完成。适合简单任务。
            </p>
          </div>
          <button
            className={`toggle-btn ${config.solo_mode ? 'active' : ''}`}
            onClick={() => saveSecuritySetting('solo_mode', !config.solo_mode)}
            disabled={busy}
          >
            {busy ? <Loader2 size={28} className="spinner" /> :
              config.solo_mode ? <ToggleRight size={28} /> : <ToggleLeft size={28} />}
          </button>
        </div>
      </div>
    </div>
  );
}
