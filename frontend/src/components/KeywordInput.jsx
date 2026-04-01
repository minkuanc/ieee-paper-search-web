import { useState } from 'react'

const CURRENT_YEAR = new Date().getFullYear()
const YEAR_OPTIONS = Array.from({ length: CURRENT_YEAR - 1999 }, (_, i) => CURRENT_YEAR - i)

export default function KeywordInput({ onSearch, loading }) {
  const [keywords, setKeywords] = useState(['', '', ''])
  const [startYear, setStartYear] = useState(CURRENT_YEAR - 3)

  function updateKeyword(i, val) {
    setKeywords(prev => prev.map((k, idx) => idx === i ? val : k))
  }

  function addKeyword() {
    setKeywords(prev => [...prev, ''])
  }

  function handleSearch() {
    const active = keywords.map(k => k.trim()).filter(Boolean)
    if (active.length === 0) return
    onSearch(active, startYear)
  }

  return (
    <div className="keyword-section">
      <div className="keyword-inputs">
        {keywords.map((kw, i) => (
          <input
            key={i}
            type="text"
            value={kw}
            placeholder={`Keyword ${i + 1}`}
            onChange={e => updateKeyword(i, e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleSearch()}
            className="keyword-input"
          />
        ))}
      </div>
      <div className="keyword-actions">
        <button onClick={addKeyword} className="btn-secondary">+ Add Keyword</button>
        <label className="year-label">
          From year:
          <select
            value={startYear}
            onChange={e => setStartYear(Number(e.target.value))}
            className="year-select"
          >
            {YEAR_OPTIONS.map(y => (
              <option key={y} value={y}>{y}</option>
            ))}
          </select>
          <span className="year-to">– {CURRENT_YEAR}</span>
        </label>
        <button onClick={handleSearch} disabled={loading} className="btn-primary">
          {loading ? 'Searching…' : 'Search'}
        </button>
      </div>
    </div>
  )
}
