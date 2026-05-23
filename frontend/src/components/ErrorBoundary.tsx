import { Component, ReactNode } from 'react';
import { Link } from 'react-router-dom';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo): void {
    console.error('ErrorBoundary caught:', error, info);
  }

  render(): ReactNode {
    if (this.state.hasError) {
      return (
        <div data-testid="error-boundary-fallback" style={{ padding: '2rem', fontFamily: 'sans-serif' }}>
          <h1>出错了 (App rendering error)</h1>
          <pre data-testid="error-message">{this.state.error?.message ?? 'unknown'}</pre>
          <nav>
            <Link to="/" data-testid="error-home-link">返回首页</Link>
            {' '}
            <button
              data-testid="error-refresh"
              onClick={() => window.location.reload()}
            >
              刷新
            </button>
          </nav>
        </div>
      );
    }

    return this.props.children;
  }
}
