import { Navigate, Route, Routes } from "react-router-dom";

import { MarketPage } from "./pages/MarketPage";

export function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/market" replace />} />
      <Route path="/market" element={<MarketPage />} />
      <Route path="/lots/:lotId" element={<MarketPage />} />
    </Routes>
  );
}
