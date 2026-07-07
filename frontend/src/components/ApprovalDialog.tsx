/** ApprovalDialog — command approval popup. */

import { createPortal } from 'react-dom';
import { ShieldAlert, Check, X } from 'lucide-react';

interface Props {
  open: boolean;
  command: string;
  onApprove: () => void;
  onDeny: () => void;
}

export function ApprovalDialog({ open, command, onApprove, onDeny }: Props) {
  if (!open) return null;
  return createPortal(
    <div className="confirm-overlay" onClick={onDeny}>
      <div className="confirm-dialog approval-dialog" onClick={e => e.stopPropagation()}>
        <div className="confirm-title" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <ShieldAlert size={18} style={{ color: 'var(--warning)' }} />
          命令执行审批
        </div>
        <div className="confirm-body">
          <pre className="approval-command">{command}</pre>
        </div>
        <div className="confirm-actions">
          <button className="btn-outlined danger" onClick={onDeny}><X size={14} /> 拒绝</button>
          <button className="text-btn primary" onClick={onApprove}><Check size={14} /> 批准</button>
        </div>
      </div>
    </div>,
    document.body
  );
}
