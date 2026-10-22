import React from 'react';

export type StatusVariant =
  | 'ONLINE'
  | 'SUCCESS'
  | 'PASS'
  | 'COMPLETED'
  | 'RECONCILED'
  | 'SYNCHRONIZED'
  | 'WARNING'
  | 'AWAITING_DATA'
  | 'PARTIAL'
  | 'STALE'
  | 'OFFLINE'
  | 'FAILED'
  | 'ERROR'
  | 'CRITICAL'
  | 'RUNNING'
  | 'PENDING'
  | 'INFO'
  | 'UNAVAILABLE';

interface StatusBadgeProps {
  status: StatusVariant | string;
  label?: string;
  pulse?: boolean;
  title?: string;
  className?: string;
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({
  status,
  label,
  pulse = false,
  title,
  className = ''
}) => {
  const normStatus = (status || '').toUpperCase();

  let variantClass = 'badge-neutral';
  if (['ONLINE', 'SUCCESS', 'PASS', 'COMPLETED', 'RECONCILED', 'SYNCHRONIZED'].includes(normStatus)) {
    variantClass = 'badge-success';
  } else if (['WARNING', 'AWAITING_DATA', 'PARTIAL', 'STALE'].includes(normStatus)) {
    variantClass = 'badge-warning';
  } else if (['OFFLINE', 'FAILED', 'ERROR', 'CRITICAL'].includes(normStatus)) {
    variantClass = 'badge-danger';
  } else if (['RUNNING', 'PENDING', 'INFO'].includes(normStatus)) {
    variantClass = 'badge-info';
  }

  const displayLabel = label || normStatus;

  return (
    <div className={`status-badge ${variantClass} ${className}`} title={title || displayLabel}>
      {pulse && <div className="pulse-dot" />}
      <span>{displayLabel}</span>
    </div>
  );
};

export default StatusBadge;
