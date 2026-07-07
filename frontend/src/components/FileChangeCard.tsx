import { useState } from 'react';
import { ChevronDown, ChevronUp, FileDiff } from 'lucide-react';
import type { FilesChangedPayload } from '../types';

interface FileChangeCardProps {
  changes: FilesChangedPayload;
}

export function FileChangeCard({ changes }: FileChangeCardProps) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="file-change-card">
      <button className="file-change-header" onClick={() => setExpanded(!expanded)}>
        {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        <FileDiff size={15} />
        <span>{changes.summary}</span>
      </button>
      <div className="file-change-list">
        {changes.files.map((file) => (
          <span key={`${file.action}:${file.path}`} className={`file-change-pill ${file.action}`}>
            {file.action} {file.path}
          </span>
        ))}
      </div>
      {expanded && <pre className="file-change-diff">{changes.combined_diff}</pre>}
    </div>
  );
}
