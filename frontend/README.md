# Frontend MVP

Vite + React 18 + TypeScript strict skeleton for Lightning Bug Regression.

## Dev

```bash
npm install && npm run dev
```

Starts dev server on http://localhost:5173 (proxies `/api` to backend on :8000).

## Tests

```bash
npm test
```

## Lint

```bash
npm run lint
```

## E2E

Playwright config is bootstrapped. A placeholder smoke test lives in `e2e/smoke.spec.ts`.
Real E2E suite arrives in M2-9.

```bash
npx playwright test
```
