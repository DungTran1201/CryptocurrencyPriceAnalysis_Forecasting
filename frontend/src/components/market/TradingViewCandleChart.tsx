import React, { useEffect, useRef } from 'react';
import {
  createChart,
  IChartApi,
  ISeriesApi,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  ColorType,
  CrosshairMode,
  LineStyle,
  Time,
  createSeriesMarkers
} from 'lightweight-charts';
import { KlineCandle, ForecastRecord } from '../../types';

interface TradingViewCandleChartProps {
  candles: KlineCandle[];
  indicatorsData?: Record<string, (number | null)[]>;
  activeOverlays: {
    sma: boolean;
    ema: boolean;
    boll: boolean;
    vwap: boolean;
  };
  activeForecast?: ForecastRecord | null;
  liveTick?: {
    price: number;
    volume?: number;
    time: string;
  } | null;
  liveKline1m?: {
    open_time: string;
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
    is_closed: boolean;
  } | null;
  timeframe: string;
  height?: number;
  onCrosshairMove?: (bar: { open: number; high: number; low: number; close: number; volume: number; time: string } | null) => void;
}

export const TradingViewCandleChart: React.FC<TradingViewCandleChartProps> = ({
  candles,
  indicatorsData,
  activeOverlays,
  activeForecast,
  liveTick,
  liveKline1m,
  timeframe,
  height = 480,
  onCrosshairMove
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);

  // Overlay series refs
  const smaSeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const emaSeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const bollUpperSeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const bollMidSeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const bollLowerSeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const vwapSeriesRef = useRef<ISeriesApi<'Line'> | null>(null);

  // Price lines refs for cleanup
  const forecastPriceLinesRef = useRef<any[]>([]);

  // Parse ISO string to lightweight-charts unix timestamp (seconds)
  const toTimestamp = (timeStr: string): Time => {
    const ms = new Date(timeStr).getTime();
    return (Math.floor(ms / 1000) as unknown) as Time;
  };

  // 1. Initialize Chart
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const chart = createChart(container, {
      width: container.clientWidth || 800,
      height: height,
      layout: {
        background: { type: ColorType.Solid, color: '#0B0E11' },
        textColor: '#848E9C',
        fontSize: 11,
        fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace'
      },
      grid: {
        vertLines: { color: '#161E27', style: LineStyle.Solid },
        horzLines: { color: '#161E27', style: LineStyle.Solid }
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: {
          color: '#3B4856',
          width: 1,
          style: LineStyle.Dashed,
          labelBackgroundColor: '#1E293B'
        },
        horzLine: {
          color: '#3B4856',
          width: 1,
          style: LineStyle.Dashed,
          labelBackgroundColor: '#1E293B'
        }
      },
      timeScale: {
        borderColor: '#222B35',
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 12,
        barSpacing: 9,
        minBarSpacing: 3
      },
      rightPriceScale: {
        borderColor: '#222B35',
        scaleMargins: {
          top: 0.1,
          bottom: 0.22
        }
      }
    });

    // Candlestick Series
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#0ECB81',
      downColor: '#F6465D',
      borderVisible: false,
      wickUpColor: '#0ECB81',
      wickDownColor: '#F6465D'
    });

    // Volume Histogram Series on separate price scale overlay
    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume_scale'
    });

    chart.priceScale('volume_scale').applyOptions({
      scaleMargins: {
        top: 0.8,
        bottom: 0
      }
    });

    // Overlay Series
    const smaSeries = chart.addSeries(LineSeries, {
      color: '#FCD535',
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false
    });

    const emaSeries = chart.addSeries(LineSeries, {
      color: '#00D8FF',
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false
    });

    const bollUpperSeries = chart.addSeries(LineSeries, {
      color: '#848E9C',
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      priceLineVisible: false,
      lastValueVisible: false
    });

    const bollMidSeries = chart.addSeries(LineSeries, {
      color: 'rgba(252, 213, 53, 0.6)',
      lineWidth: 1,
      lineStyle: LineStyle.Dotted,
      priceLineVisible: false,
      lastValueVisible: false
    });

    const bollLowerSeries = chart.addSeries(LineSeries, {
      color: '#848E9C',
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      priceLineVisible: false,
      lastValueVisible: false
    });

    const vwapSeries = chart.addSeries(LineSeries, {
      color: '#A855F7',
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;
    smaSeriesRef.current = smaSeries;
    emaSeriesRef.current = emaSeries;
    bollUpperSeriesRef.current = bollUpperSeries;
    bollMidSeriesRef.current = bollMidSeries;
    bollLowerSeriesRef.current = bollLowerSeries;
    vwapSeriesRef.current = vwapSeries;

    // Crosshair listener for header OHLCV
    if (onCrosshairMove) {
      chart.subscribeCrosshairMove((param) => {
        if (!param || !param.time || !param.seriesData) {
          onCrosshairMove(null);
          return;
        }
        const candleData = param.seriesData.get(candleSeries) as any;
        const volData = param.seriesData.get(volumeSeries) as any;
        if (candleData) {
          onCrosshairMove({
            open: candleData.open,
            high: candleData.high,
            low: candleData.low,
            close: candleData.close,
            volume: volData ? volData.value : 0,
            time: new Date((param.time as number) * 1000).toISOString()
          });
        } else {
          onCrosshairMove(null);
        }
      });
    }

    // Resize Observer
    const resizeObserver = new ResizeObserver((entries) => {
      if (!entries || entries.length === 0) return;
      const { width: newWidth, height: newHeight } = entries[0].contentRect;
      chart.applyOptions({
        width: Math.floor(newWidth),
        height: Math.floor(newHeight || height)
      });
    });
    resizeObserver.observe(container);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, [height]);

  // 2. Load Historical Candles & Indicators
  useEffect(() => {
    if (!candleSeriesRef.current || !volumeSeriesRef.current || candles.length === 0) return;

    // Deduplicate and sort candles by timestamp
    const sorted = [...candles].sort((a, b) => new Date(a.open_time).getTime() - new Date(b.open_time).getTime());

    const formattedCandles = sorted.map((c) => ({
      time: toTimestamp(c.open_time),
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close
    }));

    const formattedVolume = sorted.map((c) => ({
      time: toTimestamp(c.open_time),
      value: c.volume,
      color: c.close >= c.open ? 'rgba(14, 203, 129, 0.45)' : 'rgba(246, 70, 93, 0.45)'
    }));

    candleSeriesRef.current.setData(formattedCandles);
    volumeSeriesRef.current.setData(formattedVolume);

    // Apply Overlays
    if (indicatorsData) {
      // SMA
      if (smaSeriesRef.current) {
        if (activeOverlays.sma && indicatorsData.sma_20) {
          const smaPoints = sorted
            .map((c, i) => ({
              time: toTimestamp(c.open_time),
              value: indicatorsData.sma_20[i]
            }))
            .filter((p): p is { time: Time; value: number } => p.value !== null && p.value !== undefined);
          smaSeriesRef.current.setData(smaPoints);
        } else {
          smaSeriesRef.current.setData([]);
        }
      }

      // EMA
      if (emaSeriesRef.current) {
        if (activeOverlays.ema && indicatorsData.ema_20) {
          const emaPoints = sorted
            .map((c, i) => ({
              time: toTimestamp(c.open_time),
              value: indicatorsData.ema_20[i]
            }))
            .filter((p): p is { time: Time; value: number } => p.value !== null && p.value !== undefined);
          emaSeriesRef.current.setData(emaPoints);
        } else {
          emaSeriesRef.current.setData([]);
        }
      }

      // Bollinger Bands
      if (bollUpperSeriesRef.current && bollMidSeriesRef.current && bollLowerSeriesRef.current) {
        if (activeOverlays.boll && indicatorsData.bollinger_upper) {
          const upper = sorted
            .map((c, i) => ({ time: toTimestamp(c.open_time), value: indicatorsData.bollinger_upper[i] }))
            .filter((p): p is { time: Time; value: number } => p.value !== null && p.value !== undefined);
          const mid = sorted
            .map((c, i) => ({ time: toTimestamp(c.open_time), value: indicatorsData.bollinger_middle?.[i] }))
            .filter((p): p is { time: Time; value: number } => p.value !== null && p.value !== undefined);
          const lower = sorted
            .map((c, i) => ({ time: toTimestamp(c.open_time), value: indicatorsData.bollinger_lower?.[i] }))
            .filter((p): p is { time: Time; value: number } => p.value !== null && p.value !== undefined);

          bollUpperSeriesRef.current.setData(upper);
          bollMidSeriesRef.current.setData(mid);
          bollLowerSeriesRef.current.setData(lower);
        } else {
          bollUpperSeriesRef.current.setData([]);
          bollMidSeriesRef.current.setData([]);
          bollLowerSeriesRef.current.setData([]);
        }
      }

      // VWAP
      if (vwapSeriesRef.current) {
        if (activeOverlays.vwap && indicatorsData.vwap) {
          const vwapPoints = sorted
            .map((c, i) => ({
              time: toTimestamp(c.open_time),
              value: indicatorsData.vwap[i]
            }))
            .filter((p): p is { time: Time; value: number } => p.value !== null && p.value !== undefined);
          vwapSeriesRef.current.setData(vwapPoints);
        } else {
          vwapSeriesRef.current.setData([]);
        }
      }
    }
  }, [candles, indicatorsData, activeOverlays]);

  // 3. Real-Time Incremental Candle Updates
  useEffect(() => {
    if (!candleSeriesRef.current || !volumeSeriesRef.current) return;

    if (timeframe === '1m' && liveKline1m) {
      const barTime = toTimestamp(liveKline1m.open_time);
      candleSeriesRef.current.update({
        time: barTime,
        open: liveKline1m.open,
        high: liveKline1m.high,
        low: liveKline1m.low,
        close: liveKline1m.close
      });
      volumeSeriesRef.current.update({
        time: barTime,
        value: liveKline1m.volume,
        color: liveKline1m.close >= liveKline1m.open ? 'rgba(14, 203, 129, 0.45)' : 'rgba(246, 70, 93, 0.45)'
      });
    } else if (liveTick && candles.length > 0) {
      // For higher timeframes, update latest candle's close/high/low without full redraw
      const lastCandle = candles[candles.length - 1];
      const barTime = toTimestamp(lastCandle.open_time);
      candleSeriesRef.current.update({
        time: barTime,
        open: lastCandle.open,
        high: Math.max(lastCandle.high, liveTick.price),
        low: Math.min(lastCandle.low, liveTick.price),
        close: liveTick.price
      });
    }
  }, [liveKline1m, liveTick, timeframe, candles]);

  // 4. ML Model Forecast Overlay Price Lines & Markers
  useEffect(() => {
    const candleSeries = candleSeriesRef.current;
    if (!candleSeries) return;

    // Clear previous forecast price lines
    forecastPriceLinesRef.current.forEach((pl) => {
      try {
        candleSeries.removePriceLine(pl);
      } catch {
        // ignore
      }
    });
    forecastPriceLinesRef.current = [];

    if (!activeForecast) {
      createSeriesMarkers(candleSeries, []);
      return;
    }

    const isUp = activeForecast.predicted_direction === 'UP';
    const predColor = isUp ? '#0ECB81' : '#F6465D';

    // 1. Forecast Target Price Line
    const targetLine = candleSeries.createPriceLine({
      price: activeForecast.predicted_price,
      color: predColor,
      lineWidth: 2,
      lineStyle: LineStyle.Dashed,
      axisLabelVisible: true,
      title: `${activeForecast.model_id} Target: $${activeForecast.predicted_price.toFixed(2)} (${activeForecast.predicted_direction})`
    });
    forecastPriceLinesRef.current.push(targetLine);

    // 2. Confidence Interval Bounds (if provided)
    if (activeForecast.upper_bound_price) {
      const upperLine = candleSeries.createPriceLine({
        price: activeForecast.upper_bound_price,
        color: 'rgba(0, 216, 255, 0.75)',
        lineWidth: 1,
        lineStyle: LineStyle.Dotted,
        axisLabelVisible: true,
        title: `95% Upper ($${activeForecast.upper_bound_price.toFixed(2)})`
      });
      forecastPriceLinesRef.current.push(upperLine);
    }

    if (activeForecast.lower_bound_price) {
      const lowerLine = candleSeries.createPriceLine({
        price: activeForecast.lower_bound_price,
        color: 'rgba(0, 216, 255, 0.75)',
        lineWidth: 1,
        lineStyle: LineStyle.Dotted,
        axisLabelVisible: true,
        title: `95% Lower ($${activeForecast.lower_bound_price.toFixed(2)})`
      });
      forecastPriceLinesRef.current.push(lowerLine);
    }

    // 3. Target Time Marker
    const targetTime = toTimestamp(activeForecast.target_time.toString());
    createSeriesMarkers(candleSeries, [
      {
        time: targetTime,
        position: isUp ? 'aboveBar' : 'belowBar',
        color: predColor,
        shape: isUp ? 'arrowUp' : 'arrowDown',
        text: `ML Horizon: ${activeForecast.predicted_return_pct > 0 ? '+' : ''}${activeForecast.predicted_return_pct.toFixed(2)}%`
      }
    ]);
  }, [activeForecast]);

  return (
    <div
      ref={containerRef}
      style={{
        width: '100%',
        height: `${height}px`,
        position: 'relative',
        background: '#0B0E11',
        overflow: 'hidden'
      }}
    />
  );
};
