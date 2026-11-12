import { vi } from 'vitest';

/** React Flow를 jsdom에서 렌더링하기 위한 최소 브라우저 API 대체. */
export function installFlowDomMocks() {
  class ResizeObserverMock {
    private callback: ResizeObserverCallback;
    constructor(callback: ResizeObserverCallback) { this.callback = callback; }
    observe(target: Element) { this.callback([{ target } as ResizeObserverEntry], this as unknown as ResizeObserver); }
    unobserve() {}
    disconnect() {}
  }
  class DOMMatrixReadOnlyMock {
    m22: number;
    constructor(transform?: string) { const scale = transform?.match(/scale\(([1-9.]+)\)/)?.[1]; this.m22 = scale !== undefined ? Number(scale) : 1; }
  }
  vi.stubGlobal('ResizeObserver', ResizeObserverMock);
  vi.stubGlobal('DOMMatrixReadOnly', DOMMatrixReadOnlyMock);
  Object.defineProperties(HTMLElement.prototype, {
    offsetHeight: { configurable: true, get(this: HTMLElement) { return parseFloat(this.style.height) || 1; } },
    offsetWidth: { configurable: true, get(this: HTMLElement) { return parseFloat(this.style.width) || 1; } },
  });
  (SVGElement.prototype as unknown as { getBBox: () => DOMRect }).getBBox = () => ({ x: 0, y: 0, width: 0, height: 0 } as DOMRect);
}

export function memoryStorage() {
  const store = new Map<string, string>();
  vi.stubGlobal('localStorage', { getItem: (key: string) => store.get(key) ?? null, setItem: (key: string, value: string) => store.set(key, String(value)), removeItem: (key: string) => store.delete(key), clear: () => store.clear(), key: (index: number) => [...store.keys()][index] ?? null, get length() { return store.size; } });
  return store;
}
