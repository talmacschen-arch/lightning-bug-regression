import { render, screen } from '@testing-library/react';
import { describe, it, expect, beforeAll, afterAll, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { ErrorBoundary } from './ErrorBoundary';

// Suppress console.error output from ErrorBoundary during tests
beforeAll(() => {
  vi.spyOn(console, 'error').mockImplementation(() => undefined);
});

afterAll(() => {
  vi.restoreAllMocks();
});

function NormalChild() {
  return <div data-testid="normal-child">All good</div>;
}

function ThrowingChild({ shouldThrow }: { shouldThrow: boolean }) {
  if (shouldThrow) {
    throw new Error('Test error from child');
  }
  return <div data-testid="fine-child">Fine</div>;
}

describe('ErrorBoundary', () => {
  it('renders children normally when no error', () => {
    render(
      <MemoryRouter>
        <ErrorBoundary>
          <NormalChild />
        </ErrorBoundary>
      </MemoryRouter>,
    );
    expect(screen.getByTestId('normal-child')).toBeInTheDocument();
  });

  it('renders fallback UI when child throws', () => {
    render(
      <MemoryRouter>
        <ErrorBoundary>
          <ThrowingChild shouldThrow={true} />
        </ErrorBoundary>
      </MemoryRouter>,
    );

    // Fallback container is present and not empty
    const fallback = screen.getByTestId('error-boundary-fallback');
    expect(fallback).toBeInTheDocument();
    expect(fallback).not.toBeEmptyDOMElement();

    // Error message is displayed
    const errorMessage = screen.getByTestId('error-message');
    expect(errorMessage).toBeInTheDocument();
    expect(errorMessage.textContent).toBe('Test error from child');

    // Home link is present
    expect(screen.getByTestId('error-home-link')).toBeInTheDocument();

    // Refresh button is present
    expect(screen.getByTestId('error-refresh')).toBeInTheDocument();
  });
});
