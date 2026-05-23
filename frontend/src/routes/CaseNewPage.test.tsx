import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import CaseNewPage from './CaseNewPage';
import { Layout } from '@/components/Layout';

function renderPage() {
  return render(
    <MemoryRouter>
      <CaseNewPage />
    </MemoryRouter>,
  );
}

function renderLayout() {
  return render(
    <MemoryRouter>
      <Layout />
    </MemoryRouter>,
  );
}

describe('CaseNewPage — data-testid completeness (§6.4 R6)', () => {
  it('renders all required data-testid elements', () => {
    renderPage();

    // Tab buttons
    expect(screen.getByTestId('tab-entry-a')).toBeInTheDocument();
    expect(screen.getByTestId('tab-entry-b')).toBeInTheDocument();

    // Tab A content visible by default
    expect(screen.getByTestId('textarea-entry-a')).toBeInTheDocument();
    expect(screen.getByTestId('btn-generate-stub')).toBeInTheDocument();

    // Main YAML editor always visible
    expect(screen.getByTestId('textarea-yaml-editor')).toBeInTheDocument();

    // Action buttons
    expect(screen.getByTestId('btn-validate')).toBeInTheDocument();
    expect(screen.getByTestId('btn-try')).toBeInTheDocument();
    expect(screen.getByTestId('btn-save')).toBeInTheDocument();

    // Step results panel
    expect(screen.getByTestId('panel-step-results')).toBeInTheDocument();
  });
});

describe('CaseNewPage — tab switching', () => {
  it('shows tab-A content and hides tab-B content on initial render', () => {
    renderPage();

    expect(screen.getByTestId('textarea-entry-a')).toBeInTheDocument();
    expect(screen.queryByTestId('textarea-entry-b')).not.toBeInTheDocument();
  });

  it('clicking tab-entry-b shows textarea-entry-b and hides textarea-entry-a', () => {
    renderPage();

    fireEvent.click(screen.getByTestId('tab-entry-b'));

    expect(screen.getByTestId('textarea-entry-b')).toBeInTheDocument();
    expect(screen.queryByTestId('textarea-entry-a')).not.toBeInTheDocument();
    expect(screen.queryByTestId('btn-generate-stub')).not.toBeInTheDocument();
  });

  it('clicking tab-entry-a after tab-b switches back', () => {
    renderPage();

    fireEvent.click(screen.getByTestId('tab-entry-b'));
    fireEvent.click(screen.getByTestId('tab-entry-a'));

    expect(screen.getByTestId('textarea-entry-a')).toBeInTheDocument();
    expect(screen.queryByTestId('textarea-entry-b')).not.toBeInTheDocument();
  });
});

describe('CaseNewPage — tab-B mirrors into YAML editor', () => {
  it('typing in textarea-entry-b mirrors value into textarea-yaml-editor', () => {
    renderPage();

    fireEvent.click(screen.getByTestId('tab-entry-b'));

    const entryB = screen.getByTestId('textarea-entry-b') as HTMLTextAreaElement;
    const yamlEditor = screen.getByTestId('textarea-yaml-editor') as HTMLTextAreaElement;

    fireEvent.change(entryB, { target: { value: 'id: test-001\nsteps: []' } });

    expect(entryB.value).toBe('id: test-001\nsteps: []');
    expect(yamlEditor.value).toBe('id: test-001\nsteps: []');
  });

  it('typing in textarea-entry-a does NOT change textarea-yaml-editor', () => {
    renderPage();

    const entryA = screen.getByTestId('textarea-entry-a') as HTMLTextAreaElement;
    const yamlEditor = screen.getByTestId('textarea-yaml-editor') as HTMLTextAreaElement;

    fireEvent.change(entryA, { target: { value: 'some description' } });

    expect(entryA.value).toBe('some description');
    expect(yamlEditor.value).toBe('');
  });
});

describe('CaseNewPage — button disabled states', () => {
  it('btn-try is initially disabled', () => {
    renderPage();
    const btn = screen.getByTestId('btn-try') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it('btn-save is initially disabled', () => {
    renderPage();
    const btn = screen.getByTestId('btn-save') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it('btn-validate is initially enabled', () => {
    renderPage();
    const btn = screen.getByTestId('btn-validate') as HTMLButtonElement;
    expect(btn.disabled).toBe(false);
  });

  it('btn-generate-stub is disabled', () => {
    renderPage();
    const btn = screen.getByTestId('btn-generate-stub') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });
});

describe('Layout — nav-cases-new link', () => {
  it('renders nav-cases-new link pointing to /cases/new', () => {
    renderLayout();

    const link = screen.getByTestId('nav-cases-new');
    expect(link).toBeInTheDocument();
    expect(link.getAttribute('href')).toBe('/cases/new');
  });
});
