import React, { useEffect, useRef, useState } from 'react';
import {
  createChart,
  IChartApi,
  LineSeries,
  HistogramSeries,
  ColorType,
  LineStyle,
  Time
} from 'lightweight-charts';
import { KlineCandle } from '../../types';

interface OscillatorPaneProps {
  candles: KlineCandle[];
  indicatorsData?: Record<string, (number | null)[]>;
  height?: number;
}

export type OscillatorType = 'rsi' | 'macd' | 'atr';

export const OscillatorPane: React.FC<OscillatorPaneProps> = ({
  candles,
  indicatorsData,
  height = 140
}) => {
  const [activeOscillator, setActiveOscillator] = useState<OscillatorType>('rsi');
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  const toTimestamp = (timeStr: string): Time => {
    const ms = new Date(timeStr).getTime();
    return (Math.floor(ms / 1000) as unknown) as Time;
  };

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const chart = createChart(container, {
      width: container.clientWidth || 800,
      height: height,
      layout: {
        background: { type: ColorType.Solid, color: '#0B0E11' },
        textColor: '#848E9C',
        fontSize: 10,
        fontFamily: 'Inter, monospace'
      },
      grid: {
        vertLines: { color: '#161E27', style: LineStyle.Solid },
        horzLines: { color: '#161E27', style: LineStyle.Solid }
      },
      timeScale: {
        borderColor: '#222B35',
        timeVisible: true,
        secondsVisible: false,
        visible: true
      },
      rightPriceScale: {
        borderColor: '#222B35',
        scaleMargins: {
          top: 0.1,
          bottom: 0.1
        }
      }
    });

    chartRef.current = chart;

    const resizeObserver = new ResizeObserver((entries) => {
      if (!entries || entries.length === 0) return;
      chart.applyOptions({
        width: Math.floor(entries[0].contentRect.width),
        height: height
      });
    });
    resizeObserver.observe(container);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, [height]);

  // Update Series when activeOscillator or data changes
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !indicatorsData || candles.length === 0) return;

    // Clear existing series
    // In lightweight-charts v5, we recreate or update
    const sorted = [...candles].sort((a, b) => new Date(a.open_time).getTime() - new Date(b.open_time).getTime());

    if (activeOscillator === 'rsi') {
      const rsiSeries = chart.addSeries(LineSeries, {
        color: '#FCD535',
        lineWidth: 2,
        priceLineVisible: false
      });

      rsiSeries.createPriceLine({
        price: 70,
        color: 'rgba(246, 70, 93, 0.5)',
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: '70 Overbought'
      });

      rsiSeries.createPriceLine({
        price: 30,
        color: 'rgba(14, 203, 129, 0.5)',
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: '30 Oversold'
      });

      const rawRsi = indicatorsData.rsi_14 || indicatorsData.rsi || [];
      const rsiPoints = sorted
        .map((c, i) => ({ time: toTimestamp(c.open_time), value: rawRsi[i] }))
        .filter((p): p is { time: Time; value: number } => p.value !== null && p.value !== undefined);

      rsiSeries.setData(rsiPoints);

      return () => {
        try {
          chart.removeSeries(rsiSeries);
        } catch {
          // ignore
        }
      };
    } else if (activeOscillator === 'macd') {
      const histSeries = chart.addSeries(HistogramSeries, {
        priceFormat: { type: 'volume' }
      });
      const macdSeries = chart.addSeries(LineSeries, {
        color: '#00D8FF',
        lineWidth: 2
      });
      const signalSeries = chart.addSeries(LineSeries, {
        color: '#FCD535',
        lineWidth: 1,
        lineStyle: LineStyle.Dashed
      });

      const rawMacd = indicatorsData.macd_line || [];
      const rawSignal = indicatorsData.macd_signal || [];
      const rawHist = indicatorsData.macd_hist || [];

      macdSeries.setData(
        sorted
          .map((c, i) => ({ time: toTimestamp(c.open_time), value: rawMacd[i] }))
          .filter((p): p is { time: Time; value: number } => p.value !== null && p.value !== undefined)
      );

      signalSeries.setData(
        sorted
          .map((c, i) => ({ time: toTimestamp(c.open_time), value: rawSignal[i] }))
          .filter((p): p is { time: Time; value: number } => p.value !== null && p.value !== undefined)
      );

      histSeries.setData(
        sorted
          .map((c, i) => {
            const v = rawHist[i];
            return {
              time: toTimestamp(c.open_time),
              value: v !== null && v !== undefined ? v : 0,
              color: (v || 0) >= 0 ? 'rgba(14, 203, 129, 0.6)' : 'rgba(246, 70, 93, 0.6)'
            };
          })
          .filter((p) => p.value !== undefined)
      );

      return () => {
        try {
          chart.removeSeries(histSeries);
          chart.removeSeries(macdSeries);
          chart.removeSeries(signalSeries);
        } catch {
          // ignore
        }
      };
    } else if (activeOscillator === 'atr') {
      const atrSeries = chart.addSeries(LineSeries, {
        color: '#EC4899',
        lineWidth: 2
      });

      const rawAtr = indicatorsData.atr_14 || indicatorsData.atr || [];
      atrSeries.setData(
        sorted
          .map((c, i) => ({ time: toTimestamp(c.open_time), value: rawAtr[i] }))
          .filter((p): p is { time: Time; value: number } => p.value !== null && p.value !== undefined)
      );

      return () => {
        try {
          chart.removeSeries(atrSeries);
        } catch {
          // ignore
        }
      };
    }
  }, [activeOscillator, indicatorsData, candles]);

  return (
    <div style={{ background: '#0B0E11', borderTop: '1px solid #161E27', position: 'relative' }}>
      {/* Mini Oscillator Selector Tabs */}
      <div
        style={{
          position: 'absolute',
          top: '6px',
          left: '12px',
          zIndex: 10,
          display: 'flex',
          gap: '4px',
          background: 'rgba(18, 22, 26, 0.85)',
          padding: '2px',
          borderRadius: '4px',
          border: '1px solid #222B35'
        }}
      >
        <button
          onClick={() => setActiveOscillator('rsi')}
          style={{
            background: activeOscillator === 'rsi' ? '#222B35' : 'none',
            border: 'none',
            borderRadius: '3px',
            color: activeOscillator === 'rsi' ? '#FCD535' : '#848E9C',
            fontSize: '10px',
            fontFamily: 'monospace',
            fontWeight: 700,
            padding: '2px 8px',
            cursor: 'pointer'
          }}
        >
          RSI (14)
        </button>
        <button
          onClick={() => setActiveOscillator('macd')}
          style={{
            background: activeOscillator === 'macd' ? '#222B35' : 'none',
            border: 'none',
            borderRadius: '3px',
            color: activeOscillator === 'macd' ? '#00D8FF' : '#848E9C',
            fontSize: '10px',
            fontFamily: 'monospace',
            fontWeight: 700,
            padding: '2px 8px',
            cursor: 'pointer'
          }}
        >
          MACD
        </button>
        <button
          onClick={() => setActiveOscillator('atr')}
          style={{
            background: activeOscillator === 'atr' ? '#222B35' : 'none',
            border: 'none',
            borderRadius: '3px',
            color: activeOscillator === 'atr' ? '#EC4899' : '#848E9C',
            fontSize: '10px',
            fontFamily: 'monospace',
            fontWeight: 700,
            padding: '2px 8px',
            cursor: 'pointer'
          }}
        >
          ATR (14)
        </button>
      </div>

      <div ref={containerRef} style={{ width: '100%', height: `${height}px` }} />
    </div>
  );
};
