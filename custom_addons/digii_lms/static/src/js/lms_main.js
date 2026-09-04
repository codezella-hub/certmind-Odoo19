(function () {
    'use strict';

    function initMenu() {
        const menuToggle = document.getElementById('lmsMenuToggle');
        const mobileMenu = document.getElementById('lmsMobileMenu');
        const overlay    = document.getElementById('lmsOverlay');
        const closeMenu  = document.getElementById('lmsCloseMenu');

        if (!menuToggle || !mobileMenu || !overlay) return false;

        function openMenu() {
            mobileMenu.classList.add('active');
            overlay.classList.add('active');
            document.body.style.overflow = 'hidden';
        }

        function closeMenuFn() {
            mobileMenu.classList.remove('active');
            overlay.classList.remove('active');
            document.body.style.overflow = '';
        }

        menuToggle.addEventListener('click', openMenu);
        if (closeMenu) closeMenu.addEventListener('click', closeMenuFn);
        overlay.addEventListener('click', closeMenuFn);
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') closeMenuFn();
        });

        return true;
    }

    // 1er essai immédiat
    if (!initMenu()) {
        // 2ème essai après DOMContentLoaded
        document.addEventListener('DOMContentLoaded', function () {
            if (!initMenu()) {
                // 3ème essai : attendre que Odoo injecte le header
                const observer = new MutationObserver(function () {
                    if (initMenu()) observer.disconnect();
                });
                observer.observe(document.body, {
                    childList: true,
                    subtree: true,
                });
            }
        });
    }

})();