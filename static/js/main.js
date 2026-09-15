/**
 * Inventory & Sales Management System
 * Frontend Client Script (Modern ES6+)
 */

document.addEventListener('DOMContentLoaded', () => {
    console.log('%c⚡ Inventory & Sales Management System initialized.', 'color: #38bdf8; font-weight: bold; font-size: 14px;');
    console.log('Django MVT Architecture with PostgreSQL integration ready.');

    // Interactive card tilt / hover elevation
    const cards = document.querySelectorAll('.card, .app-card');
    cards.forEach((card) => {
        card.addEventListener('mouseenter', () => {
            card.style.transition = 'transform 0.2s ease, box-shadow 0.2s ease';
        });
    });

    // Smooth navigation anchor scrolling
    const anchorLinks = document.querySelectorAll('a[href^="#"]');
    anchorLinks.forEach(link => {
        link.addEventListener('click', (e) => {
            const targetId = link.getAttribute('href');
            if (targetId && targetId !== '#') {
                const targetElement = document.querySelector(targetId);
                if (targetElement) {
                    e.preventDefault();
                    targetElement.scrollIntoView({
                        behavior: 'smooth',
                        block: 'start'
                    });
                }
            }
        });
    });
});
