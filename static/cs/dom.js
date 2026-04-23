// Shared DOM refs. Safe to read at module-evaluation time because
// `<script type="module">` is deferred — DOM is parsed before any module runs.

export const els = {
    ratingBtns:    document.getElementById('ratingBtns'),
    filterAnchor:  document.getElementById('filterDropdownAnchor'),
    activeChips:   document.getElementById('activeChips'),
    content:       document.getElementById('content'),
    footer:        document.getElementById('footerInfo'),
    subLine:       document.getElementById('subLine'),
    archive:       document.getElementById('archiveSection'),
    archiveDates:  document.getElementById('archiveDates'),
};
