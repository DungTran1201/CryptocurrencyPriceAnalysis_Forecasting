import {
  SymbolInfo,
  MarketDataResponse,
  ForecastRecord,
  ForecastHistoryResponse,
  ModelCard,
  SystemStatus
} from '../types';

const API_BASE = '/api/v1';

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers
    },
    ...options
  });
  if (!res.ok) {
    let errorDetail = `Request failed (${res.status})`;
    try {
      const err = await res.json();
      errorDetail = err.detail || errorDetail;
    } catch {
      // ignore
    }
    throw new Error(errorDetail);
  }
  return res.json();
}

export const api = {
  // Market
  getSymbols: (): Promise<SymbolInfo[]> =>
    fetchJson<SymbolInfo[]>(`${API_BASE}/market/symbols`),

  getKlines: (symbol: string, timeframe: string, limit = 200): Promise<MarketDataResponse> =>
    fetchJson<MarketDataResponse>(`${API_BASE}/market/klines?symbol=${symbol}&timeframe=${timeframe}&limit=${limit}`),

  syncMarket: (symbol: string, timeframe: string, lookbackDays = 30) =>
    fetchJson<{ symbol: string; added_candles: number; status: string; message: string }>(
      `${API_BASE}/market/sync`,
      {
        method: 'POST',
        body: JSON.stringify({ symbol, timeframe, lookback_days: lookbackDays })
      }
    ),

  // Forecasts
  generateForecast: (symbol: string, timeframe: string, horizonSteps = 6): Promise<ForecastRecord> =>
    fetchJson<ForecastRecord>(`${API_BASE}/forecasts/generate`, {
      method: 'POST',
      body: JSON.stringify({ symbol, timeframe, horizon_steps: horizonSteps })
    }),

  getForecasts: (symbol?: string, status?: string, page = 1, pageSize = 50): Promise<ForecastHistoryResponse> => {
    const params = new URLSearchParams({ page: page.toString(), page_size: pageSize.toString() });
    if (symbol) params.append('symbol', symbol);
    if (status) params.append('status', status);
    return fetchJson<ForecastHistoryResponse>(`${API_BASE}/forecasts?${params.toString()}`);
  },

  reconcileForecasts: () =>
    fetchJson<{ status: string; reconciled_count: number }>(`${API_BASE}/forecasts/reconcile`, {
      method: 'POST'
    }),

  // Model Lab
  getModels: (symbol?: string, timeframe?: string, isActive?: boolean): Promise<ModelCard[]> => {
    const params = new URLSearchParams();
    if (symbol) params.append('symbol', symbol);
    if (timeframe) params.append('timeframe', timeframe);
    if (isActive !== undefined) params.append('is_active', isActive.toString());
    return fetchJson<ModelCard[]>(`${API_BASE}/models?${params.toString()}`);
  },

  trainModel: (symbol: string, timeframe: string, horizonSteps = 6, modelType = 'gradient_boosting', nSplits = 4) =>
    fetchJson<{ model_id: string; is_active: boolean; evaluation: any; feature_importances: Record<string, number> }>(
      `${API_BASE}/models/train`,
      {
        method: 'POST',
        body: JSON.stringify({
          symbol,
          timeframe,
          horizon_steps: horizonSteps,
          model_type: modelType,
          n_splits: nSplits
        })
      }
    ),

  // System
  getSystemStatus: (): Promise<SystemStatus> =>
    fetchJson<SystemStatus>(`${API_BASE}/system/status`)
};
