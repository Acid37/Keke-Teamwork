import { useState, useEffect, useCallback } from 'react'
import { SessionProvider } from './SessionContext'
import { SessionList } from './components/SessionList'
import { ChatArea } from './components/ChatArea'
import { MessageInput } from './components/MessageInput'
import { ToastProvider } from './components/Toast'
import { SetupWizard } from './components/SetupWizard'
import { applyTheme, setupAutoModeListener } from './theme'
import type { AppearanceConfig } from './types'

const DEFAULT_APPEARANCE: AppearanceConfig = {
  mode: 'dark',
  theme_color: '#4a9eff',
  wallpaper: null,
  wallpaper_blur: 10,
  wallpaper_opacity: 0.28,
  font_size: 14,
  accent_preset: 'blue',
}

function App() {
  const [appearance, setAppearance] = useState<AppearanceConfig>(DEFAULT_APPEARANCE)
  // Bump this every time the wallpaper file changes; combined with the URL
  // below, this gives the browser a cache-busting query string so a fresh
  // image is fetched even when the path is the same (`/api/wallpaper`).
  const [wallpaperVersion, setWallpaperVersion] = useState(0)
  const [wallpaperType, setWallpaperType] = useState<'image' | 'video' | 'none'>('none')
  const [showSetupWizard, setShowSetupWizard] = useState(false)
  const [checkingSetup, setCheckingSetup] = useState(true)

  // Load appearance config on mount
  useEffect(() => {
    fetch('/api/appearance')
      .then((res) => (res.ok ? res.json() : DEFAULT_APPEARANCE))
      .then((data: AppearanceConfig) => {
        setAppearance(data)
        applyTheme(data)
        if (data.wallpaper) setWallpaperVersion((v) => v + 1)
      })
      .catch(() => {
        applyTheme(DEFAULT_APPEARANCE)
      })

    // Fetch structured wallpaper status to know image vs video
    fetch('/api/wallpaper/status')
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data) setWallpaperType(data.wallpaper_type || 'none')
      })
      .catch(() => {})

    // Check if setup wizard is needed
    fetch('/api/setup/status')
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data && !data.setup_completed) {
          setShowSetupWizard(true)
        }
      })
      .catch(() => {})
      .finally(() => setCheckingSetup(false))
  }, [])

  // Set up auto-mode listener for system preference changes
  useEffect(() => {
    const cleanup = setupAutoModeListener(appearance, () => applyTheme(appearance))
    return () => {
      if (cleanup) cleanup()
    }
  }, [appearance])

  // Re-apply theme whenever appearance changes
  useEffect(() => {
    applyTheme(appearance)
  }, [appearance])

  // Bump version on any appearance-driven wallpaper change so the layer re-fetches.
  useEffect(() => {
    if (appearance.wallpaper) {
      setWallpaperVersion((v) => v + 1)
      const ext = appearance.wallpaper.split('.').pop()?.toLowerCase()
      setWallpaperType(ext === 'mp4' || ext === 'webm' ? 'video' : 'image')
    } else {
      setWallpaperType('none')
    }
  }, [appearance.wallpaper])

  const handleAppearanceChange = useCallback((newConfig: AppearanceConfig) => {
    setAppearance(newConfig)
  }, [])

  // Cache-busted URL for the wallpaper layer
  const wallpaperUrl = appearance.wallpaper
    ? `/api/wallpaper?v=${wallpaperVersion}`
    : null

  return (
    <ToastProvider>
      <SessionProvider>
        {/* Setup Wizard — shown on first run before main UI */}
        {!checkingSetup && (
          <SetupWizard
            open={showSetupWizard}
            onComplete={() => setShowSetupWizard(false)}
          />
        )}
        <div className={`app-container${wallpaperUrl ? ' has-wallpaper' : ''}`}>
          {/* Wallpaper background layer (fades in on change) */}
          {wallpaperUrl && wallpaperType === 'image' && (
            <div
              key={`wp-${wallpaperVersion}`}
              className="wallpaper-layer"
              style={{ backgroundImage: `url(${wallpaperUrl})` }}
            />
          )}
          {wallpaperUrl && wallpaperType === 'video' && (
            <video
              key={`wp-${wallpaperVersion}`}
              className="wallpaper-layer wallpaper-video"
              src={wallpaperUrl}
              autoPlay
              loop
              muted
              playsInline
            />
          )}
          <SessionList appearance={appearance} onAppearanceChange={handleAppearanceChange} />
          <div className={`main-area${wallpaperUrl ? ' has-wallpaper' : ''}`}>
            <ChatArea />
            <MessageInput />
          </div>
        </div>
      </SessionProvider>
    </ToastProvider>
  )
}

export { App, DEFAULT_APPEARANCE }
export default App
