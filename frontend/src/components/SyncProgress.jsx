import styles from './SyncProgress.module.css'

export default function SyncProgress({ syncState, totalRows }) {
  if (!syncState) return null

  const { results = {}, summary } = syncState
  const done = Object.keys(results).length
  const pct = totalRows > 0 ? Math.round((done / totalRows) * 100) : 0

  const counts = Object.values(results).reduce((acc, s) => {
    acc[s] = (acc[s] || 0) + 1
    return acc
  }, {})

  return (
    <div className={styles.bar}>
      {/* Progress track */}
      <div className={styles.track}>
        <div
          className={`${styles.fill} ${summary ? styles.fillDone : ''}`}
          style={{ width: summary ? '100%' : `${pct}%` }}
        />
      </div>

      {/* Stats */}
      <div className={styles.stats}>
        {!summary ? (
          <>
            <span className={styles.pct}>{pct}%</span>
            <Pill label="UPDATED" count={counts.UPDATED} color="#10b981" />
            <Pill label="SKIPPED" count={counts.SKIPPED} color="#555" />
            <Pill label="ERROR"   count={counts.ERROR}   color="#ef4444" />
            <Pill label="CONFLICT" count={counts.CONFLICT} color="#f59e0b" />
            <span className={styles.progress}>{done} / {totalRows}</span>
          </>
        ) : (
          <>
            <span className={styles.done}>✓ SYNC COMPLETE</span>
            <Pill label="UPDATED"  count={summary.updated}   color="#10b981" />
            <Pill label="CREATED"  count={summary.created}   color="#6366f1" />
            <Pill label="SKIPPED"  count={summary.skipped}   color="#555" />
            <Pill label="ERRORS"   count={summary.errors}    color="#ef4444" />
            <Pill label="CONFLICT" count={summary.conflicts} color="#f59e0b" />
              <span className={styles.duration}>{formatDuration(summary.duration_seconds)}s</span>
          </>
        )}
      </div>
    </div>
  )
}

function formatDuration(seconds) {
  if (!seconds && seconds !== 0) return ''

  const mins = Math.floor(seconds / 60)
  const secs = seconds % 60

  return `${mins}:${secs.toString().padStart(2, '0')}`
}

function Pill({ label, count, color }) {
  if (!count) return null
  return (
    <span className="pill" style={{ '--c': color }}>
      <style>{`.pill{display:inline-flex;align-items:center;gap:4px;font-family:'IBM Plex Mono',monospace;font-size:10px;color:var(--c);border:1px solid var(--c)33;background:var(--c)11;padding:1px 6px;border-radius:2px;}`}</style>
      {count} {label}
    </span>
  )
}
