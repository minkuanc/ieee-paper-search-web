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
      {truncated && (
        <div className="truncation-banner">
          ⚠ Showing first 200 of {total.toLocaleString()} results — refine keywords for more.
        </div>
      )}
      <div className="results-controls">
        <span className="results-count">Found {papers.length} paper(s). {selectedIndices.size} selected.</span>
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
              <th style={{width:180}}>Authors</th>
              <th style={{width:160}}>Venue</th>
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
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
