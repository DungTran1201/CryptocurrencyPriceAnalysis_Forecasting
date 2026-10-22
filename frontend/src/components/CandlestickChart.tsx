import React, { useRef, useEffect, useState } from 'react';
import { KlineCandle } from '../types';

interface ChartProps {
  candles: KlineCandle[];
  indicators: Record<string, (number | null)[]>;
  visibleIndicators?: {
    sma?: boolean;
    ema?: boolean;
    boll?: boolean;
    rsi?: boolean;
  };
}

export const CandlestickChart: React.FC<ChartProps> = ({
  candles,
  indicators,
  visibleIndicators = { sma: true, ema: false, boll: true, rsi: true }
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);
  const [mousePos, setMousePos] = useState<{ x: number; y: number } | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container || candles.length === 0) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Handle high DPI
    const dpr = window.devicePixelRatio || 1;
    const rect = container.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);

    const width = rect.width;
    const height = rect.height;

    // Layout division:
    // Main price chart: 65% of height
    // Volume: 15% of height
    // RSI: 20% of height
    const priceH = height * 0.65;
    const volH = height * 0.15;

    const priceTop = 10;
    const priceBottom = priceH - 10;
    const volTop = priceH + 10;
    const volBottom = priceH + volH - 5;
    const rsiTop = priceH + volH + 10;
    const rsiBottom = height - 15;

    ctx.clearRect(0, 0, width, height);

    // Compute Price min and max
    let minPrice = Infinity;
    let maxPrice = -Infinity;
    let maxVol = 0;

    candles.forEach((c) => {
      if (c.low < minPrice) minPrice = c.low;
      if (c.high > maxPrice) maxPrice = c.high;
      if (c.volume > maxVol) maxVol = c.volume;
    });

    // Expand slightly for padding
    const pPadding = (maxPrice - minPrice) * 0.05 || 10;
    minPrice -= pPadding;
    maxPrice += pPadding;

    const n = candles.length;
    const candleW = Math.max(2, (width - 60) / n);
    const gap = candleW * 0.25;
    const barW = candleW - gap;

    const priceToY = (p: number) => {
      return priceBottom - ((p - minPrice) / (maxPrice - minPrice)) * (priceBottom - priceTop);
    };

    const volToY = (v: number) => {
      if (maxVol === 0) return volBottom;
      return volBottom - (v / maxVol) * (volBottom - volTop);
    };

    const rsiToY = (r: number) => {
      return rsiBottom - (r / 100) * (rsiBottom - rsiTop);
    };

    // 1. Draw Grid Lines
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.04)';
    ctx.lineWidth = 1;
    for (let i = 1; i <= 4; i++) {
      const y = priceTop + (priceBottom - priceTop) * (i / 5);
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(width - 50, y);
      ctx.stroke();

      // Price labels
      const pVal = maxPrice - (maxPrice - minPrice) * (i / 5);
      ctx.fillStyle = '#64748b';
      ctx.font = '10px "JetBrains Mono", monospace';
      ctx.fillText(pVal.toFixed(1), width - 45, y + 3);
    }

    // Dividers
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.08)';
    ctx.beginPath();
    ctx.moveTo(0, priceH);
    ctx.lineTo(width, priceH);
    ctx.moveTo(0, priceH + volH);
    ctx.lineTo(width, priceH + volH);
    ctx.stroke();

    // 2. Bollinger Bands Cloud
    if (visibleIndicators.boll && indicators['BOLL_UPPER'] && indicators['BOLL_LOWER']) {
      const upper = indicators['BOLL_UPPER'];
      const lower = indicators['BOLL_LOWER'];
      ctx.fillStyle = 'rgba(0, 242, 254, 0.04)';
      ctx.beginPath();
      let started = false;
      for (let i = 0; i < n; i++) {
        if (upper[i] != null) {
          const x = i * candleW + barW / 2;
          const y = priceToY(upper[i]!);
          if (!started) {
            ctx.moveTo(x, y);
            started = true;
          } else {
            ctx.lineTo(x, y);
          }
        }
      }
      for (let i = n - 1; i >= 0; i--) {
        if (lower[i] != null) {
          const x = i * candleW + barW / 2;
          const y = priceToY(lower[i]!);
          ctx.lineTo(x, y);
        }
      }
      ctx.closePath();
      ctx.fill();

      // Band border lines
      ctx.strokeStyle = 'rgba(0, 242, 254, 0.25)';
      ctx.lineWidth = 1;
      ['BOLL_UPPER', 'BOLL_LOWER', 'BOLL_MID'].forEach((bKey) => {
        const line = indicators[bKey];
        if (!line) return;
        ctx.beginPath();
        let s = false;
        for (let i = 0; i < n; i++) {
          if (line[i] != null) {
            const x = i * candleW + barW / 2;
            const y = priceToY(line[i]!);
            if (!s) { ctx.moveTo(x, y); s = true; } else { ctx.lineTo(x, y); }
          }
        }
        ctx.stroke();
      });
    }

    // 3. Draw Candlesticks & Volume
    candles.forEach((c, i) => {
      const x = i * candleW;
      const isUp = c.close >= c.open;
      const color = isUp ? '#10b981' : '#f43f5e';

      const yOpen = priceToY(c.open);
      const yClose = priceToY(c.close);
      const yHigh = priceToY(c.high);
      const yLow = priceToY(c.low);

      // Wick
      ctx.strokeStyle = color;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x + barW / 2, yHigh);
      ctx.lineTo(x + barW / 2, yLow);
      ctx.stroke();

      // Body
      const bodyTop = Math.min(yOpen, yClose);
      const bodyHeight = Math.max(1, Math.abs(yClose - yOpen));
      ctx.fillStyle = color;
      ctx.fillRect(x, bodyTop, barW, bodyHeight);

      // Volume bar
      const vY = volToY(c.volume);
      ctx.fillStyle = isUp ? 'rgba(16, 185, 129, 0.4)' : 'rgba(244, 63, 94, 0.4)';
      ctx.fillRect(x, vY, barW, volBottom - vY);
    });

    // 4. Overlaid Moving Averages
    const drawLine = (vals: (number | null)[], strokeColor: string, lineW = 1.5) => {
      ctx.strokeStyle = strokeColor;
      ctx.lineWidth = lineW;
      ctx.beginPath();
      let started = false;
      for (let i = 0; i < n; i++) {
        if (vals[i] != null) {
          const x = i * candleW + barW / 2;
          const y = priceToY(vals[i]!);
          if (!started) { ctx.moveTo(x, y); started = true; } else { ctx.lineTo(x, y); }
        }
      }
      ctx.stroke();
    };

    if (visibleIndicators.sma) {
      if (indicators['SMA_7']) drawLine(indicators['SMA_7'], '#f59e0b', 1.5);
      if (indicators['SMA_25']) drawLine(indicators['SMA_25'], '#00f2fe', 1.5);
      if (indicators['SMA_99']) drawLine(indicators['SMA_99'], '#8b5cf6', 1.5);
    }
    if (visibleIndicators.ema) {
      if (indicators['EMA_12']) drawLine(indicators['EMA_12'], '#ec4899', 1.5);
      if (indicators['EMA_26']) drawLine(indicators['EMA_26'], '#3b82f6', 1.5);
    }

    // 5. RSI Subplot
    if (visibleIndicators.rsi && indicators['RSI_14']) {
      // 70 and 30 dashed reference lines
      ctx.setLineDash([4, 4]);
      ctx.strokeStyle = 'rgba(244, 63, 94, 0.3)';
      ctx.beginPath();
      ctx.moveTo(0, rsiToY(70));
      ctx.lineTo(width - 50, rsiToY(70));
      ctx.stroke();

      ctx.strokeStyle = 'rgba(16, 185, 129, 0.3)';
      ctx.beginPath();
      ctx.moveTo(0, rsiToY(30));
      ctx.lineTo(width - 50, rsiToY(30));
      ctx.stroke();
      ctx.setLineDash([]);

      ctx.fillStyle = '#64748b';
      ctx.font = '9px "JetBrains Mono", monospace';
      ctx.fillText('70', width - 45, rsiToY(70) + 3);
      ctx.fillText('30', width - 45, rsiToY(30) + 3);

      // RSI Curve
      const rsiVals = indicators['RSI_14'];
      ctx.strokeStyle = '#f59e0b';
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      let s = false;
      for (let i = 0; i < n; i++) {
        if (rsiVals[i] != null) {
          const x = i * candleW + barW / 2;
          const y = rsiToY(rsiVals[i]!);
          if (!s) { ctx.moveTo(x, y); s = true; } else { ctx.lineTo(x, y); }
        }
      }
      ctx.stroke();
    }

    // 6. Crosshairs on Hover
    if (hoverIdx !== null && hoverIdx >= 0 && hoverIdx < n && mousePos) {
      const x = hoverIdx * candleW + barW / 2;

      ctx.setLineDash([3, 3]);
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.4)';
      ctx.lineWidth = 1;

      // Vertical line
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, height);
      ctx.stroke();

      // Horizontal price line
      if (mousePos.y <= priceH) {
        ctx.beginPath();
        ctx.moveTo(0, mousePos.y);
        ctx.lineTo(width - 50, mousePos.y);
        ctx.stroke();

        // Price tag on axis
        const hoverPrice = maxPrice - (mousePos.y / priceH) * (maxPrice - minPrice);
        ctx.fillStyle = '#00f2fe';
        ctx.fillRect(width - 50, mousePos.y - 9, 50, 18);
        ctx.fillStyle = '#07090e';
        ctx.font = 'bold 10px "JetBrains Mono", monospace';
        ctx.fillText(hoverPrice.toFixed(1), width - 48, mousePos.y + 3);
      }
      ctx.setLineDash([]);
    }
  }, [candles, indicators, visibleIndicators, hoverIdx, mousePos]);

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    const container = containerRef.current;
    if (!container || candles.length === 0) return;
    const rect = container.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;

    const candleW = Math.max(2, (rect.width - 60) / candles.length);
    const idx = Math.min(candles.length - 1, Math.max(0, Math.floor(x / candleW)));
    setHoverIdx(idx);
    setMousePos({ x, y });
  };

  const handleMouseLeave = () => {
    setHoverIdx(null);
    setMousePos(null);
  };

  const activeCandle = hoverIdx !== null && candles[hoverIdx] ? candles[hoverIdx] : candles[candles.length - 1];

  return (
    <div style={{ position: 'relative', width: '100%' }}>
      {/* HUD Info Header */}
      {activeCandle && (
        <div style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: '1rem',
          padding: '0.4rem 0.75rem',
          fontSize: '0.8rem',
          fontFamily: 'var(--font-mono)',
          background: 'rgba(255, 255, 255, 0.02)',
          borderBottom: '1px solid var(--border-color)',
          color: 'var(--text-secondary)'
        }}>
          <span>Time: <strong style={{ color: '#fff' }}>{activeCandle.open_time.replace('T', ' ').slice(0, 19)}</strong></span>
          <span>O: <strong style={{ color: '#fff' }}>{activeCandle.open.toFixed(2)}</strong></span>
          <span>H: <strong style={{ color: '#10b981' }}>{activeCandle.high.toFixed(2)}</strong></span>
          <span>L: <strong style={{ color: '#f43f5e' }}>{activeCandle.low.toFixed(2)}</strong></span>
          <span>C: <strong style={{ color: activeCandle.close >= activeCandle.open ? '#10b981' : '#f43f5e' }}>
            {activeCandle.close.toFixed(2)}
          </strong></span>
          <span>Vol: <strong style={{ color: '#00f2fe' }}>{activeCandle.volume.toFixed(2)}</strong></span>
          {hoverIdx !== null && indicators['RSI_14'] && indicators['RSI_14'][hoverIdx] != null && (
            <span>RSI: <strong style={{ color: '#f59e0b' }}>{indicators['RSI_14'][hoverIdx]?.toFixed(1)}</strong></span>
          )}
        </div>
      )}

      {/* Canvas */}
      <div
        ref={containerRef}
        className="chart-container"
        onMouseMove={handleMouseMove}
        onMouseLeave={handleMouseLeave}
      >
        <canvas ref={canvasRef} style={{ width: '100%', height: '100%' }} />
      </div>
    </div>
  );
};
