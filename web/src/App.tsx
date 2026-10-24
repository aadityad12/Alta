import { useEffect, useState } from 'react'

// Placeholder until the real app shell lands (#28).
function App() {
  const [server, setServer] = useState('checking…')

  useEffect(() => {
    fetch('/health')
      .then((r) => r.json())
      .then((d) => setServer(d.ok ? 'ok' : 'not ok'))
      .catch(() => setServer('unreachable'))
  }, [])

  return (
    <main style={{ fontFamily: 'system-ui, sans-serif', padding: 32 }}>
      <h1>Bench</h1>
      <p>Server: {server}</p>
    </main>
  )
}

export default App
