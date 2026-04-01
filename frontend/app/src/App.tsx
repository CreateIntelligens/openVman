import { useState, useEffect } from 'react'

function App() {
  const [status, setStatus] = useState('Initializing...')

  useEffect(() => {
    setStatus('Ready for Live Interaction')
  }, [])

  return (
    <div className="app-container">
      <h1>openVman Live Avatar</h1>
      <div className="status-bar">
        Status: {status}
      </div>
      <div className="avatar-viewer">
        {/* Avatar rendering will go here */}
        <div style={{ width: '400px', height: '400px', backgroundColor: '#333', borderRadius: '50%', margin: '20px auto' }}>
          <p style={{ color: 'white', paddingTop: '180px', textAlign: 'center' }}>Avatar Placeholder</p>
        </div>
      </div>
      <div className="controls">
        <button onClick={() => console.log('Start ASR')}>Start Listening</button>
      </div>
    </div>
  )
}

export default App
