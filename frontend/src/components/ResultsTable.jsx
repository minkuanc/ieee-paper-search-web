export default function ResultsTable({ papers, truncated, total, selectedIndices, setSelectedIndices }) {
  if (papers.length === 0) return null

  function toggle(i) {
    setSelectedIndices(prev => {
      const next = new Set(prev)
      next.has(i) ? next.delete(i) : next.add(i)
      return next
    })
  }

  function selectAll() { setSelectedIndices(new Set(papers.map((_, i) => i))) }
  function deselectAll() { setSelectedIndices(new Set()) }

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
          <span className="stat-value">{papers.length.toLocaleString()}</span>
          {truncated && <span className="stat-cap">(capped at 200 — refine keywords for deeper results)</span>}
        </div>
        <div className="stat-divider">·</div>
        <div className="stat-item">
          <span className="stat-label">Selected</span>
          <span className="stat-value">{selectedIndices.size}</span>
        </div>
      </div>
      <div className="results-controls">
        <span>
          <button className="btn-secondary" onClick={selectAll}>Select All</button>{' '}
          <button className="btn-secondary" onClick={deselectAll}>Deselect All</button>
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
            {papers.map((p, i) => (
              <tr key={i} onClick={() => toggle(i)} className={selectedIndices.has(i) ? 'selected' : ''}>
                <td style={{textAlign:'center'}}>{selectedIndices.has(i) ? '☑' : '☐'}</td>
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
