/**
 * ==============================================================================
 * Agent Chat Response Renderer & Toast Governance Module
 * NexusERP — Autonomous AI Inventory & Procurement Agent
 * ==============================================================================
 * 
 * Provides:
 * 1. Specialized visual rendering for Purchase Order creation outcomes & proposals.
 * 2. Quick-action navigation links to inspect newly generated Draft POs.
 * 3. Non-blocking floating toast notifications for RBAC authorization denials.
 */

class AgentChatRenderer {
    constructor() {
        this.toastContainer = null;
        this.ensureToastContainer();
    }

    /**
     * Ensures the global toast container element exists in the DOM.
     */
    ensureToastContainer() {
        if (typeof document === 'undefined') return;
        let container = document.getElementById('nexus-toast-container');
        if (!container) {
            container = document.createElement('div');
            container.id = 'nexus-toast-container';
            container.className = 'nexus-toast-container';
            container.setAttribute('aria-live', 'polite');
            document.body.appendChild(container);
        }
        this.toastContainer = container;
    }

    /**
     * Renders a non-blocking, auto-fading toast notification.
     * 
     * @param {string} message - Toast message text
     * @param {'error'|'warning'|'success'|'info'} type - Toast category
     * @param {number} duration - Milliseconds before auto-dismiss (default: 5000)
     */
    showToast(message, type = 'error', duration = 5000) {
        this.ensureToastContainer();
        if (!this.toastContainer) return;

        const toast = document.createElement('div');
        toast.className = `nexus-toast nexus-toast-${type}`;

        const icon = type === 'error' ? '🚫' : (type === 'warning' ? '⚠️' : (type === 'success' ? '✅' : 'ℹ️'));

        toast.innerHTML = `
            <div class="nexus-toast-content">
                <span class="nexus-toast-icon">${icon}</span>
                <span class="nexus-toast-msg">${this.escapeHtml(message)}</span>
            </div>
            <button type="button" class="nexus-toast-close" aria-label="Dismiss notification">&times;</button>
        `;

        const closeBtn = toast.querySelector('.nexus-toast-close');
        const dismiss = () => {
            toast.classList.add('nexus-toast-hiding');
            setTimeout(() => toast.remove(), 250);
        };

        if (closeBtn) closeBtn.addEventListener('click', dismiss);

        this.toastContainer.appendChild(toast);

        // Auto-dismiss
        if (duration > 0) {
            setTimeout(dismiss, duration);
        }
    }

    /**
     * Renders a distinct visual card for a created or returned Draft Purchase Order.
     * 
     * @param {Object} poData - Data dictionary returned by create_draft_purchase_order
     * @returns {HTMLElement} The card element
     */
    renderPurchaseOrderCard(poData) {
        const card = document.createElement('div');
        card.className = 'nexus-chat-po-card';

        const poNumber = poData.order_number || `PO-#${poData.purchase_order_id || 'DRAFT'}`;
        const supplierName = poData.supplier_name || 'Vendor';
        const poId = poData.purchase_order_id;
        const totalAmount = poData.total_amount ? `$${parseFloat(poData.total_amount).toFixed(2)}` : '$0.00';
        const items = poData.items || [];

        let itemsHtml = '';
        if (items.length > 0) {
            itemsHtml = `
                <div class="nexus-po-items-table-wrapper">
                    <table class="nexus-po-items-table">
                        <thead>
                            <tr>
                                <th>Product SKU</th>
                                <th style="text-align: right;">Qty</th>
                                <th style="text-align: right;">Cost</th>
                                <th style="text-align: right;">Subtotal</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${items.map(item => `
                                <tr>
                                    <td>
                                        <div class="nexus-po-item-name">${this.escapeHtml(item.product_name || 'Product')}</div>
                                        <div class="nexus-po-item-sku">${this.escapeHtml(item.sku || '')}</div>
                                    </td>
                                    <td style="text-align: right; font-weight: 600;">${item.quantity}</td>
                                    <td style="text-align: right;">$${parseFloat(item.unit_cost || 0).toFixed(2)}</td>
                                    <td style="text-align: right; font-weight: 600;">$${parseFloat(item.subtotal || 0).toFixed(2)}</td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>
            `;
        }

        const poUrl = poId ? `/domain/purchase-orders/${poId}/` : '/domain/purchase-orders/';

        card.innerHTML = `
            <div class="nexus-po-card-header">
                <div class="nexus-po-card-title">
                    <span class="nexus-po-icon">📋</span>
                    <div>
                        <span class="nexus-po-badge-num">${this.escapeHtml(poNumber)}</span>
                        <span class="nexus-po-badge-status">DRAFT</span>
                    </div>
                </div>
                <div class="nexus-po-total-tag">${totalAmount}</div>
            </div>

            <div class="nexus-po-supplier-row">
                <span class="nexus-po-supplier-label">🏢 Supplier:</span>
                <span class="nexus-po-supplier-value">${this.escapeHtml(supplierName)}</span>
            </div>

            ${itemsHtml}

            <div class="nexus-po-card-footer">
                <div class="nexus-po-total-row">
                    <span>Estimated Total Cost:</span>
                    <strong class="nexus-po-total-highlight">${totalAmount}</strong>
                </div>
                <a href="${poUrl}" class="nexus-btn-po-link" target="_blank" rel="noopener">
                    <span>📄 View Purchase Order</span>
                    <span class="nexus-po-arrow">&rarr;</span>
                </a>
            </div>
        `;

        return card;
    }

    /**
     * Inspects tool execution steps and renders visual cards and toasts accordingly.
     * 
     * @param {Array} steps - Execution steps array from the agent response
     * @param {HTMLElement} targetContainer - Container to append visual cards to
     */
    processSteps(steps, targetContainer) {
        if (!Array.isArray(steps) || !targetContainer) return;

        steps.forEach((step) => {
            // Check for RBAC Denial
            if (step.status === 'DENIED' || (step.result && step.result.error && step.result.error.code === 'PERMISSION_DENIED')) {
                const detail = (step.result && step.result.error && step.result.error.detail) ||
                               'Permission denied: Only Managers and Admins can create draft purchase orders.';
                this.showToast(detail, 'error', 6000);
            }

            // Check for successful Draft Purchase Order Creation
            if (step.tool === 'create_draft_purchase_order' && step.status === 'SUCCESS' && step.result && step.result.data) {
                const poCard = this.renderPurchaseOrderCard(step.result.data);
                targetContainer.appendChild(poCard);
            }
        });
    }

    escapeHtml(str) {
        if (str === null || str === undefined) return '';
        const div = document.createElement('div');
        div.textContent = String(str);
        return div.innerHTML;
    }
}

// Global singleton instance
window.agentChatRenderer = new AgentChatRenderer();
