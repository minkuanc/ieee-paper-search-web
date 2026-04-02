import { useState } from 'react'

const TYPE_FILTERS = [
  { label: 'All',                     value: 'all' },
  { label: 'Journals / Transactions', value: 'journal' },
  { label: 'Conferences',             value: 'conference' },
]

export default function ResultsTable({ papers, truncated, total, selectedIndices, setSelectedIndices }) {
  const [typeFilter, setTypeFilter] = useState('all')

  if (papers.length === 0) return null

  // Apply type filter
  const filtered = typeFilter === 'all'
    ? papers
    : papers.filter(p => (p.content_type || '') === typeFilter)

  // Map filtered indices back to original paper indices for selection
  const filteredWithIdx = filtered.map(p => ({ p, origIdx: papers.indexOf(p) }))

  function toggle(origIdx) {
    setSelectedIndices(prev => {
      const next = new Set(prev)
      next.has(origIdx) ? next.delete(origIdx) : next.add(origIdx)
      return next
    })
  }

  function selectAllFiltered() {
    setSelectedIndices(prev => {
      const next = new Set(prev)
      filteredWithIdx.forEach(({ origIdx }) => next.add(origIdx))
      return next
    })
  }

  function deselectAllFiltered() {
    setSelectedIndices(prev => {
      const next = new Set(prev)
      filteredWithIdx.forEach(({ origIdx }) => next.delete(origIdx))
      return next
    })
  }

  const selectedInView = filteredWithIdx.filter(({ origIdx }) => selectedIndices.has(origIdx)).length

  return (
    <div className="results-section">
      <div className="search-stats">
        <div className="stat-item">
          <span className="stat-label">IEEE Xplore found</span>
          <span className="stat-value">{total.toLocaleString()}</span>
        </div>
        <div className="stat-divider">→</div>
        <div className="stat-item">
          <span className="stat-label">Showing</span>
          <span className="stat-value">{filtered.length.toLocaleString()}</span>
          {truncated && <span className="stat-cap">(capped at 600 — refine keywords for deeper results)</span>}
        </div>
        <div className="stat-divider">·</div>
        <div className="stat-item">
          <span className="stat-label">Selected</span>
          <span className="stat-value">{selectedIndices.size}</span>
        </div>
      </div>

      <div className="results-controls">
        {/* Type filter toggle */}
        <span className="type-filter">
          {TYPE_FILTERS.map(f => (
            <button
              key={f.value}
              className={`btn-filter${typeFilter === f.value ? ' active' : ''}`}
              onClick={() => setTypeFilter(f.value)}
            >
              {f.label}
            </button>
          ))}
        </span>
        {/* Select / deselect */}
        <span>
          <button className="btn-secondary" onClick={selectAllFiltered}>Select All</button>{' '}
          <button className="btn-secondary" onClick={deselectAllFiltered}>Deselect All</button>
        </span>
      </div>

      <div className="table-wrap">
        <table className="results-table">
          <thead>
            <tr>
              <th style={{width:36}}>☐</th>
              <th>Title</th>
              <th style={{width:60}}>Year</th>
              <th style={{width:170}}>Authors</th>
              <th style={{width:140}}>Venue</th>
              <th style={{width:220}}>IEEE Keywords</th>
            </tr>
          </thead>
          <tbody>
            {filteredWithIdx.map(({ p, origIdx }) => (
              <tr
                key={origIdx}
                onClick={() => toggle(origIdx)}
                className={selectedIndices.has(origIdx) ? 'selected' : ''}
              >
                <td style={{textAlign:'center'}}>{selectedIndices.has(origIdx) ? '☑' : '☐'}</td>
                <td title={p.title}>{p.title.length > 80 ? p.title.slice(0,79) + '…' : p.title}</td>
                <td style={{textAlign:'center'}}>{p.year}</td>
                <td>{p.authors.length > 35 ? p.authors.slice(0,34) + '…' : p.authors}</td>
                <td>{p.venue.length > 35 ? p.venue.slice(0,34) + '…' : p.venue}</td>
                <td className="kw-cell" title={p.ieee_keywords && p.ieee_keywords.join('; ')}>
                  {p.ieee_keywords && p.ieee_keywords.length > 0
                    ? p.ieee_keywords.join('; ').slice(0, 80) + (p.ieee_keywords.join('; ').length > 80 ? '…' : '')
                    : <span className="kw-none">—</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
