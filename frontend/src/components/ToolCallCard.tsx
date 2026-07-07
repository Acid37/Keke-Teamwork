import { useState } from 'react';
import {
  FileText,
  FilePlus,
  FileEdit,
  Terminal,
  Search,
  FolderSearch,
  FolderOpen,
  Wrench,
  Loader2,
  CheckCircle2,
} from 'lucide-react';
import { ToolCallInfo } from '../types';

interface ToolCallCardProps {
  toolCall: ToolCallInfo;
}

const TOOL_ICONS: Record<string, React.ComponentType<{ size?: number; className?: string }>> = {
  read_file: FileText,
  write_file: FilePlus,
  edit_file: FileEdit,
  run_console: Terminal,
  grep_search: Search,
  find_files: FolderSearch,
  list_directory: FolderOpen,
};

function getToolIcon(name: string) {
  const Icon = TOOL_ICONS[name] || Wrench;
  return Icon;
}

export function ToolCallCard({ toolCall }: ToolCallCardProps) {
  const [expanded, setExpanded] = useState(false);
  const Icon = getToolIcon(toolCall.name);

  const formatArgs = () => {
    try {
      return JSON.stringify(toolCall.args, null, 2);
    } catch {
      return String(toolCall.args);
    }
  };

  return (
    <div className="tool-card">
      <div className="tool-card-header" onClick={() => setExpanded(!expanded)}>
        <Icon size={14} className="tool-card-icon" />
        <span className="tool-card-name">{toolCall.name}</span>
        <span className={`tool-card-status ${toolCall.stage}`}>
          {toolCall.stage === 'running' ? (
            <>
              <Loader2 size={12} className="spinner" />
              <span>执行中</span>
            </>
          ) : (
            <>
              <CheckCircle2 size={12} />
              <span>完成</span>
            </>
          )}
        </span>
      </div>

      {expanded && (
        <div className="tool-card-body">
          <div className="tool-card-args">{formatArgs()}</div>

          {toolCall.result && (
            <div className="tool-card-result">{toolCall.result}</div>
          )}

          {toolCall.console_output && (
            <div className="terminal-output">{toolCall.console_output}</div>
          )}
        </div>
      )}
    </div>
  );
}
