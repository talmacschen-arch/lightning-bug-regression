import '@testing-library/jest-dom';

// jsdom gaps that cmdk (used by CaseIdCombobox) hits at runtime —
// polyfill so render() doesn't crash. Both no-op are fine because the
// tests don't rely on scroll positioning or resize callbacks.
if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}
if (typeof Element !== 'undefined' && !Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = function () {};
}
