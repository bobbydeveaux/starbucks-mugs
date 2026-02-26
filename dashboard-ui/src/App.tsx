import { useEffect, useState } from 'react';
import {
  BrowserRouter,
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { isAuthenticated } from '@/api/client';
import { handleCallback, initiateLogin, logout } from '@/auth/oidc';

// ---------------------------------------------------------------------------
// QueryClient
// ---------------------------------------------------------------------------

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
    },
  },
});

// ---------------------------------------------------------------------------
// Route guard
// ---------------------------------------------------------------------------

interface ProtectedRouteProps {
  children: React.ReactNode;
}

function ProtectedRoute({ children }: ProtectedRouteProps) {
  const location = useLocation();

  if (!isAuthenticated()) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  return <>{children}</>;
}

// ---------------------------------------------------------------------------
// Pages (placeholder — full implementation in later tasks)
// ---------------------------------------------------------------------------

function DashboardPage() {
  return (
    <div>
      <h1>TripWire Security Dashboard</h1>
      <button onClick={() => logout()}>Logout</button>
    </div>
  );
}

function LoginPage() {
  const location = useLocation();
  const from = (location.state as { from?: Location } | null)?.from?.pathname ?? '/';
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleLogin = async () => {
    setLoading(true);
    setError(null);
    try {
      await initiateLogin();
    } catch {
      setError('Failed to initiate login. Please try again.');
      setLoading(false);
    }
  };

  if (isAuthenticated()) {
    return <Navigate to={from} replace />;
  }

  return (
    <div>
      <h1>TripWire — Sign In</h1>
      {error && <p role="alert">{error}</p>}
      <button onClick={handleLogin} disabled={loading}>
        {loading ? 'Redirecting…' : 'Sign in with SSO'}
      </button>
    </div>
  );
}

function CallbackPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(location.search);

    handleCallback(params).then((ok) => {
      if (ok) {
        navigate('/', { replace: true });
      } else {
        setError('Authentication failed. Please try again.');
      }
    });
  }, [location.search, navigate]);

  if (error) {
    return (
      <div>
        <p role="alert">{error}</p>
        <a href="/login">Back to login</a>
      </div>
    );
  }

  return <div>Completing sign-in…</div>;
}

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/auth/callback" element={<CallbackPage />} />
      <Route
        path="/*"
        element={
          <ProtectedRoute>
            <DashboardPage />
          </ProtectedRoute>
        }
      />
    </Routes>
  );
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </QueryClientProvider>
  );
}

export default App;
