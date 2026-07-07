import { useState, useEffect, useRef, useCallback } from 'react';
import {
  Upload, Trash2, Check, ChevronDown, Image as ImageIcon,
  Sun, Moon, Monitor, Palette, Type as TypeIcon,
} from 'lucide-react';
import { applyTheme } from '../theme';
import { useToast } from './Toast';
import type { AppearanceConfig, WallpaperPreset, WallpaperStatus } from '../types';

interface AppearanceSettingsProps {
  config: AppearanceConfig;
  onChange: (config: AppearanceConfig) => void;
}

const MODE_OPTIONS = [
  { value: 'auto', label: '跟随系统', icon: Monitor },
  { value: 'light', label: '浅色', icon: Sun },
  { value: 'dark', label: '深色', icon: Moon },
];

// MD3-inspired color palette (matches Neo-MoFox WebUI)
const COLOR_PRESETS: { id: string; label: string; hex: string }[] = [
  { id: 'deepBlue', label: '深空蓝', hex: '#0058BD' },
  { id: 'emeraldGreen', label: '翡翠绿', hex: '#1B8F6E' },
  { id: 'coralOrange', label: '珊瑚橙', hex: '#E8591A' },
  { id: 'lavender', label: '薰衣草', hex: '#7C4DFF' },
  { id: 'rose', label: '玫瑰红', hex: '#C2185B' },
  { id: 'golden', label: '金黄色', hex: '#F9A825' },
  { id: 'teal', label: '青碧', hex: '#0EA5E9' },
  { id: 'violet', label: '紫罗兰', hex: '#7C3AED' },
];

export function AppearanceSettings({ config, onChange }: AppearanceSettingsProps) {
  const [localConfig, setLocalConfig] = useState<AppearanceConfig>(config);
  const [wallpaperStatus, setWallpaperStatus] = useState<WallpaperStatus | null>(null);
  const [presets, setPresets] = useState<WallpaperPreset[]>([]);
  const [presetsLoading, setPresetsLoading] = useState(false);
  const [presetsExpanded, setPresetsExpanded] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [confirmingRemove, setConfirmingRemove] = useState(false);
  const [wallpaperColors, setWallpaperColors] = useState<string[]>([]);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const toast = useToast();

  // Sync with parent config
  useEffect(() => { setLocalConfig(config); }, [config]);

  // Fetch structured wallpaper status (image vs video)
  const refreshStatus = useCallback(async () => {
    try {
      const r = await fetch('/api/wallpaper/status');
      if (r.ok) setWallpaperStatus(await r.json());
    } catch {}
  }, []);

  useEffect(() => { void refreshStatus(); }, [refreshStatus]);

  // Load built-in preset wallpapers
  useEffect(() => {
    let cancelled = false;
    setPresetsLoading(true);
    fetch('/api/wallpaper/presets')
      .then((r) => (r.ok ? r.json() : { presets: [] }))
      .then((data) => { if (!cancelled) setPresets(data.presets || []); })
      .catch(() => { if (!cancelled) setPresets([]); })
      .finally(() => { if (!cancelled) setPresetsLoading(false); });
    return () => { cancelled = true; };
  }, []);

  // Persist non-wallpaper changes (debounced)
  const debouncedSave = useCallback((newConfig: AppearanceConfig) => {
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(async () => {
      setSaving(true);
      try {
        const res = await fetch('/api/appearance', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(newConfig),
        });
        if (res.ok) {
          const data = await res.json();
          onChange(data.appearance);
        } else {
          toast.error('保存失败');
        }
      } catch (err) {
        toast.error('网络错误：' + (err as Error).message);
      } finally {
        setSaving(false);
      }
    }, 500);
  }, [onChange, toast]);

  useEffect(() => () => {
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
  }, []);

  // Generic field update (mode, color, font_size, blur, opacity)
  function updateField<K extends keyof AppearanceConfig>(key: K, value: AppearanceConfig[K]) {
    const updated = { ...localConfig, [key]: value };
    setLocalConfig(updated);
    applyTheme(updated);
    debouncedSave(updated);
  }

  // Wallpaper changes are immediate (no debounce)
  function applyWallpaperAppearance(partial: Partial<AppearanceConfig>) {
    const updated = { ...localConfig, ...partial } as AppearanceConfig;
    setLocalConfig(updated);
    applyTheme(updated);
    if (onChange) onChange(updated);
    debouncedSave(updated);
    void refreshStatus();
  }

  // Memoised preview URL — only changes when wallpaperVersion bumps
  const previewUrl = localConfig.wallpaper
    ? `/api/wallpaper?v=${Date.now()}`
    : null;

  // ─── Wallpaper handlers ───

  async function handleWallpaperUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > 50 * 1024 * 1024) {
      toast.error('文件过大（最大 50MB）');
      return;
    }
    setUploading(true);
    const formData = new FormData();
    formData.append('file', file);
    try {
      const res = await fetch('/api/wallpaper', { method: 'POST', body: formData });
      if (res.ok) {
        const data = await res.json();
        applyWallpaperAppearance({ wallpaper: data.appearance.wallpaper });
        toast.success('壁纸已更新');
      } else {
        const err = await res.json().catch(() => ({}));
        toast.error(err.error || '上传失败');
      }
    } catch (err) {
      toast.error('上传失败：' + (err as Error).message);
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  }

  async function handleApplyPreset(preset: WallpaperPreset) {
    try {
      const res = await fetch(`/api/wallpaper/preset/${preset.id}`, { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        applyWallpaperAppearance({ wallpaper: data.appearance.wallpaper });
        toast.success(`已应用「${preset.label}」`);
      } else {
        toast.error('应用预设失败');
      }
    } catch (err) {
      toast.error('网络错误：' + (err as Error).message);
    }
  }

  function askRemoveWallpaper() {
    if (!localConfig.wallpaper) return;
    setConfirmingRemove(true);
  }

  async function confirmRemoveWallpaper() {
    setConfirmingRemove(false);
    try {
      const res = await fetch('/api/wallpaper', { method: 'DELETE' });
      if (res.ok) {
        const data = await res.json();
        applyWallpaperAppearance({ wallpaper: data.appearance.wallpaper });
        toast.info('已移除壁纸');
      } else {
        toast.error('移除失败');
      }
    } catch (err) {
      toast.error('网络错误：' + (err as Error).message);
    }
  }

  // Color source detection
  const activeColor = localConfig.theme_color.toLowerCase();
  const isPresetColor = COLOR_PRESETS.some((c) => c.hex.toLowerCase() === activeColor);
  const isWallpaperColor = wallpaperColors.includes(localConfig.theme_color);
  const colorSource = isPresetColor ? 'preset' : isWallpaperColor ? 'wallpaper' : 'custom';

  return (
    <div className="setting-section" style={{ gap: '1.75rem' }}>
      {/* ===== Appearance Mode Cards ===== */}
      <section className="setting-section">
        <div className="section-header">
          <h3 className="section-heading">外观模式</h3>
          <p className="section-desc">选择浅色、深色或跟随系统</p>
        </div>
        <div className="mode-grid">
          {MODE_OPTIONS.map((opt) => {
            const Icon = opt.icon;
            const active = localConfig.mode === opt.value;
            return (
              <button
                key={opt.value}
                className={`mode-card${active ? ' active' : ''}`}
                onClick={() => updateField('mode', opt.value)}
              >
                {active && (
                  <div className="mode-check">
                    <Check size={12} strokeWidth={3} />
                  </div>
                )}
                <div className="mode-card-icon">
                  <Icon size={20} />
                </div>
                <span>{opt.label}</span>
              </button>
            );
          })}
        </div>
      </section>

      {/* ===== Theme Layout (Wallpaper + Colors) ===== */}
      <section className="setting-section">
        <div className="section-header">
          <h3 className="section-heading">主题</h3>
          <p className="section-desc">选择壁纸与主题色，营造你的专属风格</p>
        </div>

        <div className="theme-layout">
          {/* ---- Wallpaper Card ---- */}
          <div className="theme-card">
            <div className="theme-card-header">
              <div className="theme-card-title">
                <span className="theme-card-title-icon"><ImageIcon size={18} /></span>
                <span>壁纸</span>
              </div>
              <div className="theme-card-actions">
                {localConfig.wallpaper && (
                  <button
                    className="icon-btn danger"
                    onClick={askRemoveWallpaper}
                    disabled={uploading}
                    title="移除壁纸"
                  >
                    <Trash2 size={16} />
                  </button>
                )}
                <button
                  className="text-btn"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={uploading}
                >
                  <Upload size={14} />
                  {uploading ? '上传中…' : (localConfig.wallpaper ? '更换' : '上传')}
                </button>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".jpg,.jpeg,.png,.webp,.gif,.mp4,.webm"
                  style={{ display: 'none' }}
                  onChange={handleWallpaperUpload}
                />
              </div>
            </div>

            <div
              className={`wallpaper-preview-lg${localConfig.wallpaper ? '' : ' empty'}`}
            >
              {localConfig.wallpaper && wallpaperStatus?.wallpaper_type !== 'video' && (
                <img
                  src={`/api/wallpaper?v=${Date.now()}`}
                  alt="当前壁纸"
                  onError={(e) => {
                    // Gracefully hide broken image if file doesn't exist
                    (e.target as HTMLImageElement).style.display = 'none';
                  }}
                />
              )}
              {localConfig.wallpaper && wallpaperStatus?.wallpaper_type === 'video' && (
                <video
                  src={`/api/wallpaper?v=${Date.now()}`}
                  autoPlay
                  loop
                  muted
                  playsInline
                  onError={() => {}}
                />
              )}
              {wallpaperStatus?.wallpaper_type === 'video' && (
                <div className="wallpaper-type-badge">
                  <span>●</span> 视频
                </div>
              )}
              {!localConfig.wallpaper && (
                <>
                  <ImageIcon size={36} className="wallpaper-empty-icon" />
                  <span>点击「上传」或选择预设</span>
                </>
              )}
            </div>

            {/* Sliders */}
            <div className={`wallpaper-slider-grid${localConfig.wallpaper ? '' : ' disabled'}`}>
              <div className="slider-row">
                <span className="slider-label">模糊度</span>
                <input
                  type="range"
                  className="slider-track"
                  min={0}
                  max={30}
                  step={1}
                  value={localConfig.wallpaper_blur}
                  disabled={!localConfig.wallpaper}
                  onChange={(e) => updateField('wallpaper_blur', parseFloat(e.target.value))}
                />
                <span className="slider-val">{localConfig.wallpaper_blur}px</span>
              </div>
              <div className="slider-row">
                <span className="slider-label">不透明度</span>
                <input
                  type="range"
                  className="slider-track"
                  min={0}
                  max={1}
                  step={0.05}
                  value={localConfig.wallpaper_opacity}
                  disabled={!localConfig.wallpaper}
                  onChange={(e) => updateField('wallpaper_opacity', parseFloat(e.target.value))}
                />
                <span className="slider-val">{Math.round(localConfig.wallpaper_opacity * 100)}%</span>
              </div>
            </div>

            {/* Preset toggle */}
            <button
              className={`wallpaper-presets-toggle${presetsExpanded ? ' expanded' : ''}`}
              onClick={() => setPresetsExpanded((v) => !v)}
            >
              <ImageIcon size={14} />
              <span>内置预设 {presets.length > 0 && `(${presets.length})`}</span>
              <ChevronDown size={14} className="chevron" />
            </button>
            <div className={`wallpaper-presets-panel${presetsExpanded ? ' expanded' : ''}`}>
              {presetsLoading ? (
                <div className="wallpaper-loading">加载中…</div>
              ) : presets.length === 0 ? (
                <div className="wallpaper-loading">无可用预设</div>
              ) : (
                <div className="wallpaper-preset-grid">
                  {presets.map((p) => (
                    <button
                      key={p.id}
                      className="wallpaper-preset-thumb"
                      onClick={() => handleApplyPreset(p)}
                      title={`应用「${p.label}」`}
                    >
                      <img src={`/api/wallpaper/presets/${p.id}`} alt={p.label} loading="lazy" />
                      <span className="wallpaper-preset-label">{p.label}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* ---- Theme Color Card ---- */}
          <div className="theme-card">
            <div className="theme-card-header">
              <div className="theme-card-title">
                <span className="theme-card-title-icon"><Palette size={18} /></span>
                <span>主题色</span>
              </div>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              {/* Wallpaper-extracted colors (placeholder for now) */}
              {wallpaperColors.length > 0 && (
                <div className="color-group">
                  <div className="color-group-title">
                    <span>壁纸取色</span>
                    {colorSource === 'wallpaper' && (
                      <span className="active-badge">当前</span>
                    )}
                  </div>
                  <div className="color-swatch-row">
                    {wallpaperColors.map((hex, i) => (
                      <button
                        key={hex}
                        className={`color-swatch${activeColor === hex.toLowerCase() ? ' active' : ''}`}
                        style={{ background: hex }}
                        title={`壁纸色 ${i + 1}`}
                        onClick={() => updateField('theme_color', hex)}
                      >
                        {activeColor === hex.toLowerCase() && (
                          <Check size={18} className="color-swatch-icon" strokeWidth={3} />
                        )}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Preset colors */}
              <div className="color-group">
                <div className="color-group-title">
                  <span>预设颜色</span>
                  {colorSource === 'preset' && (
                    <span className="active-badge">当前</span>
                  )}
                </div>
                <div className="color-swatch-row">
                  {COLOR_PRESETS.map((c) => {
                    const active = c.hex.toLowerCase() === activeColor;
                    return (
                      <button
                        key={c.id}
                        className={`color-swatch${active ? ' active' : ''}`}
                        style={{ background: c.hex }}
                        title={c.label}
                        onClick={() => {
                          setLocalConfig((prev) => ({ ...prev, theme_color: c.hex, accent_preset: c.id }));
                          applyTheme({ ...localConfig, theme_color: c.hex, accent_preset: c.id });
                          debouncedSave({ ...localConfig, theme_color: c.hex, accent_preset: c.id });
                        }}
                      >
                        {active && (
                          <Check size={18} className="color-swatch-icon" strokeWidth={3} />
                        )}
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Custom color picker */}
              <div className="color-group">
                <div className="color-group-title">
                  <span>自定义</span>
                  {colorSource === 'custom' && (
                    <span className="active-badge">当前</span>
                  )}
                </div>
                <div className="custom-color-row">
                  <label
                    className="color-picker-wrap"
                    style={{ background: localConfig.theme_color }}
                    title="选择自定义颜色"
                  >
                    <input
                      type="color"
                      value={localConfig.theme_color}
                      onChange={(e) => {
                        const hex = e.target.value;
                        setLocalConfig((prev) => ({ ...prev, theme_color: hex, accent_preset: 'custom' }));
                        applyTheme({ ...localConfig, theme_color: hex, accent_preset: 'custom' });
                        debouncedSave({ ...localConfig, theme_color: hex, accent_preset: 'custom' });
                      }}
                    />
                  </label>
                  <input
                    type="text"
                    className="color-hex-input"
                    value={localConfig.theme_color}
                    onChange={(e) => {
                      const hex = e.target.value;
                      if (/^#[0-9a-fA-F]{6}$/.test(hex)) {
                        setLocalConfig((prev) => ({ ...prev, theme_color: hex, accent_preset: 'custom' }));
                        applyTheme({ ...localConfig, theme_color: hex, accent_preset: 'custom' });
                        debouncedSave({ ...localConfig, theme_color: hex, accent_preset: 'custom' });
                      }
                    }}
                    placeholder="#0058BD"
                    maxLength={7}
                  />
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ===== Font Size ===== */}
      <section className="setting-section">
        <div className="section-header">
          <h3 className="section-heading">字号</h3>
          <p className="section-desc">调整全局文字大小</p>
        </div>
        <div className="slider-card">
          <div className="slider-row">
            <span className="slider-label">
              <TypeIcon size={14} style={{ display: 'inline', verticalAlign: 'middle', marginRight: 4 }} />
              基础字号
            </span>
            <input
              type="range"
              className="slider-track"
              min={12}
              max={20}
              step={1}
              value={localConfig.font_size}
              onChange={(e) => updateField('font_size', parseInt(e.target.value, 10))}
            />
            <span className="slider-val">{localConfig.font_size}px</span>
          </div>
          <div className="font-preview" style={{ fontSize: `${localConfig.font_size}px` }}>
            这是字号预览文本。The quick brown fox jumps over the lazy dog.
          </div>
        </div>
      </section>

      {saving && (
        <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textAlign: 'right' }}>
          保存中…
        </div>
      )}

      {/* Remove-wallpaper confirmation */}
      {confirmingRemove && (
        <div className="confirm-overlay" onClick={() => setConfirmingRemove(false)}>
          <div className="confirm-dialog" onClick={(e) => e.stopPropagation()}>
            <div className="confirm-title">移除壁纸？</div>
            <div className="confirm-body">当前壁纸将被删除，恢复纯色背景。</div>
            <div className="confirm-actions">
              <button
                className="btn-outlined"
                onClick={() => setConfirmingRemove(false)}
              >
                取消
              </button>
              <button
                className="btn-filled"
                style={{ background: 'var(--tertiary)' }}
                onClick={confirmRemoveWallpaper}
              >
                移除
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
