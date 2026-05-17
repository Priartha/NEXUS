import { useEffect, useState, useCallback } from 'react'
import {
  Database,
  RefreshCw,
  Download,
  AlertTriangle,
  CheckCircle,
  XCircle,
  Clock,
  HardDrive,
  Shield,
} from 'lucide-react'

interface IntegrityCheck {
  check_name: string
  status: 'pass' | 'fail' | 'warning'
  message: string
  details?: string
}

interface TableInfo {
  name: string
  row_count: number
  size_bytes: number
  oldest_record: string | null
  newest_record: string | null
}

interface DbStatus {
  database_size_mb: number
  total_tables: number
  total_records: number
  wal_mode: boolean
  integrity_checks: IntegrityCheck[]
  table_info: TableInfo[]
  oldest_record: string | null
  newest_record: string | null
  timestamp: number
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function DbStatusPanel() {
  const [status, setStatus] = useState<DbStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [backupRunning, setBackupRunning] = useState(false)
  const [backupMessage, setBackupMessage] = useState<string | null>(null)

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch('/db/integrity')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      setStatus(json)
      setError(null)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  const runBackup = async () => {
    setBackupRunning(true)
    setBackupMessage(null)
    try {
      const res = await fetch('/db/backup', { method: 'POST' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      setBackupMessage(json.message ?? 'Backup completed successfully')
    } catch (e: any) {
      setBackupMessage(`Backup failed: ${e.message}`)
    } finally {
      setBackupRunning(false)
    }
  }

  useEffect(() => {
    fetchStatus()
    const interval = setInterval(fetchStatus, 120000)
    return () => clearInterval(interval)
  }, [fetchStatus])

  if (loading && !status) {
    return (
      <div className="db-status-panel">
        <div className="dsp-loading">
          <RefreshCw size={16} className="dsp-loading-spinner" />
          <span>Loading database status...</span>
        </div>
      </div>
    )
  }

  return (
    <div className="db-status-panel">
      {/* Header */}
      <div className="dsp-header">
        <h2>
          <Database size={14} />
          Database Status
        </h2>
        <div className="dsp-controls">
          <button
            className="dsp-btn"
            onClick={runBackup}
            disabled={backupRunning}
          >
            {backupRunning ? (
              <>
                <RefreshCw size={12} className="dsp-btn-spinner" />
                Backing up...
              </>
            ) : (
              <>
                <Download size={12} />
                Backup
              </>
            )}
          </button>
          <button className="dsp-btn" onClick={fetchStatus} title="Refresh">
            <RefreshCw size={12} />
          </button>
        </div>
      </div>

      {/* Backup Message */}
      {backupMessage && (
        <div className={`dsp-backup-msg ${backupMessage.includes('failed') ? 'error' : 'success'}`}>
          {backupMessage.includes('failed') ? <XCircle size={12} /> : <CheckCircle size={12} />}
          <span>{backupMessage}</span>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="dsp-error">
          <AlertTriangle size={12} />
          <span>{error}</span>
          <button className="dsp-btn" onClick={fetchStatus}>Retry</button>
        </div>
      )}

      {/* Summary */}
      {status && (
        <div className="dsp-summary">
          <div className="dsp-stat">
            <div className="dsp-stat-icon">
              <HardDrive size={16} />
            </div>
            <div className="dsp-stat-info">
              <span className="dsp-stat-label">Database Size</span>
              <span className="dsp-stat-value">{status.database_size_mb.toFixed(1)} MB</span>
            </div>
          </div>
          <div className="dsp-stat">
            <div className="dsp-stat-icon">
              <Database size={16} />
            </div>
            <div className="dsp-stat-info">
              <span className="dsp-stat-label">Tables</span>
              <span className="dsp-stat-value">{status.total_tables}</span>
            </div>
          </div>
          <div className="dsp-stat">
            <div className="dsp-stat-icon">
              <Shield size={16} />
            </div>
            <div className="dsp-stat-info">
              <span className="dsp-stat-label">WAL Mode</span>
              <span className={`dsp-stat-value ${status.wal_mode ? 'positive' : 'negative'}`}>
                {status.wal_mode ? 'Enabled' : 'Disabled'}
              </span>
            </div>
          </div>
          <div className="dsp-stat">
            <div className="dsp-stat-icon">
              <Clock size={16} />
            </div>
            <div className="dsp-stat-info">
              <span className="dsp-stat-label">Records</span>
              <span className="dsp-stat-value">{status.total_records.toLocaleString()}</span>
            </div>
          </div>
        </div>
      )}

      {/* Integrity Checks */}
      {status && status.integrity_checks.length > 0 && (
        <div className="dsp-section">
          <h3>Integrity Checks</h3>
          <div className="dsp-checks">
            {status.integrity_checks.map((check, i) => (
              <div
                key={i}
                className={`dsp-check ${check.status}`}
              >
                <div className="dsp-check-icon">
                  {check.status === 'pass' ? (
                    <CheckCircle size={14} />
                  ) : check.status === 'fail' ? (
                    <XCircle size={14} />
                  ) : (
                    <AlertTriangle size={14} />
                  )}
                </div>
                <div className="dsp-check-info">
                  <span className="dsp-check-name">{check.check_name}</span>
                  <span className="dsp-check-message">{check.message}</span>
                  {check.details && (
                    <span className="dsp-check-details">{check.details}</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Table Info */}
      {status && status.table_info.length > 0 && (
        <div className="dsp-section">
          <h3>Table Details</h3>
          <div className="dsp-tables">
            {status.table_info.map((table) => (
              <div key={table.name} className="dsp-table-card">
                <div className="dsp-table-header">
                  <span className="dsp-table-name">{table.name}</span>
                  <span className="dsp-table-rows">{table.row_count.toLocaleString()} rows</span>
                </div>
                <div className="dsp-table-details">
                  <div className="dsp-table-row">
                    <span className="dsp-table-label">Size</span>
                    <span className="dsp-table-value">{formatBytes(table.size_bytes)}</span>
                  </div>
                  <div className="dsp-table-row">
                    <span className="dsp-table-label">Oldest</span>
                    <span className="dsp-table-value">{table.oldest_record ?? '--'}</span>
                  </div>
                  <div className="dsp-table-row">
                    <span className="dsp-table-label">Newest</span>
                    <span className="dsp-table-value">{table.newest_record ?? '--'}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Date Range */}
      {status && (status.oldest_record || status.newest_record) && (
        <div className="dsp-section">
          <h3>Data Range</h3>
          <div className="dsp-date-range">
            <div className="dsp-date-item">
              <span className="dsp-date-label">First Record</span>
              <span className="dsp-date-value">{status.oldest_record ?? '--'}</span>
            </div>
            <div className="dsp-date-item">
              <span className="dsp-date-label">Last Record</span>
              <span className="dsp-date-value">{status.newest_record ?? '--'}</span>
            </div>
          </div>
        </div>
      )}

      {!loading && !status && (
        <div className="dsp-empty">
          <Database size={24} />
          <p>No database status available</p>
        </div>
      )}
    </div>
  )
}
