import {
  BrowserRouter,
  Navigate,
  Route,
  Routes,
  useLocation,
} from 'react-router-dom'
import { AppShell } from './components/AppShell/AppShell'
import {
  COMPARE_PAGE_PATH,
  COMPARE_SHARE_PATH,
  VERDICT_PAGE_PATH,
  VERDICT_SHARE_PATH,
} from './lib/sharePaths'
import { AboutPage } from './pages/AboutPage/AboutPage'
import { HomePage } from './pages/HomePage/HomePage'
import { PlayerCareerPage } from './pages/PlayerCareerPage/PlayerCareerPage'
import { PlayerComparePage } from './pages/PlayerComparePage/PlayerComparePage'
import { PlayerLeadersPage } from './pages/PlayerLeadersPage/PlayerLeadersPage'

/**
 * A minted share link opened where no proxy serves its preview page (issue
 * #185): replace it with the page it names, the query untouched, so that
 * page's own landing logic judges the query exactly as for an old link.
 */
function ShareLanding({ to }: { to: string }) {
  const { search } = useLocation()
  return <Navigate to={{ pathname: to, search }} replace />
}

/** The app's route table, without a router, so tests can supply their own. */
export function AppRoutes() {
  return (
    <Routes>
      <Route
        path={VERDICT_SHARE_PATH}
        element={<ShareLanding to={VERDICT_PAGE_PATH} />}
      />
      <Route
        path={COMPARE_SHARE_PATH}
        element={<ShareLanding to={COMPARE_PAGE_PATH} />}
      />
      <Route element={<AppShell />}>
        <Route path={VERDICT_PAGE_PATH} element={<HomePage />} />
        <Route path="/about" element={<AboutPage />} />
        <Route path="/nfl/leaders" element={<PlayerLeadersPage />} />
        <Route path="/nfl/players/:playerId" element={<PlayerCareerPage />} />
        <Route path={COMPARE_PAGE_PATH} element={<PlayerComparePage />} />
      </Route>
    </Routes>
  )
}

function App() {
  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  )
}

export default App
