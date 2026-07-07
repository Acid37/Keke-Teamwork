import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';
import { Message } from '../types';
import { ToolCallCard } from './ToolCallCard';
import { FileChangeCard } from './FileChangeCard';
import { ChevronDown, ChevronUp } from 'lucide-react';

interface MessageBubbleProps {
  message: Message;
  foldTools?: boolean;
}

export function MessageBubble({ message, foldTools }: MessageBubbleProps) {
  const [thinkingExpanded, setThinkingExpanded] = useState(false);
  const [toolsExpanded, setToolsExpanded] = useState(false);

  const formatTime = (ts: number) => new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  if (message.role === 'system') {
    return (
      <div className="message message-system">
        <div className="message-content">{message.content}</div>
      </div>
    );
  }

  if (message.role === 'user') {
    return (
      <div className="message message-user">
        <div className="message-content">{message.content}</div>
        <div className="message-time">{formatTime(message.timestamp)}</div>
      </div>
    );
  }

  // Assistant message
  const agentColor = message.agent_color || 'var(--accent)';
  const agentName = message.agent_name || '助手';
  const agentInitial = agentName.charAt(0);
  const toolCalls = message.tool_calls || [];
  const fileChanges = message.file_changes || [];
  const shouldFold = foldTools && toolCalls.length > 0;

  return (
    <div className="message message-assistant">
      {/* Avatar + name */}
      <div className="assistant-bubble-shell">
        {agentName && (
          <div className="message-avatar" style={{ background: agentColor }}>{agentInitial}</div>
        )}
        <div className="assistant-bubble-main">
          {agentName && (
            <div className="message-avatar-row">
              <span className="message-name" style={{ color: agentColor }}>{agentName}</span>
              <span className="message-time">{formatTime(message.timestamp)}</span>
            </div>
          )}

          {/* Thinking */}
          {message.thinking && (
            <div className="thinking-block">
              <button className="thinking-toggle" onClick={() => setThinkingExpanded(!thinkingExpanded)}>
                {thinkingExpanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                思考过程
              </button>
              {thinkingExpanded && <pre className="thinking-body">{message.thinking}</pre>}
            </div>
          )}

          {/* Tool calls — foldable when >4 */}
          {toolCalls.length > 0 && (
            <div className="tool-calls-block">
              {shouldFold ? (
                <>
                  <button className="tool-fold-toggle" onClick={() => setToolsExpanded(!toolsExpanded)}>
                    {toolsExpanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                    工具调用（{toolCalls.length} 次）{!toolsExpanded && `— ${toolCalls.map(t => t.name).join(', ')}`}
                  </button>
                  {toolsExpanded && toolCalls.map(tc => <ToolCallCard key={tc.call_id} toolCall={tc} />)}
                </>
              ) : (
                toolCalls.map(tc => <ToolCallCard key={tc.call_id} toolCall={tc} />)
              )}
            </div>
          )}

          {fileChanges.length > 0 && (
            <div className="file-changes-block">
              {fileChanges.map((changes, index) => (
                <FileChangeCard key={index} changes={changes} />
              ))}
            </div>
          )}

          {/* Content */}
          {message.content && (
            <div className="message-body">
              <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
                {message.content}
              </ReactMarkdown>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
