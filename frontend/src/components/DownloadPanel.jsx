import { useState } from 'react'

export default function DownloadPanel({ selectedPapers, keywords }) {
  const [error, setError] = useState('')
  const [progress, setProgress] = useState(null)
  const [jobId, setJobId] = useState(null)
  const [summary, setSummary] = useState(null)
  const [downloading, setDownloading] = useState(false)
  const [destFolder, setDestFolder] = useState('')

  async function handleDownload() {
    setError('')
    setSummary(null)
    setProgress(null)

    // Step 1: open native folder picker
    let folderRes
    try {
      folderRes = await fetch('/api/choose-folder')
    } catch {
      setError('Network error — is the backend running?')
      return
    }
    if (!folderRes.ok) return  // user cancelled (204)
    const { path } = await folderRes.json()
    setDestFolder(path)

    // Step 2: start download job
    let res
    try {
      res = await fetch('/api/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ papers: selectedPapers, dest_folder: path, keywords }),
      })
    } catch {
      setError('Network error — is the backend running?')
      return
    }

    if (!res.ok) {
      const data = await res.json()
      setError(data.detail || 'Download failed')
      return
    }

    const { job_id } = await res.json()
    setJobId(job_id)
    setDownloading(true)

    // Step 3: stream SSE progress
    const es = new EventSource(`/api/download/${job_id}/progress`)
    es.onmessage = e => {
      const event = JSON.parse(e.data)
      if (!event.done) setProgress(event)
      if (event.done) {
        es.close()
        setDownloading(false)
        fetch(`/api/download/${job_id}/status`)
          .then(r => r.json())
          .then(s => setSummary(s))
          .catch(() => setError('Could not fetch download summary'))
      }
    }
    es.onerror = () => { es.close(); setDownloading(false) }
  }

  const canDownload = selectedPapers.length > 0 && !downloading

  return (
    <div className="download-section">
      <div className="download-row">
        {destFolder && <span className="folder-display">{destFolder}</span>}
        <button onClick={handleDownload} disabled={!canDownload} className="btn-primary">
          {downloading ? 'Downloading…' : `Download Selected (${selectedPapers.length})`}
        </button>
      </div>

      {error && <div className="error-msg">⚠ {error}</div>}

      {(downloading || progress) && (
        <div className="progress-section">
          <progress
            value={progress ? progress.index : 0}
            max={progress ? progress.total : selectedPapers.length}
            className="progress-bar"
          />
          <div className="progress-label">
            {progress
              ? `${progress.index} / ${progress.total} — ${progress.title.slice(0, 70)}${progress.title.length > 70 ? '…' : ''}`
              : 'Starting download…'}
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
