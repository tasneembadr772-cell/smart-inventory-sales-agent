/**
 * ==============================================================================
 * Embedded Context-Aware AI Chatbot UI Script (Modern ES6+)
 * NexusERP — Inventory & Sales Management System
 * ==============================================================================
 */

class InventoryChatbot {
    constructor() {
        this.isOpen = false;
        this.isLoading = false;
        this.history = [];
        this.context = null;

        // DOM Elements
        this.launcher = document.getElementById('nexus-chat-launcher');
        this.window = document.getElementById('nexus-chat-window');
        this.messagesContainer = document.getElementById('nexus-chat-messages');
        this.input = document.getElementById('nexus-chat-input');
        this.sendBtn = document.getElementById('nexus-chat-send-btn');
        this.form = document.getElementById('nexus-chat-form');
        this.closeBtn = document.getElementById('nexus-chat-close-btn');
        this.clearBtn = document.getElementById('nexus-chat-clear-btn');
        this.contextBar = document.getElementById('nexus-chat-context-bar');
        this.suggestionsContainer = document.getElementById('nexus-chat-suggestions');
        this.launcherBadge = document.getElementById('nexus-chat-launcher-badge');

        // Endpoints
        this.chatApiUrl = '/ai/api/chat/';
        this.contextApiUrl = '/ai/api/context/';

        this.csrfToken = this.getCsrfToken();
    }

    init() {
        if (!this.launcher || !this.window) {
            return;
        }

        // Event Listeners
        this.launcher.addEventListener('click', () => this.toggleChat());
        if (this.closeBtn) this.closeBtn.addEventListener('click', () => this.toggleChat(false));
        if (this.clearBtn) this.clearBtn.addEventListener('click', () => this.clearChat());

        if (this.form) {
            this.form.addEventListener('submit', (e) => {
                e.preventDefault();
                this.handleSend();
            });
        }

        if (this.input) {
            this.input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    this.handleSend();
                }
            });

            this.input.addEventListener('input', () => this.autoResizeInput());
        }

        // Close on Escape key
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.isOpen) {
                this.toggleChat(false);
            }
        });

        // Fetch Initial Live Application Context
        this.fetchContext();

        // Render Welcome Message
        this.renderWelcome();
    }

    getCsrfToken() {
        // Try Django cookie first
        const match = document.cookie.match(/csrftoken=([^;]+)/);
        if (match) return match[1];

        // Fallback to DOM CSRF input
        const input = document.querySelector('[name=csrfmiddlewaretoken]');
        return input ? input.value : '';
    }

    toggleChat(forceState = null) {
        this.isOpen = forceState !== null ? forceState : !this.isOpen;

        if (this.isOpen) {
            this.window.classList.add('open');
            this.launcher.style.display = 'none';
            if (this.input) {
                setTimeout(() => this.input.focus(), 150);
            }
            this.scrollToBottom();
        } else {
            this.window.classList.remove('open');
            this.launcher.style.display = 'flex';
        }
    }

    async fetchContext() {
        try {
            const resp = await fetch(this.contextApiUrl, {
                headers: {
                    'X-Requested-With': 'XMLHttpRequest',
                }
            });

            if (!resp.ok) return;

            const data = await resp.json();
            if (data.success) {
                this.context = data;
                this.updateContextUI(data);
            }
        } catch (err) {
            console.warn('NexusChatbot: could not fetch live context:', err);
        }
    }

    updateContextUI(data) {
        const inv = data.inventory || {};
        const lowStock = inv.low_stock_count || 0;

        // Update Launcher Badge if low stock alerts exist
        if (this.launcherBadge) {
            if (lowStock > 0) {
                this.launcherBadge.textContent = lowStock;
                this.launcherBadge.style.display = 'inline-block';
            } else {
                this.launcherBadge.style.display = 'none';
            }
        }

        // Update Context Bar inside drawer
        if (this.contextBar) {
            const roleName = (data.user && data.user.role) ? data.user.role : 'User';
            this.contextBar.innerHTML = `
                <span class="nexus-chat-role-pill">${this.escapeHtml(roleName)}</span>
                <div class="nexus-chat-context-kpi">
                    <span class="nexus-chat-context-item">📦 <strong>${inv.total_products || 0}</strong> SKUs</span>
                    ${lowStock > 0 ? `<span class="nexus-chat-context-item" style="color: #dc2626;">⚠️ <strong>${lowStock}</strong> Low</span>` : `<span class="nexus-chat-context-item" style="color: #16a34a;">✅ Stock OK</span>`}
                </div>
            `;
        }

        // Render Quick Suggestion Chips
        if (this.suggestionsContainer && data.suggestions) {
            this.suggestionsContainer.innerHTML = '';
            data.suggestions.forEach((text) => {
                const chip = document.createElement('button');
                chip.type = 'button';
                chip.className = 'nexus-chat-chip';
                chip.textContent = text;
                chip.addEventListener('click', () => {
                    if (this.input) this.input.value = text;
                    this.handleSend();
                });
                this.suggestionsContainer.appendChild(chip);
            });
        }
    }

    renderWelcome() {
        const welcomeText = `👋 Hello! I am your **Nexus Inventory & Sales Assistant**.\n\nI can analyze stock levels, detect inventory shortages, and prepare draft purchase orders. How can I assist you today?`;
        this.appendMessage('assistant', welcomeText);
    }

    autoResizeInput() {
        if (!this.input) return;
        this.input.style.height = 'auto';
        this.input.style.height = Math.min(this.input.scrollHeight, 110) + 'px';
    }

    handleSend() {
        if (this.isLoading || !this.input) return;

        const text = this.input.value.trim();
        if (!text) return;

        this.input.value = '';
        this.autoResizeInput();

        this.sendMessage(text);
    }

    async sendMessage(text, options = {}) {
        if (this.isLoading) return;

        // Add user message to UI and history
        this.appendMessage('user', text);
        this.history.push({ role: 'user', content: text });

        // Set Loading State
        this.setLoading(true);
        this.hideError();

        const payload = {
            message: text,
            history: this.history.slice(-8), // Send last 8 turns for conversational memory
            confirmed_actions: options.confirmed_actions || [],
            auto_confirm: Boolean(options.auto_confirm),
            context: {
                current_page: window.location.pathname,
            }
        };

        try {
            const resp = await fetch(this.chatApiUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.csrfToken || this.getCsrfToken(),
                    'X-Requested-With': 'XMLHttpRequest',
                },
                body: JSON.stringify(payload),
            });

            const data = await resp.json();

            this.setLoading(false);

            if (resp.ok && data.success) {
                // Render Agent Response
                const reply = data.reply || 'Task completed.';
                this.appendMessage('assistant', reply, {
                    steps: data.steps || [],
                    pending_action: data.pending_action || null,
                    status: data.status,
                });
                this.history.push({ role: 'assistant', content: reply });

                // Refresh live context (e.g. if orders were created)
                if (data.tools_executed && data.tools_executed.includes('create_draft_purchase_order')) {
                    this.fetchContext();
                }
            } else if (data.status === 'PENDING_CONFIRMATION' && data.pending_action) {
                // Confirmation State
                const reply = data.reply || 'Action requires confirmation.';
                this.appendMessage('assistant', reply, {
                    steps: data.steps || [],
                    pending_action: data.pending_action,
                    status: data.status,
                });
                this.history.push({ role: 'assistant', content: reply });
            } else {
                // Handled Error State from Server
                const errorMsg = data.error || data.reply || 'An unexpected error occurred while processing your request.';
                this.showError(errorMsg);
                this.appendMessage('assistant', `⚠️ **Error**: ${errorMsg}`);
            }
        } catch (networkErr) {
            this.setLoading(false);
            console.error('NexusChatbot fetch error:', networkErr);
            const errDetail = 'Network communication failure. Please check your connection and try again.';
            this.showError(errDetail);
            this.appendMessage('assistant', `⚠️ **Network Error**: ${errDetail}`);
        }
    }

    setLoading(loading) {
        this.isLoading = loading;

        if (this.sendBtn) {
            this.sendBtn.disabled = loading;
        }
        if (this.input) {
            this.input.disabled = loading;
        }

        // Add or remove animated typing indicator
        const existingLoader = document.getElementById('nexus-chat-typing-indicator');
        if (loading && !existingLoader) {
            const loaderDiv = document.createElement('div');
            loaderDiv.id = 'nexus-chat-typing-indicator';
            loaderDiv.className = 'nexus-chat-loading';
            loaderDiv.innerHTML = `
                <div class="nexus-chat-dots">
                    <span></span><span></span><span></span>
                </div>
                <span class="nexus-chat-loading-text">Nexus Assistant is analyzing inventory...</span>
            `;
            this.messagesContainer.appendChild(loaderDiv);
            this.scrollToBottom();
        } else if (!loading && existingLoader) {
            existingLoader.remove();
            if (this.input) this.input.focus();
        }
    }

    appendMessage(role, text, metadata = {}) {
        if (!this.messagesContainer) return;

        const msgDiv = document.createElement('div');
        msgDiv.className = `nexus-chat-msg ${role}`;

        const bubble = document.createElement('div');
        bubble.className = 'nexus-chat-bubble';
        bubble.innerHTML = this.formatMarkdown(text);

        msgDiv.appendChild(bubble);

        // Render Tool Steps Card if present
        if (metadata.steps && metadata.steps.length > 0) {
            const stepsWrapper = this.renderStructuredSteps(metadata.steps);
            msgDiv.appendChild(stepsWrapper);
        }

        // Render Sensitive Action Confirmation Card if present
        if (metadata.pending_action) {
            const confirmCard = this.renderConfirmationCard(metadata.pending_action);
            msgDiv.appendChild(confirmCard);
        }

        // Timestamp
        const timeSpan = document.createElement('span');
        timeSpan.className = 'nexus-chat-msg-time';
        timeSpan.textContent = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        msgDiv.appendChild(timeSpan);

        this.messagesContainer.appendChild(msgDiv);
        this.scrollToBottom();
    }

    renderStructuredSteps(steps) {
        const container = document.createElement('div');
        container.style.marginTop = '6px';

        steps.forEach((step) => {
            const card = document.createElement('div');
            card.className = 'nexus-chat-action-card';

            const statusClass = step.status === 'SUCCESS' ? 'success' : (step.status === 'PENDING_CONFIRMATION' ? 'pending' : 'failure');

            card.innerHTML = `
                <div class="nexus-chat-action-header">
                    <span class="nexus-chat-action-title">
                        <span>⚡</span>
                        <code>${this.escapeHtml(step.tool || 'Action')}</code>
                    </span>
                    <span class="nexus-chat-badge-status ${statusClass}">${this.escapeHtml(step.status || 'DONE')}</span>
                </div>
                ${step.thought ? `<div style="font-size: 0.74rem; color: #64748b; font-style: italic; margin-bottom: 4px;">"${this.escapeHtml(step.thought)}"</div>` : ''}
                <details>
                    <summary style="cursor: pointer; color: #4f46e5; font-size: 0.72rem; font-weight: 500;">View execution data</summary>
                    <div class="nexus-chat-action-details">
                        <div><strong>Parameters:</strong> ${this.escapeHtml(JSON.stringify(step.args))}</div>
                        <div style="margin-top: 4px;"><strong>Result:</strong> ${this.escapeHtml(JSON.stringify(step.result))}</div>
                    </div>
                </details>
            `;
            container.appendChild(card);
        });

        return container;
    }

    renderConfirmationCard(pendingAction) {
        const card = document.createElement('div');
        card.className = 'nexus-chat-confirm-card';

        const summaryText = pendingAction.summary || `Execute ${pendingAction.tool_name} with provided parameters.`;

        card.innerHTML = `
            <div class="nexus-chat-confirm-title">
                <span>⚠️</span> Approval Required: ${this.escapeHtml(pendingAction.tool_name)}
            </div>
            <div class="nexus-chat-confirm-desc">
                ${this.escapeHtml(summaryText)}
            </div>
            <div class="nexus-chat-confirm-actions">
                <button type="button" class="nexus-chat-btn-approve">Approve & Execute</button>
                <button type="button" class="nexus-chat-btn-cancel">Cancel</button>
            </div>
        `;

        const approveBtn = card.querySelector('.nexus-chat-btn-approve');
        const cancelBtn = card.querySelector('.nexus-chat-btn-cancel');

        approveBtn.addEventListener('click', () => {
            approveBtn.disabled = true;
            approveBtn.textContent = 'Executing...';
            // Send follow-up confirmation request
            this.sendMessage(`Confirm execution of ${pendingAction.tool_name}`, {
                confirmed_actions: [pendingAction.tool_name],
                auto_confirm: true,
            });
            card.remove();
        });

        cancelBtn.addEventListener('click', () => {
            card.innerHTML = `<span style="color: #64748b; font-size: 0.76rem; font-style: italic;">Action cancelled by user.</span>`;
        });

        return card;
    }

    showError(message) {
        let errDiv = document.getElementById('nexus-chat-error-banner');
        if (!errDiv) {
            errDiv = document.createElement('div');
            errDiv.id = 'nexus-chat-error-banner';
            errDiv.className = 'nexus-chat-error';
            this.messagesContainer.appendChild(errDiv);
        }

        errDiv.innerHTML = `
            <span>⚠️ ${this.escapeHtml(message)}</span>
            <button type="button" style="background: transparent; border: none; color: inherit; cursor: pointer; font-size: 0.9rem;" onclick="this.parentElement.remove()">✕</button>
        `;
        this.scrollToBottom();
    }

    hideError() {
        const errDiv = document.getElementById('nexus-chat-error-banner');
        if (errDiv) errDiv.remove();
    }

    clearChat() {
        if (!this.messagesContainer) return;
        this.messagesContainer.innerHTML = '';
        this.history = [];
        this.hideError();
        this.renderWelcome();
    }

    scrollToBottom() {
        if (!this.messagesContainer) return;
        setTimeout(() => {
            this.messagesContainer.scrollTop = this.messagesContainer.scrollHeight;
        }, 50);
    }

    escapeHtml(str) {
        if (typeof str !== 'string') str = String(str || '');
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    formatMarkdown(text) {
        if (!text) return '';
        let escaped = this.escapeHtml(text);

        // Convert bold: **text**
        escaped = escaped.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');

        // Convert inline code: `code`
        escaped = escaped.replace(/`([^`]+)`/g, '<code>$1</code>');

        // Convert line breaks to paragraphs/br
        const lines = escaped.split('\n');
        let html = '';
        let inList = false;

        lines.forEach((line) => {
            const trimmed = line.trim();
            if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) {
                if (!inList) {
                    html += '<ul style="margin: 4px 0 8px 18px; padding: 0;">';
                    inList = true;
                }
                html += `<li>${trimmed.substring(2)}</li>`;
            } else {
                if (inList) {
                    html += '</ul>';
                    inList = false;
                }
                if (trimmed) {
                    html += `<p>${trimmed}</p>`;
                }
            }
        });

        if (inList) html += '</ul>';

        return html;
    }
}

// Auto-initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.inventoryChatbot = new InventoryChatbot();
    window.inventoryChatbot.init();
});
