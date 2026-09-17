/**
 * NexusERP - Modern ES6+ Inventory Dynamic Search, Filtering & Stock Adjustments
 * 
 * Provides client-side instant search debouncing, real-time table filtering,
 * responsive modal workflows, and AJAX-driven stock adjustments.
 */

document.addEventListener('DOMContentLoaded', () => {
    initProductLiveSearch();
    initFilterAutoSubmit();
    initAlertDismissal();
    initStockAdjustmentModal();
    initLowStockLiveSearch();
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
 * Helper to display temporary alert messages dynamically.
 */
function showDynamicAlert(message, type = 'success') {
    let container = document.querySelector('.messages-container');
    if (!container) {
        container = document.createElement('div');
        container.className = 'messages-container';
        const header = document.querySelector('.site-header');
        if (header) {
            header.insertAdjacentElement('afterend', container);
        } else {
            document.body.prepend(container);
        }
    }

    const alertEl = document.createElement('div');
    alertEl.className = `alert alert-${type}`;
    alertEl.innerHTML = `
        <span class="alert-icon">${type === 'success' ? '✅' : '⚠️'}</span>
        <span class="alert-text">${message}</span>
    `;
    container.appendChild(alertEl);

    setTimeout(() => {
        alertEl.style.transition = 'opacity 0.5s ease, transform 0.5s ease';
        alertEl.style.opacity = '0';
        alertEl.style.transform = 'translateY(-10px)';
        setTimeout(() => alertEl.remove(), 500);
    }, 5000);
}

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
        resetBtn.addEventListener('click', () => {
            if (searchInput.value) {
                searchInput.value = '';
                filterRows('');
            }
        });
    }
}

/**
 * Initializes client-side debounced live search on the low-stock queue table.
 */
function initLowStockLiveSearch() {
    const searchInput = document.getElementById('lowStockSearchInput');
    const table = document.getElementById('lowStockTable');
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

        if (emptyRow) {
            emptyRow.style.display = (visibleCount === 0 && rows.length > 0) ? '' : 'none';
        }
    };

    searchInput.addEventListener('input', debounce((event) => {
        filterRows(event.target.value);
    }, 200));
}

/**
 * Automatically submits filter dropdowns when user selects an option.
 */
function initFilterAutoSubmit() {
    const autoSubmitSelects = [
        'categoryFilterSelect',
        'stockFilterSelect',
        'statusFilterSelect',
        'lowStockCatSelect',
        'lowStockSuppSelect',
        'txTypeFilterSelect',
    ];

    autoSubmitSelects.forEach(id => {
        const selectEl = document.getElementById(id);
        if (selectEl && selectEl.form) {
            selectEl.addEventListener('change', () => selectEl.form.submit());
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

/**
 * ES6+ Stock Adjustment Modal Handler (AJAX & Real-time DOM updates).
 */
function initStockAdjustmentModal() {
    const modal = document.getElementById('stockAdjustmentModal');
    const form = document.getElementById('stockAdjustmentForm');
    if (!modal || !form) return;

    const modalProductName = document.getElementById('modalProductName');
    const modalProductSku = document.getElementById('modalProductSku');
    const modalCurrentStock = document.getElementById('modalCurrentStock');
    const modalReorderLevel = document.getElementById('modalReorderLevel');
    const typeSelect = document.getElementById('stockAdjustmentType');
    const qtyInput = document.getElementById('stockAdjustmentQuantity');
    const qtyLabel = document.getElementById('qtyFieldLabel');
    const qtyHelp = document.getElementById('qtyFieldHelp');
    const formErrors = document.getElementById('modalFormErrors');
    const submitBtn = document.getElementById('btnSubmitStockAdjust');

    let currentProductId = null;
    let currentStockValue = 0;

    // Open modal on click of any .btn-adjust-stock button
    document.addEventListener('click', (e) => {
        const btn = e.target.closest('.btn-adjust-stock');
        if (!btn) return;

        currentProductId = btn.dataset.productId;
        const productName = btn.dataset.productName || 'Product SKU';
        const productSku = btn.dataset.productSku || '';
        currentStockValue = parseInt(btn.dataset.stock, 10) || 0;
        const reorderLevel = btn.dataset.reorder || '10';

        if (modalProductName) modalProductName.textContent = productName;
        if (modalProductSku) modalProductSku.textContent = productSku;
        if (modalCurrentStock) modalCurrentStock.textContent = currentStockValue;
        if (modalReorderLevel) modalReorderLevel.textContent = reorderLevel;

        form.action = `/domain/products/${currentProductId}/stock-adjustment/`;
        form.reset();
        if (formErrors) formErrors.style.display = 'none';

        // Reset operation type labels
        updateTypeLabels('ADD');

        modal.style.display = 'flex';
        qtyInput.focus();
    });

    const closeModal = () => {
        modal.style.display = 'none';
        if (formErrors) formErrors.style.display = 'none';
        form.reset();
    };

    const closeBtn = document.getElementById('btnCloseAdjustModal');
    const cancelBtn = document.getElementById('btnCancelAdjustModal');
    if (closeBtn) closeBtn.addEventListener('click', closeModal);
    if (cancelBtn) cancelBtn.addEventListener('click', closeModal);

    modal.addEventListener('click', (e) => {
        if (e.target === modal) closeModal();
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && modal.style.display === 'flex') {
            closeModal();
        }
    });

    // Dynamic field labels based on transaction type
    const updateTypeLabels = (type) => {
        if (type === 'ADD') {
            if (qtyLabel) qtyLabel.innerHTML = 'Units to Add <span class="required-star">*</span>';
            if (qtyInput) {
                qtyInput.placeholder = 'Enter units to add (e.g. 20)';
                qtyInput.min = '1';
            }
            if (qtyHelp) qtyHelp.textContent = 'Units added to physical warehouse stock.';
        } else if (type === 'REMOVE') {
            if (qtyLabel) qtyLabel.innerHTML = 'Units to Remove <span class="required-star">*</span>';
            if (qtyInput) {
                qtyInput.placeholder = `Max ${currentStockValue} units`;
                qtyInput.min = '1';
                qtyInput.max = currentStockValue.toString();
            }
            if (qtyHelp) qtyHelp.textContent = `Units dispatched or scrapped. Cannot exceed ${currentStockValue}.`;
        } else if (type === 'ADJUSTMENT') {
            if (qtyLabel) qtyLabel.innerHTML = 'New Total Stock Count <span class="required-star">*</span>';
            if (qtyInput) {
                qtyInput.placeholder = 'Enter verified physical count (e.g. 45)';
                qtyInput.min = '0';
                qtyInput.removeAttribute('max');
            }
            if (qtyHelp) qtyHelp.textContent = 'Calibrated physical count verified by warehouse audit.';
        }
    };

    if (typeSelect) {
        typeSelect.addEventListener('change', (e) => updateTypeLabels(e.target.value));
    }

    // AJAX Form submission
    form.addEventListener('submit', async (e) => {
        e.preventDefault();

        if (formErrors) formErrors.style.display = 'none';
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.textContent = 'Processing...';
        }

        const formData = new FormData(form);

        try {
            const response = await fetch(form.action, {
                method: 'POST',
                headers: {
                    'X-Requested-With': 'XMLHttpRequest',
                    'Accept': 'application/json',
                },
                body: formData,
            });

            const data = await response.json();

            if (response.ok && data.success) {
                closeModal();
                showDynamicAlert(data.message, 'success');

                // Real-time update of matching table row
                const productRow = document.getElementById(`product-row-${data.product_id}`);
                if (productRow) {
                    const qtyDisplay = productRow.querySelector('.stock-qty-display');
                    if (qtyDisplay) {
                        qtyDisplay.textContent = data.new_stock;
                        qtyDisplay.className = `stock-qty-display font-bold ${
                            data.new_stock === 0 ? 'text-danger' : (data.is_low_stock ? 'text-warning' : 'text-success')
                        }`;
                    }

                    const statusCell = productRow.querySelector('.stock-status-cell');
                    if (statusCell) {
                        if (data.stock_status === 'out_of_stock') {
                            statusCell.innerHTML = '<span class="badge badge-danger">Out of Stock</span>';
                        } else if (data.stock_status === 'low_stock') {
                            statusCell.innerHTML = `<span class="badge badge-warning">Low Stock (≤${data.reorder_level})</span>`;
                        } else {
                            statusCell.innerHTML = '<span class="badge badge-success">In Stock</span>';
                        }
                    }

                    // Update dataset stock on button
                    const adjustBtn = productRow.querySelector('.btn-adjust-stock');
                    if (adjustBtn) {
                        adjustBtn.dataset.stock = data.new_stock;
                    }
                }

                // Update low stock queue row if present
                const lowStockRow = document.getElementById(`low-stock-row-${data.product_id}`);
                if (lowStockRow) {
                    if (data.stock_status === 'in_stock') {
                        lowStockRow.style.transition = 'opacity 0.4s ease';
                        lowStockRow.style.opacity = '0.3';
                    } else {
                        const qtySpan = lowStockRow.querySelector('.stock-qty');
                        if (qtySpan) qtySpan.textContent = data.new_stock;
                    }
                }

                // Update system KPI summary counters if provided
                if (data.kpis) {
                    const kpiUnits = document.getElementById('kpiTotalUnits');
                    const kpiLow = document.getElementById('kpiLowStockCount');
                    const kpiOut = document.getElementById('kpiOutOfStockCount');

                    if (kpiUnits) kpiUnits.textContent = data.kpis.total_units;
                    if (kpiLow) kpiLow.textContent = data.kpis.low_stock_count;
                    if (kpiOut) kpiOut.textContent = data.kpis.out_of_stock_count;
                }

                // If on product detail page, refresh after a brief delay so transaction ledger renders
                if (window.location.pathname.includes(`/products/${data.product_id}/`)) {
                    setTimeout(() => window.location.reload(), 700);
                }

            } else {
                // Show errors in modal
                const errorMsg = data.message || 'Validation failed. Please check inputs.';
                if (formErrors) {
                    formErrors.textContent = errorMsg;
                    formErrors.style.display = 'block';
                }
            }
        } catch (err) {
            if (formErrors) {
                formErrors.textContent = 'A network error occurred while communicating with the server.';
                formErrors.style.display = 'block';
            }
        } finally {
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.textContent = 'Confirm Stock Update';
            }
        }
    });
}
