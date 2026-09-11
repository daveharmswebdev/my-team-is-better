import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/AppShell/AppShell'
import { AboutPage } from './pages/AboutPage/AboutPage'
import { HomePage } from './pages/HomePage/HomePage'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/" element={<HomePage />} />
          <Route path="/about" element={<AboutPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
