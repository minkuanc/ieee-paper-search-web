import { useState } from 'react'

export default function KeywordInput({ onSearch, loading }) {
  const [keywords, setKeywords] = useState(['', '', ''])

  function updateKeyword(i, val) {
    setKeywords(prev => prev.map((k, idx) => idx === i ? val : k))
  }

  function addKeyword() {
    setKeywords(prev => [...prev, ''])
  }

  function handleSearch() {
    const active = keywords.map(k => k.trim()).filter(Boolean)
    if (active.length === 0) return
    onSearch(active)
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
        <button onClick={handleSearch} disabled={loading} className="btn-primary">
          {loading ? 'Searching…' : 'Search'}
        </button>
      </div>
    </div>
  )
}
