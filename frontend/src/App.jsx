import { useState } from 'react'
import KeywordInput from './components/KeywordInput'
import ResultsTable from './components/ResultsTable'
import DownloadPanel from './components/DownloadPanel'
import './App.css'

export default function App() {
  const [loading, setLoading] = useState(false)
  const [searchError, setSearchError] = useState('')
  const [papers, setPapers] = useState([])
  const [truncated, setTruncated] = useState(false)
  const [total, setTotal] = useState(0)
  const [selectedIndices, setSelectedIndices] = useState(new Set())
  const [keywords, setKeywords] = useState([])

  async function handleSearch(kws, startYear) {
    setLoading(true)
    setSearchError('')
    setKeywords(kws)
    setPapers([])
    setTotal(0)
    setSelectedIndices(new Set())
    try {
      const res = await fetch('/api/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ keywords: kws, start_year: startYear }),
      })
      if (!res.ok) {
        const err = await res.json()
        setSearchError(err.detail || 'Search failed')
        return
      }
      const data = await res.json()
      setPapers(data.papers)
      setTruncated(data.truncated)
      setTotal(data.total)
      setSelectedIndices(new Set())
    } catch {
      setSearchError('Cannot reach backend — make sure it is running on port 8000.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="app">
      <h1>IEEE Paper Search</h1>
      <KeywordInput onSearch={handleSearch} loading={loading} />
      {loading && <div className="searching-msg">Searching IEEE Xplore… this may take 10–20 seconds.</div>}
      {searchError && <div className="error-msg" style={{marginBottom: 12}}>⚠ {searchError}</div>}
      <ResultsTable
        papers={papers}
        truncated={truncated}
        total={total}
        selectedIndices={selectedIndices}
        setSelectedIndices={setSelectedIndices}
      />
      <DownloadPanel
        selectedPapers={papers.filter((_, i) => selectedIndices.has(i))}
        keywords={keywords}
      />
    </div>
  )
}
