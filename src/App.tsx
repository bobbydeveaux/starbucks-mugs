import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { CostaVsStarbucksPage } from './pages/CostaVsStarbucksPage';
import { FerrariPage } from './pages/FerrariPage';
import { LamborghiniPage } from './pages/LamborghiniPage';
import { ComparePage } from './pages/ComparePage';

function App() {
  return (
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <Routes>
        <Route path="/" element={<CostaVsStarbucksPage />} />
        <Route path="/ferrari" element={<FerrariPage />} />
        <Route path="/lamborghini" element={<LamborghiniPage />} />
        <Route path="/compare" element={<ComparePage />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
