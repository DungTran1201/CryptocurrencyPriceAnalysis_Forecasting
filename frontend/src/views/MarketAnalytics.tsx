import React, { useState, useEffect } from 'react';
import {
  LineChart,
  BarChart2,
  TrendingUp,
  Activity,
  RefreshCw,
  AlertTriangle,
  Info,
  Grid
} from 'lucide-react';
import { api } from '../services/api';
import {
  SymbolInfo,
  MarketDataResponse,
  ReturnsDistributionResponse,
  RollingVolatilityResponse,
  DrawdownsResponse,
  CorrelationMatrixResponse
} from '../types';
import { formatCurrency } from '../utils/formatters';
import { CandlestickChart } from '../components/CandlestickChart';

export const MarketAnalytics: React.FC = () => {
  const [symbols, setSymbols] = useState<SymbolInfo[]>([]);
  const [selectedSymbol, setSelectedSymbol] = useState<string>('BTCUSDT');
  const [timeframe, setTimeframe] = useState<string>('1h');

  // Sub-tab view: 'chart' | 'returns' | 'volatility' | 'drawdowns' | 'correlations'
  const [activeAnalyticsTab, setActiveAnalyticsTab] = useState<'chart' | 'returns' | 'volatility' | 'drawdowns' | 'correlations'>('chart');

  // Datasets
  const [marketData, setMarketData] = useState<MarketDataResponse | null>(null);
  const [returnsData, setReturnsData] = useState<ReturnsDistributionResponse | null>(null);
  const [volatilityData, setVolatilityData] = useState<RollingVolatilityResponse | null>(null);
  const [drawdownsData, setDrawdownsData] = useState<DrawdownsResponse | null>(null);
  const [correlationData, setCorrelationData] = useState<CorrelationMatrixResponse | null>(null);

  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const loadInitial = async () => {
    try {
      const symList = await api.getSymbols();
      setSymbols(symList);
    } catch (err: any) {
      setError(err?.message || 'Failed to load symbols.');
    }
  };

  const loadTabData = async () => {
    try {
      setLoading(true);
      setError(null);

      if (activeAnalyticsTab === 'chart') {
        const klines = await api.getKlines(selectedSymbol, timeframe, 150);
        setMarketData(klines);
      } else if (activeAnalyticsTab === 'returns') {
        const ret = await api.getReturnsDistribution(selectedSymbol, timeframe, 500);
        setReturnsData(ret);
      } else if (activeAnalyticsTab === 'volatility') {
        const vol = await api.getRollingVolatility(selectedSymbol, timeframe, 500);
        setVolatilityData(vol);
      } else if (activeAnalyticsTab === 'drawdowns') {
        const dd = await api.getDrawdowns(selectedSymbol, timeframe, 500);
        setDrawdownsData(dd);
      } else if (activeAnalyticsTab === 'correlations') {
        const corr = await api.getCorrelationMatrix('BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT', timeframe, 300);
        setCorrelationData(corr);
      }
    } catch (err: any) {
      setError(err?.message || 'Failed to load analytics data.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadInitial();
  }, []);

  useEffect(() => {
    loadTabData();
  }, [selectedSymbol, timeframe, activeAnalyticsTab]);

  return (
    <div className="view-container">
      {/* Header */}
      <div className="view-header">
        <div>
          <div className="view-tag">QUANTITATIVE RESEARCH & MARKET METRICS</div>
          <h1 className="view-title">Market & Exploratory Analytics</h1>
          <p className="view-subtitle">
            Institutional crypto analytics: return distributions, rolling realized volatility, drawdowns, and cross-asset correlations.
          </p>
        </div>
        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
          <select
            className="filter-select"
            value={selectedSymbol}
            onChange={(e) => setSelectedSymbol(e.target.value)}
          >
            {symbols.map((s) => (
              <option key={s.symbol} value={s.symbol}>
                {s.symbol}
              </option>
            ))}
          </select>
          <select
            className="filter-select"
            value={timeframe}
            onChange={(e) => setTimeframe(e.target.value)}
          >
            <option value="15m">15m</option>
            <option value="1h">1h</option>
            <option value="4h">4h</option>
            <option value="1d">1d</option>
          </select>
          <button className="btn btn-secondary" onClick={loadTabData} title="Refresh">
            <RefreshCw size={14} />
          </button>
        </div>
      </div>

      {error && (
        <div className="alert-banner error" style={{ marginBottom: '1.25rem' }}>
          <AlertTriangle size={16} />
          <span>{error}</span>
        </div>
      )}

      {/* Analytics Sub-Tabs */}
      <div className="filter-toolbar">
        <div className="tab-pill-group">
          <button
            className={`tab-pill ${activeAnalyticsTab === 'chart' ? 'active' : ''}`}
            onClick={() => setActiveAnalyticsTab('chart')}
          >
            <LineChart size={14} />
            <span>OHLCV & Indicators</span>
          </button>
          <button
            className={`tab-pill ${activeAnalyticsTab === 'returns' ? 'active' : ''}`}
            onClick={() => setActiveAnalyticsTab('returns')}
          >
            <BarChart2 size={14} />
            <span>Return Distribution & Moments</span>
          </button>
          <button
            className={`tab-pill ${activeAnalyticsTab === 'volatility' ? 'active' : ''}`}
            onClick={() => setActiveAnalyticsTab('volatility')}
          >
            <Activity size={14} />
            <span>Rolling Realized Volatility</span>
          </button>
          <button
            className={`tab-pill ${activeAnalyticsTab === 'drawdowns' ? 'active' : ''}`}
            onClick={() => setActiveAnalyticsTab('drawdowns')}
          >
            <TrendingUp size={14} />
            <span>Drawdowns & Maximum DD</span>
          </button>
          <button
            className={`tab-pill ${activeAnalyticsTab === 'correlations' ? 'active' : ''}`}
            onClick={() => setActiveAnalyticsTab('correlations')}
          >
            <Grid size={14} />
            <span>Asset Return Correlations</span>
          </button>
        </div>
      </div>

      {/* Sub-tab 1: Candlestick & Indicators */}
      {activeAnalyticsTab === 'chart' && (
        <div className="panel" style={{ marginTop: '1.25rem' }}>
          <div className="panel-header">
            <div className="panel-title">
              <LineChart size={18} color="var(--accent-cyan)" />
              <span>
                {selectedSymbol} • {timeframe} Historical Candles & Indicators
              </span>
            </div>
            <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
              {marketData ? `${marketData.count} candles loaded` : '—'}
            </span>
          </div>

          {loading ? (
            <div className="loading-state">
              <RefreshCw size={24} className="spin" />
              <span>Rendering chart...</span>
            </div>
          ) : !marketData || marketData.candles.length === 0 ? (
            <div className="empty-state">
              <p>No stored candles available for {selectedSymbol} ({timeframe}).</p>
            </div>
          ) : (
            <div style={{ height: '440px', width: '100%' }}>
              <CandlestickChart
                candles={marketData.candles}
                indicators={marketData.indicators}
              />
            </div>
          )}
        </div>
      )}

      {/* Sub-tab 2: Return Distribution & Moments */}
      {activeAnalyticsTab === 'returns' && (
        <div style={{ marginTop: '1.25rem' }}>
          {loading ? (
            <div className="loading-state">
              <RefreshCw size={24} className="spin" />
              <span>Calculating statistical moments...</span>
            </div>
          ) : !returnsData || !returnsData.has_sufficient_data ? (
            <div className="panel">
              <div className="empty-state">
                <Info size={32} color="var(--accent-cyan)" />
                <p>{returnsData?.message || 'Insufficient data to compute return distribution.'}</p>
              </div>
            </div>
          ) : (
            <>
              {/* Statistical Moments Cards */}
              <div className="grid-4-cols">
                <div className="kpi-card">
                  <div className="kpi-label">Mean Return (μ)</div>
                  <div className="kpi-value">{returnsData.metrics?.mean_pct.toFixed(3)}%</div>
                  <div className="kpi-subtext">Median: {returnsData.metrics?.median_pct.toFixed(3)}%</div>
                </div>
                <div className="kpi-card">
                  <div className="kpi-label">Standard Deviation (σ)</div>
                  <div className="kpi-value">{returnsData.metrics?.std_pct.toFixed(3)}%</div>
                  <div className="kpi-subtext">Variance: {returnsData.metrics?.variance_pct}</div>
                </div>
                <div className="kpi-card">
                  <div className="kpi-label">Skewness</div>
                  <div className="kpi-value" style={{ color: (returnsData.metrics?.skewness || 0) < 0 ? 'var(--semantic-amber)' : 'inherit' }}>
                    {returnsData.metrics?.skewness}
                  </div>
                  <div className="kpi-subtext">
                    {(returnsData.metrics?.skewness || 0) < 0 ? 'Negative asymmetry (fat left tail)' : 'Positive asymmetry'}
                  </div>
                </div>
                <div className="kpi-card">
                  <div className="kpi-label">Excess Kurtosis</div>
                  <div className="kpi-value" style={{ color: (returnsData.metrics?.kurtosis || 0) > 3 ? 'var(--semantic-amber)' : 'inherit' }}>
                    {returnsData.metrics?.kurtosis}
                  </div>
                  <div className="kpi-subtext">Leptokurtic fat-tailed distribution</div>
                </div>
              </div>

              {/* Value at Risk (VaR), CVaR, ATR, VWAP Cards */}
              <div className="grid-4-cols" style={{ marginTop: '1rem' }}>
                <div className="kpi-card">
                  <div className="kpi-label">VaR 95% / CVaR 95%</div>
                  <div className="kpi-value" style={{ color: 'var(--semantic-red)', fontSize: '1.2rem' }}>
                    {returnsData.metrics?.var_95_pct}% / {returnsData.metrics?.cvar_95_pct ?? '—'}%
                  </div>
                  <div className="kpi-subtext">5% tail & Expected Shortfall (ES)</div>
                </div>
                <div className="kpi-card">
                  <div className="kpi-label">VaR 99% / CVaR 99%</div>
                  <div className="kpi-value" style={{ color: 'var(--semantic-red)', fontSize: '1.2rem' }}>
                    {returnsData.metrics?.var_99_pct}% / {returnsData.metrics?.cvar_99_pct ?? '—'}%
                  </div>
                  <div className="kpi-subtext">1% extreme tail & CVaR</div>
                </div>
                <div className="kpi-card">
                  <div className="kpi-label">ATR (14) & Log Mean</div>
                  <div className="kpi-value" style={{ fontSize: '1.2rem' }}>
                    {returnsData.metrics?.atr_14 != null ? formatCurrency(returnsData.metrics.atr_14) : '—'}
                  </div>
                  <div className="kpi-subtext">
                    Log Mean: {returnsData.metrics?.log_mean_pct != null ? `${returnsData.metrics.log_mean_pct.toFixed(4)}%` : '—'}
                  </div>
                </div>
                <div className="kpi-card">
                  <div className="kpi-label">Session VWAP</div>
                  <div className="kpi-value" style={{ fontSize: '1.2rem', color: 'var(--accent-cyan)' }}>
                    {returnsData.metrics?.vwap != null ? formatCurrency(returnsData.metrics.vwap) : '—'}
                  </div>
                  <div className="kpi-subtext">Volume-Weighted Average Price</div>
                </div>
              </div>

              {/* Binned Histogram Table */}
              <div className="panel" style={{ marginTop: '1rem' }}>
                <div className="panel-header">
                  <div className="panel-title">
                    <BarChart2 size={18} color="var(--accent-cyan)" />
                    <span>Return Frequency Histogram ({returnsData.count} bars evaluated)</span>
                  </div>
                </div>

                <div className="histogram-bars-container">
                  {returnsData.histogram?.map((bin, i) => {
                    const maxCount = Math.max(...(returnsData.histogram?.map((b) => b.count) || [1]));
                    const heightPct = Math.round((bin.count / maxCount) * 100);
                    return (
                      <div key={i} className="hist-col" title={`[${bin.bin_start}% to ${bin.bin_end}%]: ${bin.count} bars`}>
                        <div className="hist-bar-track">
                          <div className="hist-bar-fill" style={{ height: `${heightPct}%` }}></div>
                        </div>
                        <div className="hist-label">{bin.bin_center.toFixed(1)}%</div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </>
          )}
        </div>
      )}

      {/* Sub-tab 3: Rolling Realized Volatility */}
      {activeAnalyticsTab === 'volatility' && (
        <div style={{ marginTop: '1.25rem' }}>
          {loading ? (
            <div className="loading-state">
              <RefreshCw size={24} className="spin" />
              <span>Computing rolling volatility windows...</span>
            </div>
          ) : !volatilityData || !volatilityData.has_sufficient_data ? (
            <div className="panel">
              <div className="empty-state">
                <p>Insufficient historical data to compute rolling realized volatility.</p>
              </div>
            </div>
          ) : (
            <>
              <div className="grid-3-cols">
                <div className="kpi-card">
                  <div className="kpi-label">7-Period Annualized Volatility</div>
                  <div className="kpi-value">{volatilityData.current_annualized_vol?.vol_7}%</div>
                  <div className="kpi-subtext">Short-term market regime</div>
                </div>
                <div className="kpi-card">
                  <div className="kpi-label">14-Period Annualized Volatility</div>
                  <div className="kpi-value">{volatilityData.current_annualized_vol?.vol_14}%</div>
                  <div className="kpi-subtext">Medium lookback horizon</div>
                </div>
                <div className="kpi-card">
                  <div className="kpi-label">30-Period Annualized Volatility</div>
                  <div className="kpi-value">{volatilityData.current_annualized_vol?.vol_30}%</div>
                  <div className="kpi-subtext">Longer trend baseline</div>
                </div>
              </div>

              <div className="panel" style={{ marginTop: '1rem' }}>
                <div className="panel-header">
                  <div className="panel-title">
                    <Activity size={18} color="var(--accent-cyan)" />
                    <span>Recent Rolling Volatility Series</span>
                  </div>
                </div>
                <div className="table-responsive">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Timestamp (UTC)</th>
                        <th>7-Period Vol (Ann.)</th>
                        <th>14-Period Vol (Ann.)</th>
                        <th>30-Period Vol (Ann.)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {volatilityData.series.slice(-15).reverse().map((pt, i) => (
                        <tr key={i}>
                          <td style={{ fontFamily: 'var(--font-mono)' }}>{pt.timestamp.replace('T', ' ')}</td>
                          <td style={{ fontFamily: 'var(--font-mono)', color: 'var(--accent-cyan)' }}>{pt.vol_7}%</td>
                          <td style={{ fontFamily: 'var(--font-mono)' }}>{pt.vol_14}%</td>
                          <td style={{ fontFamily: 'var(--font-mono)' }}>{pt.vol_30}%</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          )}
        </div>
      )}

      {/* Sub-tab 4: Drawdowns */}
      {activeAnalyticsTab === 'drawdowns' && (
        <div style={{ marginTop: '1.25rem' }}>
          {loading ? (
            <div className="loading-state">
              <RefreshCw size={24} className="spin" />
              <span>Calculating drawdown trajectory...</span>
            </div>
          ) : !drawdownsData || !drawdownsData.has_sufficient_data ? (
            <div className="panel">
              <div className="empty-state">
                <p>Insufficient historical data to compute drawdowns.</p>
              </div>
            </div>
          ) : (
            <>
              <div className="grid-3-cols">
                <div className="kpi-card">
                  <div className="kpi-label">Maximum Drawdown (MDD)</div>
                  <div className="kpi-value" style={{ color: 'var(--semantic-red)' }}>
                    {drawdownsData.max_drawdown_pct}%
                  </div>
                  <div className="kpi-subtext">Peak-to-trough worst-case loss</div>
                </div>
                <div className="kpi-card">
                  <div className="kpi-label">Current Drawdown from Peak</div>
                  <div className="kpi-value" style={{ color: 'var(--semantic-amber)' }}>
                    {drawdownsData.current_drawdown_pct}%
                  </div>
                  <div className="kpi-subtext">Relative to historical running peak</div>
                </div>
                <div className="kpi-card">
                  <div className="kpi-label">MDD Trough Timestamp</div>
                  <div className="kpi-value" style={{ fontSize: '1rem' }}>
                    {drawdownsData.max_drawdown_trough_date ? drawdownsData.max_drawdown_trough_date.slice(0, 16).replace('T', ' ') : '—'}
                  </div>
                  <div className="kpi-subtext">
                    Peak on: {drawdownsData.max_drawdown_peak_date ? drawdownsData.max_drawdown_peak_date.slice(0, 10) : '—'}
                  </div>
                </div>
              </div>

              <div className="panel" style={{ marginTop: '1rem' }}>
                <div className="panel-header">
                  <div className="panel-title">
                    <TrendingUp size={18} color="var(--accent-cyan)" />
                    <span>Historical Drawdown Observations</span>
                  </div>
                </div>
                <div className="table-responsive">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Timestamp (UTC)</th>
                        <th>Price</th>
                        <th>Running Peak</th>
                        <th>Drawdown %</th>
                      </tr>
                    </thead>
                    <tbody>
                      {drawdownsData.series.slice(-15).reverse().map((pt, i) => (
                        <tr key={i}>
                          <td style={{ fontFamily: 'var(--font-mono)' }}>{pt.timestamp.replace('T', ' ')}</td>
                          <td style={{ fontFamily: 'var(--font-mono)' }}>{formatCurrency(pt.price)}</td>
                          <td style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>
                            {formatCurrency(pt.peak)}
                          </td>
                          <td
                            style={{
                              fontFamily: 'var(--font-mono)',
                              color: pt.drawdown_pct < -5 ? 'var(--semantic-red)' : 'var(--text-muted)'
                            }}
                          >
                            {pt.drawdown_pct}%
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          )}
        </div>
      )}

      {/* Sub-tab 5: Cross-Asset Correlation Matrix */}
      {activeAnalyticsTab === 'correlations' && (
        <div className="panel" style={{ marginTop: '1.25rem' }}>
          <div className="panel-header">
            <div className="panel-title">
              <Grid size={18} color="var(--accent-cyan)" />
              <span>Pairwise Pearson Correlation Matrix</span>
            </div>
            <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
              Aligned Hourly Returns ({correlationData?.observations_count || 0} observations)
            </span>
          </div>

          {loading ? (
            <div className="loading-state">
              <RefreshCw size={24} className="spin" />
              <span>Aligning return vectors and computing Pearson correlations...</span>
            </div>
          ) : !correlationData || !correlationData.has_sufficient_data ? (
            <div className="empty-state">
              <Info size={32} color="var(--accent-cyan)" />
              <p>{correlationData?.message || 'Need more historical observations to compute asset correlations.'}</p>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem', marginTop: '0.5rem' }}>
              <div className="table-responsive">
                <table className="data-table correlation-matrix-table">
                  <thead>
                    <tr>
                      <th>Pearson Correlation (ρ)</th>
                      {correlationData.symbols.map((sym) => (
                        <th key={sym} style={{ textAlign: 'center' }}>
                          {sym}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {correlationData.matrix.map((row) => (
                      <tr key={row.symbol}>
                        <td style={{ fontWeight: 600, color: '#fff' }}>{row.symbol}</td>
                        {correlationData.symbols.map((colSym) => {
                          const val = row[colSym];
                          let bgColor = 'transparent';
                          if (val != null) {
                            if (val > 0.7) bgColor = 'rgba(0, 230, 204, 0.25)';
                            else if (val > 0.4) bgColor = 'rgba(0, 230, 204, 0.12)';
                            else if (val < 0) bgColor = 'rgba(255, 77, 77, 0.2)';
                          }
                          return (
                            <td
                              key={colSym}
                              style={{
                                textAlign: 'center',
                                fontFamily: 'var(--font-mono)',
                                backgroundColor: bgColor,
                                fontWeight: row.symbol === colSym ? 700 : 400
                              }}
                            >
                              {val != null ? val.toFixed(3) : '—'}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {correlationData.covariance_matrix && correlationData.covariance_matrix.length > 0 && (
                <div className="table-responsive">
                  <table className="data-table correlation-matrix-table">
                    <thead>
                      <tr>
                        <th>Return Covariance (pct²)</th>
                        {correlationData.symbols.map((sym) => (
                          <th key={sym} style={{ textAlign: 'center' }}>
                            {sym}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {correlationData.covariance_matrix.map((row) => (
                        <tr key={row.symbol}>
                          <td style={{ fontWeight: 600, color: '#fff' }}>{row.symbol}</td>
                          {correlationData.symbols.map((colSym) => {
                            const val = row[colSym];
                            return (
                              <td key={colSym} style={{ textAlign: 'center', fontFamily: 'var(--font-mono)' }}>
                                {val != null ? Number(val).toFixed(4) : '—'}
                              </td>
                            );
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
