import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { LandingPage } from './pages/LandingPage';
import { AnalysisPage } from './pages/AnalysisPage';
import { ResultsPage } from './pages/ResultsPage';
import { NotFoundPage } from './pages/NotFoundPage';

export const App: React.FC = () => {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/documents/:id/analysis" element={<AnalysisPage />} />
        <Route path="/documents/:id/results" element={<ResultsPage />} />
        {/* Shorthand demo routes */}
        <Route path="/analysis" element={<Navigate to="/documents/sample-demo-4092/analysis" replace />} />
        <Route path="/results" element={<Navigate to="/documents/sample-demo-4092/results" replace />} />
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </BrowserRouter>
  );
};

export default App;
