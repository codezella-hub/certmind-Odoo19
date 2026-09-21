/**
 * Correctif Mixed Content — Azure Container Apps
 *
 * Azure ne transmet pas X-Forwarded-Proto à Odoo. Werkzeug construit
 * alors les URLs en http://, ce qui déclenche une erreur Mixed Content
 * dans le navigateur et bloque l'affichage des iframes (PDF, vidéos).
 *
 * Ce script remplace http:// par https:// sur toutes les iframes,
 * au chargement et lorsque de nouvelles iframes sont ajoutées.
 */
(function () {
    'use strict';

    function corrigerHttps() {
        document.querySelectorAll('iframe[src^="http://"]').forEach(function (iframe) {
            var src = iframe.src;
            iframe.src = 'https://' + src.slice(7);
        });
    }

    // Corriger les iframes présentes au chargement
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', corrigerHttps);
    } else {
        corrigerHttps();
    }

    // Corriger les iframes ajoutées dynamiquement (navigation SPA Odoo)
    if (window.MutationObserver) {
        var observateur = new MutationObserver(function (mutations) {
            mutations.forEach(function (m) {
                m.addedNodes.forEach(function (noeud) {
                    if (noeud.nodeType === 1) {
                        if (noeud.tagName === 'IFRAME' &&
                                noeud.src && noeud.src.startsWith('http://')) {
                            noeud.src = 'https://' + noeud.src.slice(7);
                        }
                        noeud.querySelectorAll &&
                            noeud.querySelectorAll('iframe[src^="http://"]')
                                 .forEach(function (iframe) {
                                     iframe.src = 'https://' + iframe.src.slice(7);
                                 });
                    }
                });
            });
        });
        observateur.observe(document.documentElement,
                            { childList: true, subtree: true });
    }
})();
