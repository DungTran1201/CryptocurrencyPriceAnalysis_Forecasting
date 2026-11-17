import React, { useState, useEffect, useCallback } from 'react';
import { useMarketStream } from '../context/MarketStreamContext';
import { MarketHeader } from '../components/market/MarketHeader';
import { TradingViewCandleChart } from '../components/market/TradingViewCandleChart';
import { OscillatorPane } from '../components/market/OscillatorPane';
import { ModelIntelligencePanel } from '../components/market/ModelIntelligencePanel';
import { SymbolInfo, KlineCandle, ForecastRecord, ModelCard } from '../types';
import { api } from '../services/api';

export const MarketTerminalView: React.FC = () => {
  const { wsState, liveSymbols } = useMarketStream();

  const [symbols, setSymbols] = useState<SymbolInfo[]>([]);
  const [selectedSymbol, setSelectedSymbol] = useState<string>('BTCUSDT');
  const [timeframe, setTimeframe] = useState<string>('1h');
  const [candles, setCandles] = useState<KlineCandle[]>([]);
  const [indicatorsData, setIndicatorsData] = useState<Record<string, (number | null)[]>>({});
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const [activeModel, setActiveModel] = useState<ModelCard | null>(null);
  const [latestForecast, setLatestForecast] = useState<ForecastRecord | null>(null);

  const [activeOverlays, setActiveOverlays] = useState({
    sma: true,
    ema: true,
    boll: false,
    vwap: false
  });

  const [crosshairBar, setCrosshairBar] = useState<{
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
    time: string;
  } | null>(null);

  const [syncing, setSyncing] = useState<boolean>(false);
  const [generating, setGenerating] = useState<boolean>(false);
  const [reconciling, setReconciling] = useState<boolean>(false);

  // 1. Fetch initial symbols list
  useEffect(() => {
    api.getSymbols()
      .then((res) => {
        if (Array.isArray(res) && res.length > 0) {
          setSymbols(res);
        }
      })
      .catch((err) => console.error('Failed to load symbols:', err));
  }, []);

  // 2. Fetch Historical Candles & Indicators for selected symbol + timeframe
  const loadKlines = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.getKlines(selectedSymbol, timeframe, 200);
      setCandles(res.candles || []);
      setIndicatorsData(res.indicators || {});
    } catch (err: any) {
      console.error('Failed to load klines:', err);
      setError(err.message || 'Failed to load candlestick data.');
    } finally {
      setLoading(false);
    }
  }, [selectedSymbol, timeframe]);

  useEffect(() => {
    loadKlines();
  }, [loadKlines]);

  // 3. Fetch Active Model & Latest Forecast for selected symbol
  const loadModelAndForecast = useCallback(async () => {
    try {
      const models = await api.getModels(selectedSymbol, timeframe, true);
      if (models && models.length > 0) {
        setActiveModel(models[0]);
      } else {
        setActiveModel(null);
      }

      const forecastsRes = await api.getForecasts(selectedSymbol, undefined, 1, 1);
      if (forecastsRes && forecastsRes.records && forecastsRes.records.length > 0) {
        setLatestForecast(forecastsRes.records[0]);
      } else {
        setLatestForecast(null);
      }
    } catch {
      // ignore
    }
  }, [selectedSymbol, timeframe]);

  useEffect(() => {
    loadModelAndForecast();
  }, [loadModelAndForecast]);

  // 4. Extract Real-Time Live Ticks from WebSocket Stream
  const currentSymbolUpdate = liveSymbols[selectedSymbol.toUpperCase()];
  const liveTick = currentSymbolUpdate?.live_price
    ? {
        price: currentSymbolUpdate.live_price,
        volume: currentSymbolUpdate.live_trade_qty,
        time: currentSymbolUpdate.live_trade_time || new Date().toISOString()
      }
    : null;

  const liveKline1m = currentSymbolUpdate?.kline_1m || null;

  // Handlers
  const handleToggleOverlay = (key: 'sma' | 'ema' | 'boll' | 'vwap') => {
    setActiveOverlays((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const handleQuickSync = async () => {
    try {
      setSyncing(true);
      await api.syncMarket(selectedSymbol, timeframe, 30);
      await loadKlines();
    } catch (err: any) {
      console.error('Sync failed:', err);
    } finally {
      setSyncing(false);
    }
  };

  const handleGenerateForecast = async (horizonSteps: number) => {
    try {
      setGenerating(true);
      const res = await api.generateForecast(selectedSymbol, timeframe, horizonSteps);
      setLatestForecast(res);
    } catch (err: any) {
      console.error('Forecast generation failed:', err);
    } finally {
      setGenerating(false);
    }
  };

  const handleReconcile = async () => {
    try {
      setReconciling(true);
      await api.reconcileForecasts();
      await loadModelAndForecast();
    } catch (err: any) {
      console.error('Reconciliation failed:', err);
    } finally {
      setReconciling(false);
    }
  };

  const currentTickerInfo = symbols.find((s) => s.symbol === selectedSymbol) || null;

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        background: '#0B0E11',
        overflow: 'hidden'
      }}
    >
      {/* 1. Market Header with Tickers & Timeframe Selector */}
      <MarketHeader
        symbols={symbols}
        selectedSymbol={selectedSymbol}
        onSelectSymbol={setSelectedSymbol}
        timeframe={timeframe}
        onSelectTimeframe={setTimeframe}
        livePrice={liveTick?.price}
        tickerInfo={currentTickerInfo}
        wsState={wsState}
        crosshairBar={crosshairBar}
        activeOverlays={activeOverlays}
        onToggleOverlay={handleToggleOverlay}
        onQuickSync={handleQuickSync}
        syncing={syncing}
      />

      {/* 2. Main Workspace: Chart + Oscillators (Left/Center) & Model Intelligence (Right) */}
      <div style={{ flex: 1, display: 'flex', minHeight: 0, overflow: 'hidden' }}>
        {/* Left: Financial Chart & Oscillator Workspace */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, overflow: 'hidden' }}>
          {error && (
            <div style={{ padding: '8px 16px', background: 'rgba(246, 70, 93, 0.15)', color: '#F6465D', fontSize: '12px' }}>
              {error}
            </div>
          )}

          {/* Main Candlestick Chart */}
          <div style={{ flex: 1, position: 'relative', minHeight: '340px' }}>
            {loading && candles.length === 0 ? (
              <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#848E9C', fontSize: '13px' }}>
                Loading market candles...
              </div>
            ) : candles.length === 0 ? (
              <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: '#848E9C', gap: '8px' }}>
                <span>No stored candles for {selectedSymbol} ({timeframe}).</span>
                <button
                  onClick={handleQuickSync}
                  style={{
                    padding: '6px 12px',
                    background: '#FCD535',
                    color: '#0B0E11',
                    border: 'none',
                    borderRadius: '4px',
                    fontWeight: 700,
                    fontSize: '11px',
                    cursor: 'pointer'
                  }}
                >
                  Sync Market Candles from Binance
                </button>
              </div>
            ) : (
              <TradingViewCandleChart
                candles={candles}
                indicatorsData={indicatorsData}
                activeOverlays={activeOverlays}
                activeForecast={latestForecast}
                liveTick={liveTick}
                liveKline1m={liveKline1m}
                timeframe={timeframe}
                height={460}
                onCrosshairMove={setCrosshairBar}
              />
            )}
          </div>

          {/* Secondary Oscillator Panel (RSI / MACD / ATR) */}
          <OscillatorPane
            candles={candles}
            indicatorsData={indicatorsData}
            height={130}
          />
        </div>

        {/* Right: AI & Model Intelligence Panel */}
        <ModelIntelligencePanel
          symbol={selectedSymbol}
          timeframe={timeframe}
          activeModel={activeModel}
          latestForecast={latestForecast}
          onGenerateForecast={handleGenerateForecast}
          onReconcile={handleReconcile}
          generating={generating}
          reconciling={reconciling}
        />
      </div>
    </div>
  );
};
