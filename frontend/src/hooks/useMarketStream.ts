import { useEffect, useRef, useState } from 'react';
import { getMarketWebSocketUrl } from '../services/api';
import { IncrementalAnalyticsSnapshot } from '../types';

export interface LiveSymbolUpdate {
  symbol: string;
  live_price?: number;
  live_trade_qty?: number;
  live_trade_time?: string;
  live_trades_count?: number;
  live_vwap?: number | null;
  kline_1m?: {
    open_time: string;
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
    is_closed: boolean;
  };
  analytics?: IncrementalAnalyticsSnapshot;
  latest_forecast?: Record<string, any>;
}

export interface StreamEventFeedItem {
  id: string;
  symbol: string;
  price: number;
  qty?: number;
  vwap?: number | null;
  time: string;
}

const MAX_CLIENT_FEED_ITEMS = 60;

export function useMarketStream(enabled = true) {
  const [wsState, setWsState] = useState<'CONNECTING' | 'CONNECTED' | 'RECONNECTING' | 'DISCONNECTED'>('CONNECTING');
  const [liveSymbols, setLiveSymbols] = useState<Record<string, LiveSymbolUpdate>>({});
  const [streamStatus, setStreamStatus] = useState<Record<string, any>>({});
  const [recentFeed, setRecentFeed] = useState<StreamEventFeedItem[]>([]);
  const [lastMessageAt, setLastMessageAt] = useState<string | null>(null);
  const reconnectTimer = useRef<number | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!enabled) {
      setWsState('DISCONNECTED');
      return;
    }

    let cancelled = false;
    let attempt = 0;

    const connect = () => {
      if (cancelled) return;
      setWsState(attempt === 0 ? 'CONNECTING' : 'RECONNECTING');
      const ws = new WebSocket(getMarketWebSocketUrl());
      wsRef.current = ws;

      ws.onopen = () => {
        if (cancelled) return;
        attempt = 0;
        setWsState('CONNECTED');
      };

      ws.onmessage = (event) => {
        if (cancelled) return;
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === 'heartbeat') return;

          if (msg.symbols && typeof msg.symbols === 'object') {
            setLiveSymbols((prev) => ({ ...prev, ...msg.symbols }));
            setLastMessageAt(new Date().toISOString());

            // Bounded client ring buffer of coalesced tick summaries
            const additions: StreamEventFeedItem[] = [];
            for (const [sym, val] of Object.entries(msg.symbols as Record<string, LiveSymbolUpdate>)) {
              if (val.live_price !== undefined && val.live_price !== null) {
                additions.push({
                  id: `${sym}-${msg.ts_ms || Date.now()}`,
                  symbol: sym,
                  price: val.live_price,
                  qty: val.live_trade_qty,
                  vwap: val.live_vwap,
                  time: val.live_trade_time || new Date().toISOString()
                });
              }
            }
            if (additions.length > 0) {
              setRecentFeed((prev) => [...additions, ...prev].slice(0, MAX_CLIENT_FEED_ITEMS));
            }
          }
          if (msg.stream_status) {
            setStreamStatus(msg.stream_status);
          }
        } catch {
          // ignore malformed ws frame
        }
      };

      ws.onclose = () => {
        if (cancelled) return;
        setWsState('RECONNECTING');
        attempt += 1;
        const delayMs = Math.min(1000 * Math.pow(1.6, attempt), 15000);
        reconnectTimer.current = window.setTimeout(connect, delayMs);
      };

      ws.onerror = () => {
        ws.close();
      };
    };

    connect();
    return () => {
      cancelled = true;
      if (reconnectTimer.current !== null) {
        clearTimeout(reconnectTimer.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [enabled]);

  return { wsState, liveSymbols, streamStatus, recentFeed, lastMessageAt };
}

