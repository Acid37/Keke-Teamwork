import { createContext, useCallback, useContext, useEffect, useState, useRef } from 'react';
import { createPortal } from 'react-dom';
import { CheckCircle2, AlertCircle, Info, X } from 'lucide-react';

type ToastKind = 'success' | 'error' | 'info';

interface ToastItem {
  id: number;
  kind: ToastKind;
  message: string;
}

interface ToastApi {
  success: (msg: string) => void;
  error: (msg: string) => void;
  info: (msg: string) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    // No-op fallback so components rendered outside the provider still work
    return { success: () => {}, error: () => {}, info: () => {} };
  }
  return ctx;
}

let _id = 0;

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const timers = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map());

  const dismiss = useCallback((id: number) => {
    setToasts((cur) => cur.filter((t) => t.id !== id));
    const t = timers.current.get(id);
    if (t) {
      clearTimeout(t);
      timers.current.delete(id);
    }
  }, []);

  const push = useCallback(
    (kind: ToastKind, message: string, ttl = 3000) => {
      const id = ++_id;
      setToasts((cur) => [...cur, { id, kind, message }]);
      const t = setTimeout(() => dismiss(id), ttl);
      timers.current.set(id, t);
    },
    [dismiss]
  );

  // Cleanup all timers on unmount
  useEffect(() => {
    const m = timers.current;
    return () => {
      m.forEach((t) => clearTimeout(t));
      m.clear();
    };
  }, []);

  const api: ToastApi = {
    success: (msg) => push('success', msg),
    error: (msg) => push('error', msg, 5000),
    info: (msg) => push('info', msg),
  };

  return (
    <ToastContext.Provider value={api}>
      {children}
      {createPortal(
        <div className="toast-stack">
          {toasts.map((t) => (
            <div key={t.id} className={`toast toast-${t.kind}`}>
              <span className="toast-icon">
                {t.kind === 'success' && <CheckCircle2 size={16} />}
                {t.kind === 'error' && <AlertCircle size={16} />}
                {t.kind === 'info' && <Info size={16} />}
              </span>
              <span className="toast-message">{t.message}</span>
              <button
                className="toast-close"
                onClick={() => dismiss(t.id)}
                aria-label="关闭"
              >
                <X size={12} />
              </button>
            </div>
          ))}
        </div>,
        document.body
      )}
    </ToastContext.Provider>
  );
}
