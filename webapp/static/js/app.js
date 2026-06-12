/* ── Pulse — shared JS utilities ── */

/**
 * Escape HTML entities to prevent XSS when inserting dynamic text.
 */
function escapeHtml(str) {
    if (!str) return '';
    const el = document.createElement('span');
    el.textContent = str;
    return el.innerHTML;
}

/**
 * Standard Plotly layout matching the light theme.
 */
function chartLayout(title) {
    return {
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor:  'rgba(0,0,0,0)',
        font:  { color: '#6b7280', family: 'Inter', size: 11 },
        margin:{ l: 14, r: 14, t: 56, b: 14 },
        xaxis: { gridcolor: 'rgba(0,79,159,0.06)', showgrid: true, zeroline: false,
                 linecolor: 'rgba(0,79,159,0.08)', tickfont: { color: '#6b7280', size: 10 } },
        yaxis: { gridcolor: 'rgba(0,79,159,0.06)', showgrid: true, zeroline: false,
                 linecolor: 'rgba(0,79,159,0.08)', tickfont: { color: '#6b7280', size: 10 } },
        title: { text: title || '', x: 0.01, xanchor: 'left', y: 0.98, yanchor: 'top',
                 font: { color: '#111827', size: 13, family: 'Inter' } },
        legend: { bgcolor: 'rgba(0,0,0,0)', font: { color: '#6b7280', size: 10 },
                  orientation: 'h', yanchor: 'bottom', y: 1.08, xanchor: 'right', x: 1 },
    };
}

/**
 * Toast notification system
 */
function showToast(message, type) {
    type = type || 'info';
    const container = document.getElementById('toastContainer');
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = 'toast toast-' + type;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(20px)';
        toast.style.transition = 'all 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, 3500);
}

/**
 * Smooth navigation with brief fade transition for sidebar links
 */
document.addEventListener('DOMContentLoaded', () => {
    // Update sidebar footer with timestamp
    const footer = document.getElementById('sidebarFooter');
    if (footer) {
        const now = new Date();
        const fmt = now.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
                    + ' ' + now.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
        footer.textContent = fmt;
    }

    // Smooth page transitions for nav items
    document.querySelectorAll('.nav-item').forEach(link => {
        link.addEventListener('click', (e) => {
            if (link.classList.contains('active')) return;
            e.preventDefault();
            const main = document.querySelector('.main-content');
            main.style.opacity = '0';
            main.style.transition = 'opacity 0.15s ease';
            setTimeout(() => { window.location.href = link.href; }, 150);
        });
    });
});
