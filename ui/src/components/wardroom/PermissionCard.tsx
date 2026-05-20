import type { CSSProperties } from 'react';

export type WardRoomPermissionCard = {
  id: string;
  intent: string;
  scope: string;
  reason: string;
  expiresAt: string;
};

type PermissionCardProps = {
  card: WardRoomPermissionCard;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  onReviewMore: (id: string) => void;
};

const shellStyle: CSSProperties = {
  border: '1px solid rgba(240, 176, 96, 0.35)',
  borderRadius: 10,
  padding: 12,
  background: 'rgba(23, 22, 30, 0.82)',
  color: '#ded8cf',
};

const labelStyle: CSSProperties = {
  color: '#8e8aa3',
  fontSize: 12,
  textTransform: 'uppercase',
  letterSpacing: '0.06em',
};

const valueStyle: CSSProperties = {
  fontSize: 13,
  marginTop: 2,
  marginBottom: 8,
};

export function PermissionCard({ card, onApprove, onReject, onReviewMore }: PermissionCardProps) {
  const expiresMs = new Date(card.expiresAt).getTime() - Date.now();
  const expiresSec = Math.max(0, Math.floor(expiresMs / 1000));

  return (
    <div style={shellStyle} data-testid="wardroom-permission-card">
      <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 10 }}>File Write Permission Request</div>

      <div style={labelStyle}>Scope</div>
      <div style={valueStyle}>{card.scope}</div>

      <div style={labelStyle}>Reason</div>
      <div style={valueStyle}>{card.reason}</div>

      <div style={labelStyle}>Expiry</div>
      <div style={valueStyle}>{expiresSec}s remaining</div>

      <div style={{ display: 'flex', gap: 8 }}>
        <button onClick={() => onApprove(card.id)}>Approve</button>
        <button onClick={() => onReject(card.id)}>Reject</button>
        <button onClick={() => onReviewMore(card.id)}>Review More</button>
      </div>
    </div>
  );
}
