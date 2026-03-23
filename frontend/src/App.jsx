import { useState } from 'react'
import KeywordInput from './components/KeywordInput'
import './App.css'

export default function App() {
  const [loading, setLoading] = useState(false)
  const [papers, setPapers] = useState([])
  const [truncated, setTruncated] = useState(false)
  const [total, setTotal] = useState(0)
  const [selectedIndices, setSelectedIndices] = useState(new Set())
  const [keywords, setKeywords] = useState([])

  async function handleSearch(kws) {
    setLoading(true)
    setKeywords(kws)
    try {
      const res = await fetch('/api/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ keywords: kws, years_back: 3 }),
      })
      const data = await res.json()
      setPapers(data.papers)
      setTruncated(data.truncated)
      setTotal(data.total)
      setSelectedIndices(new Set())
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="app">
      <h1>IEEE Paper Search</h1>
      <KeywordInput onSearch={handleSearch} loading={loading} />
      <p>{papers.length} papers loaded</p>
    </div>
  )
}
