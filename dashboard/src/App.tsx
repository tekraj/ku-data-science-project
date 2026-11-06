import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { LoginPage } from "./pages/LoginPage";
import { ProtectedRoute } from "./pages/ProtectedRoute";
import { DashboardPage } from "./pages/DashboardPage";
import { NewsPage } from "./pages/NewsPage";
import { NewsDetailPage } from "./pages/NewsDetailPage";
import { LogsPage } from "./pages/LogsPage";
import { TechnicalsPage } from "./pages/TechnicalsPage";
import { MarketPage } from "./pages/MarketPage";
import { OrderBookPage } from "./pages/OrderBookPage";
import { BrokersPage } from "./pages/BrokersPage";

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<ProtectedRoute />}>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/news" element={<NewsPage />} />
          <Route path="/news/:id" element={<NewsDetailPage />} />
          <Route path="/logs" element={<LogsPage />} />
          <Route path="/technicals" element={<TechnicalsPage />} />
          <Route path="/market" element={<MarketPage />} />
          <Route path="/orderbook" element={<OrderBookPage />} />
          <Route path="/brokers" element={<BrokersPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
