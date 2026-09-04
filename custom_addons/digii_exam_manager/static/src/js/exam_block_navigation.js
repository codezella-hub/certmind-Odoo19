/**
 * Bloque la navigation pendant le passage d'un examen :
 *   - Fleches "back" et "forward" du navigateur
 *   - Touche F5 et Ctrl+R (reload)
 *   - Touche Backspace quand on est hors d'un champ (declenche back sur anciens navigateurs)
 *   - Raccourcis Ctrl+W, Ctrl+F, Ctrl+P
 *   - Clic droit (context menu) pour reduire les possibilites de triche
 *   - Avertissement avant de quitter la page
 *
 * Ce script n'est actif que sur les pages de survey quand le survey a
 * is_exam = True. Il est injecte par le template
 * `exam_block_nav_on_survey` qui herite de `survey.survey_fill_form`.
 */
(function () {
    "use strict";

    // -------------------------------------------------------------------
    // 0. Sur l'écran de fin d'examen : NE RIEN bloquer (sinon la
    //    redirection automatique vers /my/exams est empêchée par
    //    beforeunload). On expose __examAllowLeave en no-op et on sort.
    // -------------------------------------------------------------------
    if (document.querySelector('.o_survey_finished')) {
        window.__examAllowLeave = function () {};
        console.log('[Exam] Page de fin : navigation libre.');
        return;
    }

    // -------------------------------------------------------------------
    // 1. Flag pour autoriser le "back" apres la soumission finale
    // -------------------------------------------------------------------
    var allowLeave = false;
    window.__examAllowLeave = function () { allowLeave = true; };

    // Detecter soumission du formulaire survey : le natif soumet via
    // un bouton submit. Au moment ou le candidat soumet, on autorise.
    document.addEventListener('submit', function () {
        allowLeave = true;
    }, true);

    // -------------------------------------------------------------------
    // 2. Blocage des fleches back / forward via popstate
    // -------------------------------------------------------------------
    try {
        history.pushState(null, '', window.location.href);
    } catch (e) { /* ignore */ }

    window.addEventListener('popstate', function () {
        if (allowLeave) return;
        // On re-pousse l'etat courant pour "annuler" le back
        try {
            history.pushState(null, '', window.location.href);
        } catch (e) { /* ignore */ }
        showWarning("Navigation bloquee pendant l'examen.");
    });

    // -------------------------------------------------------------------
    // 3. Blocage des raccourcis clavier
    // -------------------------------------------------------------------
    document.addEventListener('keydown', function (e) {
        // F5 / Ctrl+R / Ctrl+Shift+R -> reload
        if (e.key === 'F5' ||
            ((e.ctrlKey || e.metaKey) && (e.key === 'r' || e.key === 'R'))) {
            e.preventDefault();
            e.stopPropagation();
            showWarning("Le rechargement de la page est desactive pendant l'examen.");
            return false;
        }
        // Alt + fleches -> back / forward
        if (e.altKey && (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) {
            e.preventDefault();
            return false;
        }
        // Ctrl+W -> fermer onglet (on ne peut pas bloquer totalement, mais
        // beforeunload s'en charge)
        // Ctrl+F -> recherche, Ctrl+P -> print : souvent abuses pour voir les reponses
        if ((e.ctrlKey || e.metaKey) && (e.key === 'p' || e.key === 'P')) {
            e.preventDefault();
            showWarning("L'impression est desactivee pendant l'examen.");
            return false;
        }
        // Backspace hors d'un champ editable -> back sur anciens browsers
        if (e.key === 'Backspace') {
            var el = e.target;
            var isEditable = el && (
                el.tagName === 'INPUT' ||
                el.tagName === 'TEXTAREA' ||
                el.tagName === 'SELECT' ||
                el.isContentEditable
            );
            if (!isEditable) {
                e.preventDefault();
                return false;
            }
        }
    }, true);

    // -------------------------------------------------------------------
    // 4. Bloquer le clic droit (anti-copie)
    // -------------------------------------------------------------------
    document.addEventListener('contextmenu', function (e) {
        e.preventDefault();
        return false;
    });

    // -------------------------------------------------------------------
    // 5. Avertissement avant de quitter / fermer la page
    // -------------------------------------------------------------------
    window.addEventListener('beforeunload', function (e) {
        if (allowLeave) return;
        var msg = "Si vous quittez, votre examen sera perdu. Continuer ?";
        e.preventDefault();
        e.returnValue = msg;
        return msg;
    });

    // -------------------------------------------------------------------
    // 6. Petit toast discret pour prevenir le candidat
    // -------------------------------------------------------------------
    function showWarning(text) {
        var t = document.getElementById('exam-nav-warning');
        if (!t) {
            t = document.createElement('div');
            t.id = 'exam-nav-warning';
            t.style.cssText =
                'position:fixed;top:20px;right:20px;z-index:9999;' +
                'background:#F59E0B;color:#fff;padding:12px 18px;' +
                'border-radius:8px;font-family:system-ui,sans-serif;' +
                'font-size:13px;font-weight:600;box-shadow:0 4px 14px rgba(0,0,0,.2);' +
                'transition:opacity 0.3s;opacity:0;';
            document.body.appendChild(t);
        }
        t.textContent = text;
        t.style.opacity = '1';
        clearTimeout(t._hideTimer);
        t._hideTimer = setTimeout(function () {
            t.style.opacity = '0';
        }, 2500);
    }

    console.log('[Exam] Navigation blocker active');
})();
