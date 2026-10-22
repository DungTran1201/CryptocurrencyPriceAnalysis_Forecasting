import React, { useState, useEffect } from 'react';
import {
  Database,
  Download,
  RefreshCw,
  Table,
  BookOpen,
  ChevronLeft,
  ChevronRight,
  AlertTriangle
} from 'lucide-react';
import { api } from '../services/api';
import { DatasetMetadata, DatasetPreviewResponse, SymbolInfo } from '../types';
import { formatNumber, formatCurrency } from '../utils/formatters';

export const DataExplorer: React.FC = () => {
  const [datasets, setDatasets] = useState<DatasetMetadata[]>([]);
  const [selectedDataset, setSelectedDataset] = useState<string>('silver_klines');
  const [symbols, setSymbols] = useState<SymbolInfo[]>([]);

  // Filters
  const [filterSymbol, setFilterSymbol] = useState<string>('BTCUSDT');
  const [filterTimeframe, setFilterTimeframe] = useState<string>('1h');
  const [page, setPage] = useState<number>(1);
  const [pageSize, setPageSize] = useState<number>(25);

  // Data Preview
  const [previewData, setPreviewData] = useState<DatasetPreviewResponse | null>(null);
  const [activeTab, setActiveTab] = useState<'table' | 'schema'>('table');
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const loadDatasets = async () => {
    try {
      const [dsList, syms] = await Promise.all([
        api.getDatasets(),
        api.getSymbols()
      ]);
      setDatasets(dsList);
      setSymbols(syms);
    } catch (err: any) {
      setError(err?.message || 'Failed to load dataset catalog.');
    }
  };

  const loadPreview = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await api.previewDataset(
        selectedDataset,
        page,
        pageSize,
        selectedDataset === 'silver_klines' ? filterSymbol : undefined,
        selectedDataset === 'silver_klines' ? filterTimeframe : undefined
      );
      setPreviewData(res);
    } catch (err: any) {
      setError(err?.message || 'Failed to load dataset records.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadDatasets();
  }, []);

  useEffect(() => {
    loadPreview();
  }, [selectedDataset, page, pageSize, filterSymbol, filterTimeframe]);

  const currentDatasetMeta = datasets.find((d) => d.id === selectedDataset);

  const handleExportCsv = () => {
    const url = api.getExportCsvUrl(
      selectedDataset,
      selectedDataset === 'silver_klines' ? filterSymbol : undefined,
      selectedDataset === 'silver_klines' ? filterTimeframe : undefined,
      2000
    );
    window.open(url, '_blank');
  };

  return (
    <div className="view-container">
      {/* Header */}
      <div className="view-header">
        <div>
          <div className="view-tag">DATA DISCOVERY & SCHEMA CATALOG</div>
          <h1 className="view-title">Data Explorer</h1>
          <p className="view-subtitle">
            Inspect Medallion datasets, view schema contracts, analyze column profiles, and export CSV snapshots.
          </p>
        </div>
        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
          <button className="btn btn-secondary" onClick={handleExportCsv} id="btn-export-csv">
            <Download size={14} />
            <span>Export Bounded CSV</span>
          </button>
          <button className="btn btn-secondary" onClick={loadPreview} title="Refresh records">
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

      {/* Dataset & Filter Bar */}
      <div className="filter-toolbar">
        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', flexWrap: 'wrap' }}>
          <Database size={16} color="var(--accent-cyan)" />
          <select
            className="filter-select"
            value={selectedDataset}
            onChange={(e) => {
              setSelectedDataset(e.target.value);
              setPage(1);
            }}
            aria-label="Select Medallion Dataset"
          >
            {datasets.map((d) => (
              <option key={d.id} value={d.id}>
                [{d.layer}] {d.name}
              </option>
            ))}
          </select>

          {selectedDataset === 'silver_klines' && (
            <>
              <select
                className="filter-select"
                value={filterSymbol}
                onChange={(e) => {
                  setFilterSymbol(e.target.value);
                  setPage(1);
                }}
              >
                {symbols.map((s) => (
                  <option key={s.symbol} value={s.symbol}>
                    {s.symbol}
                  </option>
                ))}
              </select>

              <select
                className="filter-select"
                value={filterTimeframe}
                onChange={(e) => {
                  setFilterTimeframe(e.target.value);
                  setPage(1);
                }}
              >
                <option value="15m">15m</option>
                <option value="1h">1h</option>
                <option value="4h">4h</option>
                <option value="1d">1d</option>
              </select>
            </>
          )}

          <select
            className="filter-select"
            value={pageSize}
            onChange={(e) => {
              setPageSize(parseInt(e.target.value));
              setPage(1);
            }}
          >
            <option value="25">25 per page</option>
            <option value="50">50 per page</option>
            <option value="100">100 per page</option>
          </select>
        </div>

        {/* View Switcher: Table vs Schema */}
        <div className="tab-pill-group">
          <button
            className={`tab-pill ${activeTab === 'table' ? 'active' : ''}`}
            onClick={() => setActiveTab('table')}
          >
            <Table size={13} />
            <span>Records Table</span>
          </button>
          <button
            className={`tab-pill ${activeTab === 'schema' ? 'active' : ''}`}
            onClick={() => setActiveTab('schema')}
          >
            <BookOpen size={13} />
            <span>Schema Dictionary</span>
          </button>
        </div>
      </div>

      {/* Dataset Profile Card */}
      {previewData && (
        <div className="grid-4-cols" style={{ marginTop: '1.25rem' }}>
          <div className="kpi-card">
            <div className="kpi-label">Total Partition Records</div>
            <div className="kpi-value">{formatNumber(previewData.total_rows)}</div>
            <div className="kpi-subtext">Server-side indexed count</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-label">Columns Defined</div>
            <div className="kpi-value">{previewData.profile.columns_count}</div>
            <div className="kpi-subtext">Explicit typed schema</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-label">Time Coverage Start</div>
            <div className="kpi-value" style={{ fontSize: '1.1rem' }}>
              {previewData.profile.min_open_time ? previewData.profile.min_open_time.slice(0, 16).replace('T', ' ') : '—'}
            </div>
            <div className="kpi-subtext">Oldest record in partition</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-label">Time Coverage Tip</div>
            <div className="kpi-value" style={{ fontSize: '1.1rem' }}>
              {previewData.profile.max_open_time ? previewData.profile.max_open_time.slice(0, 16).replace('T', ' ') : '—'}
            </div>
            <div className="kpi-subtext">Latest closed watermark</div>
          </div>
        </div>
      )}

      {/* Main Content Area: Table View or Schema Dictionary */}
      <div className="panel" style={{ marginTop: '1.25rem' }}>
        {activeTab === 'schema' ? (
          <div>
            <div className="panel-header">
              <div className="panel-title">
                <BookOpen size={18} color="var(--accent-cyan)" />
                <span>Data Contract & Column Dictionary: {currentDatasetMeta?.name}</span>
              </div>
              <span className="badge badge-neutral">{currentDatasetMeta?.layer}</span>
            </div>

            <p style={{ color: 'var(--text-muted)', fontSize: '0.88rem', marginBottom: '1.25rem' }}>
              {currentDatasetMeta?.description}
            </p>

            <div className="table-responsive">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Column Name</th>
                    <th>Data Type</th>
                    <th>Nullable</th>
                    <th>Description</th>
                  </tr>
                </thead>
                <tbody>
                  {currentDatasetMeta?.columns.map((col) => (
                    <tr key={col.name}>
                      <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: '#fff' }}>
                        {col.name}
                      </td>
                      <td style={{ fontFamily: 'var(--font-mono)', color: 'var(--accent-cyan)' }}>
                        {col.type}
                      </td>
                      <td>
                        <span className={`badge ${col.nullable ? 'badge-neutral' : 'badge-danger'}`}>
                          {col.nullable ? 'Nullable' : 'NOT NULL'}
                        </span>
                      </td>
                      <td style={{ color: 'var(--text-muted)' }}>{col.description}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : (
          <div>
            <div className="panel-header">
              <div className="panel-title">
                <Table size={18} color="var(--accent-cyan)" />
                <span>
                  Records Preview (Page {page} of {previewData?.total_pages || 1})
                </span>
              </div>
              <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                <button
                  className="btn btn-secondary btn-sm"
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1 || loading}
                >
                  <ChevronLeft size={14} />
                  <span>Prev</span>
                </button>
                <span style={{ fontSize: '0.82rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                  {page} / {previewData?.total_pages || 1}
                </span>
                <button
                  className="btn btn-secondary btn-sm"
                  onClick={() => setPage((p) => Math.min(previewData?.total_pages || 1, p + 1))}
                  disabled={page >= (previewData?.total_pages || 1) || loading}
                >
                  <span>Next</span>
                  <ChevronRight size={14} />
                </button>
              </div>
            </div>

            {loading ? (
              <div className="loading-state">
                <RefreshCw size={24} className="spin" />
                <span>Loading bounded records...</span>
              </div>
            ) : !previewData || previewData.rows.length === 0 ? (
              <div className="empty-state">
                <Database size={36} color="var(--text-muted)" />
                <p>No records found matching filters.</p>
              </div>
            ) : (
              <div className="table-responsive">
                <table className="data-table">
                  <thead>
                    <tr>
                      {Object.keys(previewData.rows[0]).map((key) => (
                        <th key={key} style={{ textTransform: 'capitalize' }}>
                          {key.replace(/_/g, ' ')}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {previewData.rows.map((row, idx) => (
                      <tr key={idx}>
                        {Object.entries(row).map(([k, v]) => (
                          <td key={k} style={{ fontFamily: typeof v === 'number' ? 'var(--font-mono)' : 'inherit' }}>
                            {typeof v === 'number'
                              ? k.includes('price') || k === 'open' || k === 'high' || k === 'low' || k === 'close'
                                ? formatCurrency(v)
                                : formatNumber(v)
                              : typeof v === 'boolean'
                              ? v
                                ? 'true'
                                : 'false'
                              : String(v ?? '—')}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
