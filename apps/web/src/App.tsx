import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/AppShell/AppShell'
import { AboutPage } from './pages/AboutPage/AboutPage'
import { HomePage } from './pages/HomePage/HomePage'
import { PlayerCareerPage } from './pages/PlayerCareerPage/PlayerCareerPage'
import { PlayerComparePage } from './pages/PlayerComparePage/PlayerComparePage'
import { PlayerLeadersPage } from './pages/PlayerLeadersPage/PlayerLeadersPage'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/" element={<HomePage />} />
          <Route path="/about" element={<AboutPage />} />
          <Route path="/nfl/leaders" element={<PlayerLeadersPage />} />
          <Route path="/nfl/players/:playerId" element={<PlayerCareerPage />} />
          <Route path="/nfl/compare" element={<PlayerComparePage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
