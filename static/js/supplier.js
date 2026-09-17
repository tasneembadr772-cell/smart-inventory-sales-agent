/**
 * NexusERP - Modern ES6+ Supplier Dynamic Search & Filtering
 * 
 * Provides client-side instant search debouncing, real-time table filtering,
 * and responsive UI interactions for the supplier directory.
 */

document.addEventListener('DOMContentLoaded', () => {
    initSupplierLiveSearch();
    initSupplierFilterAutoSubmit();
});

/**
 * Debounce helper utility for high-performance input listening.
 * @param {Function} func Function to execute after delay.
 * @param {number} delay Milliseconds to wait.
 */
const debounce = (func, delay = 200) => {
    let timeoutId;
    return (...args) => {
        clearTimeout(timeoutId);
        timeoutId = setTimeout(() => func.apply(null, args), delay);
    };
};

/**
 * Initializes client-side debounced live search on the suppliers table.
 */
function initSupplierLiveSearch() {
    const searchInput = document.getElementById('supplierSearchInput');
    const table = document.getElementById('suppliersTable');
    const noMatchesCard = document.getElementById('noSearchMatches');
    if (!searchInput || !table) return;

    const rows = table.querySelectorAll('tbody tr.supplier-row');
    const emptyRow = table.getElementById('supplierEmptyRow');

    const filterRows = (query) => {
        const cleanQuery = query.toLowerCase().trim();
        let visibleCount = 0;

        rows.forEach(row => {
            const name = row.dataset.name || '';
            const contact = row.dataset.contact || '';
            const email = row.dataset.email || '';
            const phone = row.dataset.phone || '';
            const textContent = row.textContent.toLowerCase();

            const isMatch = cleanQuery === '' ||
                            name.includes(cleanQuery) ||
                            contact.includes(cleanQuery) ||
                            email.includes(cleanQuery) ||
                            phone.includes(cleanQuery) ||
                            textContent.includes(cleanQuery);

            if (isMatch) {
                row.style.display = '';
                visibleCount++;
            } else {
                row.style.display = 'none';
            }
        });

        // Toggle dynamic no-match notification card
        if (noMatchesCard) {
            noMatchesCard.style.display = (visibleCount === 0 && rows.length > 0 && cleanQuery !== '') ? 'block' : 'none';
        }

        // Hide main empty row if rows existed originally
        if (emptyRow && rows.length > 0) {
            emptyRow.style.display = 'none';
        }
    };

    // Debounced input listener
    searchInput.addEventListener('input', debounce((event) => {
        filterRows(event.target.value);
    }, 150));

    // Reset button listener
    const resetBtn = document.getElementById('resetSupplierFilters');
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
 * Automatically submits filter dropdowns when user selects a status option.
 */
function initSupplierFilterAutoSubmit() {
    const statusSelect = document.getElementById('statusFilterSelect');
    const form = document.getElementById('supplierFilterForm');

    if (!form || !statusSelect) return;

    statusSelect.addEventListener('change', () => {
        form.submit();
    });
}
