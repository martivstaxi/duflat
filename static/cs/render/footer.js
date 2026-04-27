import { els } from '../dom.js?v=36';

export function renderFooter() {
    // Steady-state footer is intentionally blank; only transient states
    // (background scan indicator, manual poll completion/error) populate it.
    els.footer.textContent = '';
}
