/** DirectoryPicker — in-browser directory browser.
 *
 *  Sends `browse.directory` WebSocket messages and listens
 *  for `browse.directory_result` to navigate the server filesystem.
 *  Calls `onSelect(path)` when the user picks a directory.
 */

import { useState, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { Folder, ChevronRight, Home, HardDrive, X, Loader2 } from 'lucide-react';

interface DirEntry { name: string; is_dir: boolean }

interface Props {
  initialPath?: string;
  onSelect: (path: string) => void;
  onCancel: () => void;
}

export function DirectoryPicker({ initialPath = '', onSelect, onCancel }: Props) {
  const [path, setPath] = useState(initialPath);
  const [parent, setParent] = useState<string | null>(null);
  const [entries, setEntries] = useState<DirEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const browse = useCallback((p: string) => {
    setLoading(true);
    setError(null);
    try {
      const ws = new WebSocket(`ws://${location.hostname}:8765/ws`);
      const handleOpen = () => {
        ws.send(JSON.stringify({
          type: 'browse.directory',
          id: Date.now().toString(36),
          payload: { path: p },
        }));
      };
      const handleMsg = (e: MessageEvent) => {
        const msg = JSON.parse(e.data);
        if (msg.type === 'browse.directory_result') {
          const payload = msg.payload || {};
          setPath(payload.path || p);
          setParent(payload.parent ?? null);
          setEntries(payload.entries || []);
          if (payload.error) setError(payload.error);
          setLoading(false);
          ws.close();
        }
      };
      ws.onopen = handleOpen;
      ws.onmessage = handleMsg;
      ws.onerror = () => { setError('Connection failed'); setLoading(false); ws.close(); };
      setTimeout(() => { if (ws.readyState !== WebSocket.CLOSED) { setError('Timeout'); setLoading(false); ws.close(); } }, 5000);
    } catch (e) {
      setError(String(e));
      setLoading(false);
    }
  }, []);

  useEffect(() => { browse(initialPath); }, [initialPath, browse]);

  const enterDir = (name: string) => {
    if (isDriveRoot && /^[A-Z]:\\?$/.test(name)) {
      browse(name);
      return;
    }
    const sep = path.endsWith('\\') || path.endsWith('/') ? '' : '\\';
    browse(path + sep + name);
  };

  const goParent = () => { if (parent !== null) browse(parent); };
  const isDriveRoot = path === '' || path === '/' || path === '根目录';

  return createPortal(
    <div className="confirm-overlay" onClick={onCancel}>
      <div className="directory-picker" onClick={e => e.stopPropagation()}>
        <div className="directory-picker-header">
          <h2>选择目录</h2>
          <button className="icon-btn" onClick={onCancel}><X size={16}/></button>
        </div>

        <div className="directory-picker-nav">
          <button className="icon-btn" onClick={() => browse('根目录')} disabled={loading} title="驱动盘列表"><Home size={16}/></button>
          <button className="text-btn" onClick={goParent} disabled={parent === null || loading}>..</button>
          <span className="directory-picker-path">{isDriveRoot ? '💻 选择驱动盘...' : path}</span>
        </div>

        <div className="directory-picker-list">
          {loading ? (
            <div className="directory-picker-status"><Loader2 size={16} className="spinner"/> 加载中…</div>
          ) : error ? (
            <div className="directory-picker-status error">{error}</div>
          ) : entries.length === 0 ? (
            <div className="directory-picker-status">此目录为空</div>
          ) : (
            entries.map(e => (
              <div key={e.name} className={`directory-picker-entry ${e.is_dir ? '' : 'file'}`}>
                <div className="directory-picker-entry-name" onClick={() => e.is_dir && enterDir(e.name)}>
                  {e.is_dir ? (
                    isDriveRoot && /^[A-Z]:\\?$/.test(e.name) ? <HardDrive size={16} className="text-blue-500"/> : <Folder size={16} className="text-amber-500"/>
                  ) : (
                    <ChevronRight size={16} className="text-gray-500"/>
                  )}
                  <span>{e.name}</span>
                </div>
                {e.is_dir && (
                  <button
                    className="directory-picker-select-btn"
                    onClick={() => {
                      let target = e.name;
                      if (isDriveRoot && /^[A-Z]:\\?$/.test(e.name)) { target = e.name; }
                      else {
                        const sep = path.endsWith('\\') || path.endsWith('/') ? '' : '\\';
                        target = path + sep + e.name;
                      }
                      onSelect(target);
                    }}
                  >选择</button>
                )}
              </div>
            ))
          )}
        </div>
      </div>
    </div>,
    document.body
  );
}
