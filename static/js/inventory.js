/**
 * NexusERP - Modern ES6+ Inventory Dynamic Search & Filtering
 * 
 * Provides client-side instant search debouncing, real-time table filtering,
 * and responsive UI interactions for the inventory products catalog.
 */

document.addEventListener('DOMContentLoaded', () => {
    initProductLiveSearch();
    initFilterAutoSubmit();
    initAlertDismissal();
});

/**
 * Debounce helper utility for high-performance input listening.
 */
const debounce = (func, delay = 250) => {
    let timeoutId;
    return (...args) => {
        clearTimeout(timeoutId);
        timeoutId = setTimeout(() => func.apply(null, args), delay);
    };
};

/**
 * Initializes client-side debounced live search on the products table.
 */
function initProductLiveSearch() {
    const searchInput = document.getElementById('productSearchInput');
    const table = document.getElementById('productsTable');
    if (!searchInput || !table) return;

    const rows = table.querySelectorAll('tbody tr.product-row');
    const emptyRow = table.querySelector('tbody tr.empty-row');

    const filterRows = (query) => {
        const cleanQuery = query.toLowerCase().trim();
        let visibleCount = 0;

        rows.forEach(row => {
            const name = row.dataset.name || '';
            const sku = row.dataset.sku || '';
            const textContent = row.textContent.toLowerCase();

            const isMatch = cleanQuery === '' || 
                            name.includes(cleanQuery) || 
                            sku.includes(cleanQuery) || 
                            textContent.includes(cleanQuery);

            if (isMatch) {
                row.style.display = '';
                visibleCount++;
            } else {
                row.style.display = 'none';
            }
        });

        // Toggle dynamic empty state if all rows are hidden
        if (emptyRow) {
            emptyRow.style.display = (visibleCount === 0 && rows.length > 0) ? '' : 'none';
        }
    };

    // Debounced listener on keystrokes
    searchInput.addEventListener('input', debounce((event) => {
        filterRows(event.target.value);
    }, 200));

    // Reset button listener
    const resetBtn = document.getElementById('resetFilters');
    if (resetBtn) {
        resetBtn.addEventListener('click', (e) => {
            if (searchInput.value) {
                searchInput.value = '';
                filterRows('');
            }
        });
    }
}

/**
 * Automatically submits filter dropdowns when user selects an option.
 */
function initFilterAutoSubmit() {
    const categorySelect = document.getElementById('categoryFilterSelect');
    const stockSelect = document.getElementById('stockFilterSelect');
    const statusSelect = document.getElementById('statusFilterSelect');
    const form = document.getElementById('productFilterForm');

    if (!form) return;

    const autoSubmit = () => form.submit();

    [categorySelect, stockSelect, statusSelect].forEach(selectEl => {
        if (selectEl) {
            selectEl.addEventListener('change', autoSubmit);
        }
    });
}

/**
 * Automatically dismisses flash alert messages after 6 seconds.
 */
function initAlertDismissal() {
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach(alertEl => {
        setTimeout(() => {
            alertEl.style.transition = 'opacity 0.5s ease, transform 0.5s ease';
            alertEl.style.opacity = '0';
            alertEl.style.transform = 'translateY(-10px)';
            setTimeout(() => alertEl.remove(), 500);
        }, 6000);
    });
}
