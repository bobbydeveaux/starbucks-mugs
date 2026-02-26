import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import App from './App';
import * as clientModule from '@/api/client';

vi.mock('@/auth/oidc', () => ({
  initiateLogin: vi.fn().mockResolvedValue(undefined),
  handleCallback: vi.fn().mockResolvedValue(false),
  logout: vi.fn(),
}));

describe('App routing', () => {
  beforeEach(() => {
    localStorage.clear();
    // Reset to login page
    window.history.pushState({}, '', '/');
  });

  it('redirects unauthenticated users to /login', () => {
    vi.spyOn(clientModule, 'isAuthenticated').mockReturnValue(false);
    render(<App />);
    expect(screen.getByRole('heading', { name: /Sign in/i })).toBeInTheDocument();
  });

  it('renders dashboard for authenticated users', () => {
    vi.spyOn(clientModule, 'isAuthenticated').mockReturnValue(true);
    render(<App />);
    expect(screen.getByText(/TripWire Security Dashboard/i)).toBeInTheDocument();
  });
});
