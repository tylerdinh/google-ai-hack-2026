import { Routes, Route, Navigate } from 'react-router-dom'
import LoginPage from './pages/LoginPage'
import WatchlistPage from './pages/WatchlistPage'
import StockDetailPage from './pages/StockDetailPage'

export default function App() {
  return (
    <Routes>
      <Route path="/"        element={<LoginPage />} />
      <Route path="/stocks"  element={<WatchlistPage />} />
      <Route path="/stock"   element={<StockDetailPage />} />
      <Route path="*"        element={<Navigate to="/" replace />} />
    </Routes>
  )
}