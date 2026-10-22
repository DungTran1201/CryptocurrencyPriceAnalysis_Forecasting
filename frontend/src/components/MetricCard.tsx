import React from 'react';

interface MetricCardProps {
  label: string;
  value: string | number;
  subtext?: string | React.ReactNode;
  icon?: React.ReactNode;
  badge?: React.ReactNode;
  highlight?: boolean;
  onClick?: () => void;
  className?: string;
}

export const MetricCard: React.FC<MetricCardProps> = ({
  label,
  value,
  subtext,
  icon,
  badge,
  highlight = false,
  onClick,
  className = ''
}) => {
  return (
    <div
      className={`kpi-card ${highlight ? 'highlight' : ''} ${onClick ? 'clickable' : ''} ${className}`}
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
    >
      <div className="kpi-header">
        <span className="kpi-label">{label}</span>
        {icon && <span className="kpi-icon">{icon}</span>}
      </div>
      <div className="kpi-value">{value}</div>
      {(subtext || badge) && (
        <div className="kpi-footer">
          {badge && <div className="kpi-badge">{badge}</div>}
          {subtext && <div className="kpi-subtext">{subtext}</div>}
        </div>
      )}
    </div>
  );
};

export default MetricCard;
