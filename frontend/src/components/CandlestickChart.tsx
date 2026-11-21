import React, { useRef, useEffect, useState } from 'react';
import { KlineCandle } from '../types';
import { formatNumber, formatVolume } from '../utils/formatters';

interface ChartProps {
  candles: KlineCandle[];
  indicators: Record<string, (number | null)[]>;
  height?: number;
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
  height = 420,
  visibleIndicators = { sma: true, ema: false, boll: true, rsi: true }
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [dimensions, setDimensions] = useState<{ width: number; height: number }>({ width: 800, height });
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);
  const [mousePos, setMousePos] = useState<{ x: number; y: number } | null>(null);

  // ResizeObserver for dynamic responsiveness (guards integer bounds to prevent DPI resize feedback loop)
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const w = Math.round(entry.contentRect.width);
        const h = Math.round(entry.contentRect.height);
        if (w > 0 && h > 0) {
          setDimensions((prev) => (prev.width === w && prev.height === h ? prev : { width: w, height: h }));
        }
      }
    });

    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container || candles.length === 0) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // High DPI scaling decoupled from DOM layout size
    const dpr = window.devicePixelRatio || 1;
    const rect = container.getBoundingClientRect();
    const width = Math.max(10, Math.round(rect.width));
    const chartHeight = Math.max(240, Math.round(rect.height || height));

    canvas.width = Math.max(1, Math.round(width * dpr));
    canvas.height = Math.max(1, Math.round(chartHeight * dpr));
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    // Layout division:
    // Main price chart: 62% of height
    // Volume: 16% of height
    // RSI: 22% of height
    const priceH = chartHeight * 0.62;
    const volH = chartHeight * 0.16;

    const priceTop = 15;
    const priceBottom = priceH - 10;
    const volTop = priceH + 12;
    const volBottom = priceH + volH - 6;
    const rsiTop = priceH + volH + 12;
    const rsiBottom = chartHeight - 20;

    ctx.clearRect(0, 0, width, chartHeight);

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
    const yAxisWidth = 70;
    const chartWidth = Math.max(10, width - yAxisWidth);
    const candleW = Math.max(2, chartWidth / n);
    const gap = Math.max(1, candleW * 0.25);
    const barW = Math.max(1, candleW - gap);

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

    // 1. Draw Background Grid Lines & Price Labels
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.05)';
    ctx.lineWidth = 1;
    for (let i = 1; i <= 5; i++) {
      const y = priceTop + (priceBottom - priceTop) * (i / 6);
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(chartWidth, y);
      ctx.stroke();

      // Price labels
      const pVal = maxPrice - (maxPrice - minPrice) * (i / 6);
      ctx.fillStyle = '#707A8A';
      ctx.font = '10px "JetBrains Mono", monospace';
      ctx.textAlign = 'left';
      ctx.fillText(formatNumber(pVal, 2), chartWidth + 6, y + 3);
    }

    // Dividers between panels
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.08)';
    ctx.beginPath();
    ctx.moveTo(0, priceH);
    ctx.lineTo(width, priceH);
    ctx.moveTo(0, priceH + volH);
    ctx.lineTo(width, priceH + volH);
    ctx.stroke();

    // Volume label
    ctx.fillStyle = '#707A8A';
    ctx.font = '9px "JetBrains Mono", monospace';
    ctx.fillText('VOL', 8, volTop + 10);
    ctx.fillText(formatVolume(maxVol), chartWidth + 6, volTop + 10);

    // 2. Bollinger Bands Cloud
    if (visibleIndicators.boll && indicators['BOLL_UPPER'] && indicators['BOLL_LOWER']) {
      const upper = indicators['BOLL_UPPER'];
      const lower = indicators['BOLL_LOWER'];
      ctx.fillStyle = 'rgba(252, 213, 53, 0.03)';
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
      ctx.strokeStyle = 'rgba(252, 213, 53, 0.25)';
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

    // 3. Draw Candlesticks & Volume (Binance #2EBD85 buy green, #F6465D sell red)
    candles.forEach((c, i) => {
      const x = i * candleW;
      const isUp = c.close >= c.open;
      const color = isUp ? '#2EBD85' : '#F6465D';

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
      ctx.fillStyle = isUp ? 'rgba(46, 189, 133, 0.45)' : 'rgba(246, 70, 93, 0.45)';
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
      if (indicators['SMA_7']) drawLine(indicators['SMA_7'], '#FCD535', 1.5); // Binance yellow
      if (indicators['SMA_25']) drawLine(indicators['SMA_25'], '#3B82F6', 1.5); // Institutional blue
      if (indicators['SMA_99']) drawLine(indicators['SMA_99'], '#A855F7', 1.5); // Violet
    }
    if (visibleIndicators.ema) {
      if (indicators['EMA_12']) drawLine(indicators['EMA_12'], '#F59E0B', 1.5); // Amber
      if (indicators['EMA_26']) drawLine(indicators['EMA_26'], '#06B6D4', 1.5); // Cyan
    }

    // 5. RSI Subplot
    if (visibleIndicators.rsi && indicators['RSI_14']) {
      // 70 and 30 dashed reference lines
      ctx.setLineDash([4, 4]);
      ctx.strokeStyle = 'rgba(246, 70, 93, 0.3)';
      ctx.beginPath();
      ctx.moveTo(0, rsiToY(70));
      ctx.lineTo(chartWidth, rsiToY(70));
      ctx.stroke();

      ctx.strokeStyle = 'rgba(46, 189, 133, 0.3)';
      ctx.beginPath();
      ctx.moveTo(0, rsiToY(30));
      ctx.lineTo(chartWidth, rsiToY(30));
      ctx.stroke();
      ctx.setLineDash([]);

      // RSI Label
      ctx.fillStyle = '#707A8A';
      ctx.font = '9px "JetBrains Mono", monospace';
      ctx.fillText('RSI (14)', 8, rsiTop + 10);
      ctx.fillText('70', chartWidth + 6, rsiToY(70) + 3);
      ctx.fillText('30', chartWidth + 6, rsiToY(30) + 3);

      // RSI Curve
      const rsiLine = indicators['RSI_14'];
      ctx.strokeStyle = '#FCD535';
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      let started = false;
      for (let i = 0; i < n; i++) {
        if (rsiLine[i] != null) {
          const x = i * candleW + barW / 2;
          const y = rsiToY(rsiLine[i]!);
          if (!started) { ctx.moveTo(x, y); started = true; } else { ctx.lineTo(x, y); }
        }
      }
      ctx.stroke();
    }

    // 6. X-Axis Time Labels
    ctx.fillStyle = '#707A8A';
    ctx.font = '9px "JetBrains Mono", monospace';
    ctx.textAlign = 'center';
    const step = Math.max(1, Math.floor(n / 6));
    for (let i = 0; i < n; i += step) {
      const c = candles[i];
      const x = i * candleW + barW / 2;
      const timeLabel = c.open_time.slice(11, 16) || c.open_time.slice(5, 10);
      ctx.fillText(timeLabel, x, chartHeight - 4);
    }

    // 7. Crosshairs on Hover
    if (hoverIdx !== null && hoverIdx >= 0 && hoverIdx < n && mousePos) {
      const x = hoverIdx * candleW + barW / 2;

      ctx.setLineDash([3, 3]);
      ctx.strokeStyle = 'rgba(252, 213, 53, 0.5)';
      ctx.lineWidth = 1;

      // Vertical line across chart
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, chartHeight);
      ctx.stroke();

      // Horizontal price line
      if (mousePos.y <= priceH) {
        ctx.beginPath();
        ctx.moveTo(0, mousePos.y);
        ctx.lineTo(chartWidth, mousePos.y);
        ctx.stroke();

        // Price tag on axis (Binance yellow pill with dark text)
        const hoverPrice = maxPrice - (mousePos.y / priceH) * (maxPrice - minPrice);
        ctx.fillStyle = '#FCD535';
        ctx.fillRect(chartWidth, mousePos.y - 9, yAxisWidth, 18);
        ctx.fillStyle = '#12161C';
        ctx.font = 'bold 10px "JetBrains Mono", monospace';
        ctx.textAlign = 'left';
        ctx.fillText(formatNumber(hoverPrice, 2), chartWidth + 5, mousePos.y + 4);
      }
      ctx.setLineDash([]);
    }
  }, [candles, indicators, visibleIndicators, hoverIdx, mousePos, dimensions, height]);

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    const container = containerRef.current;
    if (!container || candles.length === 0) return;
    const rect = container.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;

    const yAxisWidth = 70;
    const chartWidth = Math.max(10, rect.width - yAxisWidth);
    const candleW = Math.max(2, chartWidth / candles.length);
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
    <div style={{ position: 'relative', width: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* HUD Info Header */}
      {activeCandle && (
        <div style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: '1.25rem',
          padding: '0.5rem 0.85rem',
          fontSize: '0.82rem',
          fontFamily: 'var(--font-mono)',
          background: 'rgba(255, 255, 255, 0.02)',
          borderBottom: '1px solid var(--border-color)',
          color: 'var(--text-secondary)'
        }}>
          <span>Time: <strong style={{ color: 'var(--text-primary)' }}>{activeCandle.open_time.replace('T', ' ').slice(0, 19)}</strong></span>
          <span>O: <strong style={{ color: 'var(--text-primary)' }}>{formatNumber(activeCandle.open, 2)}</strong></span>
          <span>H: <strong style={{ color: 'var(--color-success)' }}>{formatNumber(activeCandle.high, 2)}</strong></span>
          <span>L: <strong style={{ color: 'var(--color-danger)' }}>{formatNumber(activeCandle.low, 2)}</strong></span>
          <span>C: <strong style={{ color: activeCandle.close >= activeCandle.open ? 'var(--color-success)' : 'var(--color-danger)' }}>
            {formatNumber(activeCandle.close, 2)}
          </strong></span>
          <span>Vol: <strong style={{ color: 'var(--accent-yellow)' }}>{formatVolume(activeCandle.volume)}</strong></span>
          {hoverIdx !== null && indicators['RSI_14'] && indicators['RSI_14'][hoverIdx] != null && (
            <span>RSI: <strong style={{ color: 'var(--color-warning)' }}>{formatNumber(indicators['RSI_14'][hoverIdx], 1)}</strong></span>
          )}
          {hoverIdx !== null && indicators['SMA_25'] && indicators['SMA_25'][hoverIdx] != null && (
            <span>SMA(25): <strong style={{ color: '#3B82F6' }}>{formatNumber(indicators['SMA_25'][hoverIdx], 2)}</strong></span>
          )}
        </div>
      )}

      {/* Canvas Container (locked pixel height + absolute canvas eliminates HiDPI ResizeObserver stretch loops) */}
      <div
        ref={containerRef}
        className="chart-container"
        style={{ height: `${height}px`, minHeight: `${height}px`, maxHeight: `${height}px`, position: 'relative', width: '100%', overflow: 'hidden' }}
        onMouseMove={handleMouseMove}
        onMouseLeave={handleMouseLeave}
      >
        <canvas
          ref={canvasRef}
          style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', display: 'block' }}
        />
      </div>
    </div>
  );
};

export default CandlestickChart;
