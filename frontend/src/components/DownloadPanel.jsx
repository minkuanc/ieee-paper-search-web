import { useState } from 'react'

export default function DownloadPanel({ selectedPapers, keywords }) {
  const [destFolder, setDestFolder] = useState('')
  const [error, setError] = useState('')
  const [progress, setProgress] = useState(null)
  const [jobId, setJobId] = useState(null)
  const [summary, setSummary] = useState(null)
  const [downloading, setDownloading] = useState(false)

  async function handleDownload() {
    setError('')
    setSummary(null)
    setProgress(null)

    const res = await fetch('/api/download', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ papers: selectedPapers, dest_folder: destFolder, keywords }),
    })

    if (!res.ok) {
      const data = await res.json()
      setError(data.detail || 'Download failed')
      return
    }

    const { job_id } = await res.json()
    setJobId(job_id)
    setDownloading(true)

    const es = new EventSource(`/api/download/${job_id}/progress`)
    es.onmessage = e => {
      const event = JSON.parse(e.data)
      setProgress(event)
      if (event.done) {
        es.close()
        setDownloading(false)
        fetch(`/api/download/${job_id}/status`)
          .then(r => r.json())
          .then(s => setSummary(s))
      }
    }
    es.onerror = () => { es.close(); setDownloading(false) }
  }

  const canDownload = selectedPapers.length > 0 && destFolder.trim() && !downloading

  return (
    <div className="download-section">
      <div className="download-row">
        <input
          type="text"
          value={destFolder}
          onChange={e => setDestFolder(e.target.value)}
          placeholder="/Users/you/Downloads"
          className="folder-input"
        />
        <button onClick={handleDownload} disabled={!canDownload} className="btn-primary">
          {downloading ? 'Downloading…' : `Download Selected (${selectedPapers.length})`}
        </button>
      </div>

      {error && <div className="error-msg">⚠ {error}</div>}

      {progress && (
        <div className="progress-section">
          <progress value={progress.index} max={progress.total} className="progress-bar" />
          <div className="progress-label">
            {progress.index} / {progress.total} — {progress.title.slice(0, 60)}{progress.title.length > 60 ? '…' : ''}
          </div>
        </div>
      )}

      {summary && (
        <div className="summary">
          ✓ {summary.downloaded} downloaded, {summary.failed} failed.{' '}
          <a href={`/api/download/${jobId}/excel`} download="papers.xlsx" className="excel-link">
            Download Excel
          </a>
        </div>
      )}
    </div>
  )
}
