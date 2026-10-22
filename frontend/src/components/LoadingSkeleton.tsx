import React from 'react';

interface LoadingSkeletonProps {
  lines?: number;
  height?: string | number;
  className?: string;
}

export const LoadingSkeleton: React.FC<LoadingSkeletonProps> = ({
  lines = 3,
  height = '18px',
  className = ''
}) => {
  return (
    <div className={`skeleton-container ${className}`}>
      {Array.from({ length: lines }).map((_, idx) => (
        <div
          key={idx}
          className="skeleton-bar"
          style={{
            height,
            width: idx === lines - 1 ? '60%' : '100%'
          }}
        />
      ))}
    </div>
  );
};

export default LoadingSkeleton;
