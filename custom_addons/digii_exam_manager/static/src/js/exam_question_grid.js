/**
 * Exam page - Question navigation grid (panneau lateral indicateur).
 *
 * v3 - APPROCHE SIMPLE ET ROBUSTE :
 *
 *   - Le panneau lateral est UN INDICATEUR VISUEL UNIQUEMENT.
 *     Il ne touche PAS aux boutons natifs Odoo (precedent / suivant /
 *     submit). Ces boutons restent a leur place naturelle, en bas du
 *     formulaire d'examen, et continuent de fonctionner exactement
 *     comme dans un survey Odoo standard.
 *
 *   - Avantages :
 *       * Aucun risque de cacher / re-afficher un bouton (plus de bug
 *         de submit qui apparait puis disparait)
 *       * Aucun risque de double-clic / clones
 *       * Le va-et-vient (precedent / suivant) marche tel que defini
 *         par Odoo
 *
 *   - Le panneau affiche :
 *       1. Une barre de progression (X/N + pourcentage)
 *       2. Une grille de numeros de questions :
 *            - Violet plein (.current) -> question affichee maintenant
 *            - Gris neutre (.answered) -> question deja repondue
 *              (volontairement NI vert NI rouge pour ne pas suggerer
 *               une reponse correcte/fausse)
 *            - Beige (defaut)          -> question sans reponse
 *       3. Une legende
 *
 *   - PALETTE (alignee sur la maquette quiz.html fournie par l'utilisateur) :
 *       Fond page    : #F1EFE8 (beige)
 *       Cartes       : #FFFFFF
 *       Primaire     : #534AB7 (violet) / hover #463F9D
 *       Succes       : #639922 (vert) / soft #E1F5EE
 *       Texte muted  : #5F5E5A
 *       Police       : -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto
 *
 *   - DETECTION DE LA QUESTION COURANTE :
 *     Convention native Odoo Survey :
 *         <div class="js_question-wrapper"
 *              id="<surveyId>_<pageId>_<questionId>">
 *     Donc on prend le DERNIER nombre de l'id (pas le premier).
 *
 *   - Le mode CLAIR est force au niveau html+body avec color-scheme.
 *
 * Diagnostic :
 *   Console : "[ExamGrid]" pour voir l'etat de la detection.
 */
(function () {
    "use strict";

    var DEBUG = true;
    function log() {
        if (!DEBUG) return;
        var args = Array.prototype.slice.call(arguments);
        args.unshift('[ExamGrid]');
        console.log.apply(console, args);
    }

    var cfg = document.getElementById('examRuntimeConfig');
    if (!cfg) {
        log('No #examRuntimeConfig, abort');
        return;
    }

    // ---- Lecture des donnees ----
    var grid = [];
    var answeredIds = {};
    try {
        grid = JSON.parse(cfg.dataset.questionGrid || '[]');
    } catch (e) {
        log('question-grid parse error:', e);
        return;
    }
    if (!grid.length) {
        log('Empty grid, abort');
        return;
    }
    try {
        var arr = JSON.parse(cfg.dataset.answeredIds || '[]');
        arr.forEach(function (id) { answeredIds[id] = true; });
    } catch (e) { /* ignore */ }

    // Index id -> num pour les logs
    var idToNum = {};
    grid.forEach(function (q) { idToNum[q.id] = q.num; });

    // Mode de navigation natif Odoo (one_page / page_per_question /
    // page_per_section). Conditionne le comportement au clic sur un numero.
    var LAYOUT = cfg.dataset.layout || 'page_per_question';

    // Index id de question -> id de section parente (page_id).
    // Necessaire pour le mode page_per_section : on navigue par SECTION,
    // donc la cible du saut est le page_id, pas la question elle-meme.
    var idToPageId = {};
    grid.forEach(function (q) {
        idToPageId[q.id] = q.page_id || false;
    });

    log('Loaded', grid.length, 'questions,',
        Object.keys(answeredIds).length, 'already answered',
        '| layout =', LAYOUT);

    // -------------------------------------------------------------------
    // CSS injection
    // -------------------------------------------------------------------
    function injectStyles() {
        var style = document.createElement('style');
        style.textContent = `
            /* Forcer le mode clair sur TOUTE la page d'examen */
            html.eqg-active,
            body.eqg-active {
                color-scheme: light !important;
                background: #F1EFE8 !important;
                color: #1a1a1a !important;
            }
            body.eqg-active .o_survey_form,
            body.eqg-active form.js_surveyform,
            body.eqg-active form {
                color-scheme: light !important;
                background: #F1EFE8 !important;
                color: #1a1a1a !important;
            }
            body.eqg-active input,
            body.eqg-active textarea,
            body.eqg-active select,
            body.eqg-active button {
                color-scheme: light !important;
            }

            /* Masquer le footer "Powered by Odoo" pendant l'examen */
            body.eqg-active #wrapwrap > footer,
            body.eqg-active footer.o_footer,
            body.eqg-active footer#footer,
            body.eqg-active .o_footer,
            body.eqg-active .o_footer_copyright,
            body.eqg-active .o_footer_disclaimer,
            body.eqg-active .o_brand_promotion,
            body.eqg-active .o_powered_by,
            body.eqg-active #o_footer_powered_by,
            body.eqg-active a.o_brand_promotion,
            body.eqg-active a[href*="odoo.com"][title*="Powered"],
            body.eqg-active a[href*="odoo.com"][title*="powered"] {
                display: none !important;
                visibility: hidden !important;
                height: 0 !important;
                overflow: hidden !important;
            }

            /* Variables CSS scopees sur le panneau (pas :root) */
            #examQuestionGrid {
                --eqg-bg: #ffffff;
                --eqg-bg-soft: #F1EFE8;
                --eqg-bg-soft2: #F1EFE8;
                --eqg-border: rgba(0,0,0,0.1);
                --eqg-border-strong: rgba(0,0,0,0.2);
                --eqg-text: #1a1a1a;
                --eqg-text-soft: #5F5E5A;
                --eqg-text-muted: #5F5E5A;
                --eqg-shadow: 0 8px 24px rgba(15,23,42,0.08), 0 2px 6px rgba(15,23,42,0.04);
                --eqg-success: #639922;
                --eqg-success-strong: #527E1B;
                --eqg-success-soft: #E1F5EE;
                --eqg-success-text-on: #ffffff;
                /* Couleur NEUTRE pour une question "repondue" (numero coche).
                   Volontairement ni verte ni rouge, pour ne pas laisser croire
                   au candidat que sa reponse est correcte/fausse. Le vert reste
                   reserve a la barre de progression (avancement uniquement). */
                --eqg-answered: #475569;
                --eqg-answered-soft: #E2E8F0;
                --eqg-answered-strong: #334155;
                --eqg-primary: #534AB7;
                --eqg-primary-strong: #463F9D;
                --eqg-primary-soft: #EEEDFE;
                --eqg-track: #F1EFE8;

                color-scheme: light;
                position: fixed;
                top: 80px;
                right: 16px;
                z-index: 9998;
                width: 280px;
                max-height: calc(100vh - 110px);
                background: var(--eqg-bg);
                border: 0.5px solid var(--eqg-border);
                border-radius: 16px;
                box-shadow: var(--eqg-shadow);
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI',
                             Roboto, sans-serif;
                color: var(--eqg-text);
                display: flex;
                flex-direction: column;
                overflow: hidden;
                font-size: 13px;
            }

            /* ---- Header avec progression ---- */
            #examQuestionGrid .eqg-header {
                padding: 14px 16px 12px;
                background: linear-gradient(135deg,
                    var(--eqg-bg-soft) 0%, var(--eqg-bg) 100%);
                border-bottom: 0.5px solid var(--eqg-border);
            }
            #examQuestionGrid .eqg-title {
                display: flex;
                align-items: center;
                justify-content: space-between;
                margin-bottom: 8px;
            }
            #examQuestionGrid .eqg-title-text {
                font-size: 11px;
                font-weight: 500;
                text-transform: uppercase;
                letter-spacing: 0.5px;
                color: var(--eqg-text-muted);
            }
            #examQuestionGrid .eqg-progress-num {
                font-size: 13px;
                font-weight: 500;
                color: var(--eqg-text);
            }
            #examQuestionGrid .eqg-progress-num .eqg-num-done {
                color: var(--eqg-success);
            }
            #examQuestionGrid .eqg-progress-num .eqg-num-sep {
                color: var(--eqg-text-muted);
                font-weight: 500;
                margin: 0 2px;
            }
            #examQuestionGrid .eqg-progress-bar {
                width: 100%;
                height: 6px;
                background: var(--eqg-track);
                border-radius: 999px;
                overflow: hidden;
                position: relative;
            }
            #examQuestionGrid .eqg-progress-fill {
                height: 100%;
                background: var(--eqg-success);
                border-radius: 999px;
                width: 0%;
                transition: width 0.3s ease;
            }
            #examQuestionGrid .eqg-progress-pct {
                font-size: 10px;
                font-weight: 500;
                color: var(--eqg-text-muted);
                text-align: right;
                margin-top: 4px;
                letter-spacing: 0.3px;
            }

            /* ---- Grille de numeros ---- */
            #examQuestionGrid .eqg-list {
                padding: 12px;
                overflow-y: auto;
                display: grid;
                grid-template-columns: repeat(5, 1fr);
                gap: 6px;
                flex: 1;
                min-height: 0;
            }
            #examQuestionGrid .eqg-list::-webkit-scrollbar {
                width: 6px;
            }
            #examQuestionGrid .eqg-list::-webkit-scrollbar-thumb {
                background: var(--eqg-border-strong);
                border-radius: 3px;
            }

            #examQuestionGrid .eqg-item {
                aspect-ratio: 1 / 1;
                display: flex;
                align-items: center;
                justify-content: center;
                border-radius: 8px;
                background: var(--eqg-bg-soft2);
                color: var(--eqg-text-muted);
                font-size: 12px;
                font-weight: 500;
                border: 0.5px solid var(--eqg-border);
                cursor: pointer;
                user-select: none;
                position: relative;
                transition: transform 0.1s ease, box-shadow 0.1s ease;
            }
            #examQuestionGrid .eqg-item:hover {
                transform: scale(1.08);
                box-shadow: 0 2px 8px rgba(15,23,42,0.18);
            }
            #examQuestionGrid .eqg-item:active {
                transform: scale(0.97);
            }
            #examQuestionGrid .eqg-item.answered {
                background: var(--eqg-answered-soft);
                color: var(--eqg-answered-strong);
                border-color: transparent;
            }
            /* MISE EN EVIDENCE de la question courante */
            #examQuestionGrid .eqg-item.current {
                background: var(--eqg-primary) !important;
                color: #ffffff !important;
                border-color: var(--eqg-primary) !important;
                z-index: 2;
            }
            /* Si une question est a la fois courante ET deja repondue,
               on garde le violet de la courante car c'est l'info la plus
               importante pour l'utilisateur */
            #examQuestionGrid .eqg-item.answered.current {
                background: var(--eqg-primary) !important;
                color: #ffffff !important;
                border-color: var(--eqg-primary) !important;
            }

            /* ---- Legende ---- */
            #examQuestionGrid .eqg-legend {
                padding: 10px 14px;
                border-top: 0.5px solid var(--eqg-border);
                font-size: 11px;
                color: var(--eqg-text-muted);
                display: flex;
                gap: 12px;
                flex-wrap: wrap;
                background: var(--eqg-bg);
            }
            #examQuestionGrid .eqg-legend-item {
                display: inline-flex;
                align-items: center;
                gap: 5px;
            }
            #examQuestionGrid .eqg-legend-dot {
                display: inline-block;
                width: 7px;
                height: 7px;
                border-radius: 50%;
                vertical-align: middle;
            }

            /* ====================================================
               STYLE MODERNE DES BOUTONS NATIFS ODOO
               (Precedent / Suivant / Terminer)

               Approche : on NE TOUCHE PAS au DOM. On stylise les
               boutons natifs LA OU ils sont, en bas du formulaire.
               Si Odoo les re-render, le CSS s'applique a nouveau
               automatiquement. Aucun risque de casser le va-et-vient.
               ==================================================== */

            /* Conteneur de la barre de boutons */
            body.eqg-active .o_survey_main_button_container,
            body.eqg-active .o_survey_buttons,
            body.eqg-active .o_survey_navigation {
                display: flex !important;
                gap: 12px !important;
                justify-content: center !important;
                align-items: center !important;
                padding: 18px 16px !important;
                margin-top: 28px !important;
                margin-bottom: 16px !important;
                background: #ffffff !important;
                border: 0.5px solid var(--eqg-border, rgba(0,0,0,0.1)) !important;
                border-radius: 16px !important;
                box-shadow: none !important;
                flex-wrap: wrap !important;
            }

            /* Style commun aux boutons natifs */
            body.eqg-active .o_survey_main_button_container button,
            body.eqg-active .o_survey_buttons button,
            body.eqg-active .o_survey_navigation button,
            body.eqg-active form.js_surveyform button[type="submit"] {
                padding: 13px 28px !important;
                border-radius: 8px !important;
                font-weight: 500 !important;
                font-size: 15px !important;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI',
                             Roboto, sans-serif !important;
                border: none !important;
                cursor: pointer !important;
                transition: background 0.15s ease !important;
                display: inline-flex !important;
                align-items: center !important;
                gap: 8px !important;
                min-width: 130px !important;
                justify-content: center !important;
                line-height: 1.4 !important;
            }

            /* PRECEDENT : neutre, blanc avec bordure (comme nav-circle-btn) */
            body.eqg-active button[value="previous"],
            body.eqg-active button[name="previous"],
            body.eqg-active button[name="button_previous"] {
                background: #ffffff !important;
                color: #5F5E5A !important;
                border: 0.5px solid rgba(0,0,0,0.1) !important;
            }
            body.eqg-active button[value="previous"]:hover:not(:disabled),
            body.eqg-active button[name="previous"]:hover:not(:disabled),
            body.eqg-active button[name="button_previous"]:hover:not(:disabled) {
                background: #F1EFE8 !important;
            }

            /* SUIVANT : violet primary (comme .continue-btn de la maquette) */
            body.eqg-active button[value="next"],
            body.eqg-active button[name="next"],
            body.eqg-active button[name="button_next"] {
                background: #534AB7 !important;
                color: #ffffff !important;
                border: none !important;
            }
            body.eqg-active button[value="next"]:hover:not(:disabled),
            body.eqg-active button[name="next"]:hover:not(:disabled),
            body.eqg-active button[name="button_next"]:hover:not(:disabled) {
                background: #463F9D !important;
            }

            /* TERMINER / SUBMIT : vert succes, sobre (sans pulse) */
            body.eqg-active button[value="finish"],
            body.eqg-active button[name="button_submit"],
            body.eqg-active button[name="submit"],
            body.eqg-active form.js_surveyform button[type="submit"][value="finish"] {
                background: #639922 !important;
                color: #ffffff !important;
                border: none !important;
            }
            body.eqg-active button[value="finish"]:hover:not(:disabled),
            body.eqg-active button[name="button_submit"]:hover:not(:disabled),
            body.eqg-active button[name="submit"]:hover:not(:disabled) {
                background: #527E1B !important;
            }

            /* Active (clic en cours) */
            body.eqg-active .o_survey_main_button_container button:active,
            body.eqg-active .o_survey_buttons button:active,
            body.eqg-active .o_survey_navigation button:active {
                transform: translateY(0) !important;
            }

            /* Disabled (bouton grise par Odoo, ex: fin du formulaire) */
            body.eqg-active .o_survey_main_button_container button:disabled,
            body.eqg-active .o_survey_buttons button:disabled,
            body.eqg-active .o_survey_navigation button:disabled {
                opacity: 0.45 !important;
                cursor: not-allowed !important;
                transform: none !important;
            }

            /* Sur mobile : barre en bas, boutons en colonne pour
               eviter qu'ils debordent */
            @media (max-width: 992px) {
                body.eqg-active .o_survey_main_button_container,
                body.eqg-active .o_survey_buttons,
                body.eqg-active .o_survey_navigation {
                    margin-bottom: 60vh !important;  /* place pour le panneau bottom */
                    padding: 14px 10px !important;
                    gap: 8px !important;
                }
                body.eqg-active .o_survey_main_button_container button,
                body.eqg-active .o_survey_buttons button,
                body.eqg-active .o_survey_navigation button {
                    min-width: 0 !important;
                    flex: 1 1 auto !important;
                    padding: 10px 14px !important;
                    font-size: 13px !important;
                }
            }

            /* ---- Decaler le contenu de la page pour ne pas etre sous le panneau ---- */
            @media (min-width: 993px) {
                body.eqg-active .o_survey_form,
                body.eqg-active form.js_surveyform,
                body.eqg-active main {
                    padding-right: 310px;
                }
            }

            /* ---- Responsive ---- */
            @media (max-width: 992px) {
                #examQuestionGrid {
                    position: fixed;
                    top: auto;
                    bottom: 8px;
                    right: 8px;
                    left: 8px;
                    width: auto;
                    max-height: 40vh;
                    border-radius: 12px;
                }
                #examQuestionGrid .eqg-list {
                    grid-template-columns: repeat(8, 1fr);
                }
            }
            @media (max-width: 480px) {
                #examQuestionGrid .eqg-list {
                    grid-template-columns: repeat(6, 1fr);
                }
            }
        `;
        document.head.appendChild(style);
    }

    // -------------------------------------------------------------------
    // Construction du panneau
    // -------------------------------------------------------------------
    var panel, list;

    function buildPanel() {
        panel = document.createElement('div');
        panel.id = 'examQuestionGrid';

        panel.innerHTML =
            '<div class="eqg-header">' +
                '<div class="eqg-title">' +
                    '<span class="eqg-title-text">Progression</span>' +
                    '<span class="eqg-progress-num" id="eqgProgressNum">' +
                        '<span class="eqg-num-done">0</span>' +
                        '<span class="eqg-num-sep">/</span>' +
                        '<span>' + grid.length + '</span>' +
                    '</span>' +
                '</div>' +
                '<div class="eqg-progress-bar">' +
                    '<div class="eqg-progress-fill" id="eqgProgressFill"></div>' +
                '</div>' +
                '<div class="eqg-progress-pct" id="eqgProgressPct">0%</div>' +
            '</div>' +
            '<div class="eqg-list" id="eqgList"></div>' +
            '<div class="eqg-legend">' +
                '<span class="eqg-legend-item">' +
                    '<span class="eqg-legend-dot" style="background:var(--eqg-primary);' +
                        'box-shadow:0 0 0 2px var(--eqg-primary-soft)"></span>' +
                    'En cours' +
                '</span>' +
                '<span class="eqg-legend-item">' +
                    '<span class="eqg-legend-dot" style="background:var(--eqg-answered)"></span>' +
                    'Repondue' +
                '</span>' +
                '<span class="eqg-legend-item">' +
                    '<span class="eqg-legend-dot" style="background:var(--eqg-bg-soft2);' +
                        'border:1px solid var(--eqg-border-strong)"></span>' +
                    'Non repondue' +
                '</span>' +
            '</div>';

        document.body.appendChild(panel);
        document.body.classList.add('eqg-active');
        document.documentElement.classList.add('eqg-active');
        list = document.getElementById('eqgList');

        grid.forEach(function (q) {
            var item = document.createElement('div');
            item.className = 'eqg-item';
            item.dataset.questionId = q.id;
            item.id = 'eqg-item-' + q.id;
            item.title = 'Question ' + q.num + (q.title ? ' : ' + q.title : '');
            item.textContent = q.num;
            if (answeredIds[q.id]) item.classList.add('answered');
            // NAVIGATION : clic = saut vers cette question / section
            item.addEventListener('click', function () {
                navigateToQuestion(q.id);
            });
            list.appendChild(item);
        });

        updateProgress();
    }

    function updateProgress() {
        var answered = grid.filter(function (q) {
            return answeredIds[q.id];
        }).length;
        var total = grid.length;
        var pct = total > 0 ? Math.round((answered / total) * 100) : 0;

        var numEl = document.getElementById('eqgProgressNum');
        if (numEl) {
            numEl.innerHTML =
                '<span class="eqg-num-done">' + answered + '</span>' +
                '<span class="eqg-num-sep">/</span>' +
                '<span>' + total + '</span>';
        }
        var fillEl = document.getElementById('eqgProgressFill');
        if (fillEl) fillEl.style.width = pct + '%';
        var pctEl = document.getElementById('eqgProgressPct');
        if (pctEl) pctEl.textContent = pct + '% complete';
    }

    function markAnswered(qid, isAnswered) {
        var item = document.getElementById('eqg-item-' + qid);
        if (!item) return;
        var was = !!answeredIds[qid];
        if (isAnswered) {
            answeredIds[qid] = true;
            item.classList.add('answered');
        } else {
            delete answeredIds[qid];
            item.classList.remove('answered');
        }
        if (was !== isAnswered) updateProgress();
    }

    function markCurrent(currentIds) {
        var prev = document.querySelectorAll('#examQuestionGrid .eqg-item.current');
        prev.forEach(function (el) { el.classList.remove('current'); });
        currentIds.forEach(function (qid) {
            var item = document.getElementById('eqg-item-' + qid);
            if (item) {
                item.classList.add('current');
                if (item.scrollIntoView) {
                    try {
                        item.scrollIntoView({
                            behavior: 'smooth',
                            block: 'nearest',
                            inline: 'nearest',
                        });
                    } catch (e) { /* ignore */ }
                }
            }
        });
    }

    // -------------------------------------------------------------------
    // NAVIGATION : clic sur un numero -> aller a la question / section
    //
    // Comportement selon le mode natif Odoo (LAYOUT) :
    //
    //   * one_page :
    //       Toutes les questions sont deja dans le DOM. On fait simplement
    //       defiler la page jusqu'a la question. Aucune perte de reponse
    //       possible (rien n'est soumis).
    //
    //   * page_per_question :
    //       Une seule question est affichee a la fois. On demande a
    //       l'interaction native SurveyForm de SAUTER vers question.id en
    //       passant par `submitForm({ previousPageId })` -> Odoo sauvegarde
    //       d'abord les reponses de la question courante puis affiche la cible.
    //
    //   * page_per_section :
    //       Une seule SECTION est affichee a la fois. La cible du saut est
    //       donc le page_id (section) de la question cliquee, pas la question.
    //       Si la question n'a pas de section (page_id = False), il n'y a
    //       qu'une "page" implicite -> on ne tente pas de saut serveur.
    //
    // Le dialogue avec l'interaction native se fait via l'evenement custom
    // 'exam:goto' (ecoute par exam_survey_jump.js qui patche SurveyForm).
    // -------------------------------------------------------------------
    function navigateToQuestion(qid) {
        log('Navigation demandee vers question id', qid,
            '(N°', idToNum[qid], ') | layout', LAYOUT);

        if (LAYOUT === 'one_page') {
            scrollToQuestionInDom(qid);
            return;
        }

        var targetId = qid;
        if (LAYOUT === 'page_per_section') {
            var pageId = idToPageId[qid];
            if (!pageId) {
                // Question sans section : pas de saut serveur fiable possible.
                // On tente quand meme un scroll au cas ou elle serait visible.
                scrollToQuestionInDom(qid);
                return;
            }
            targetId = pageId;
        }

        // Si la question (ou sa section) est deja celle affichee, on ne
        // soumet pas : on se contente d'un scroll (evite un aller-retour
        // serveur inutile).
        var currentIds = detectCurrentQuestionIds();
        if (currentIds.indexOf(qid) !== -1) {
            scrollToQuestionInDom(qid);
            return;
        }

        // Deleguer le saut a l'interaction native (sauvegarde + affichage).
        document.dispatchEvent(new CustomEvent('exam:goto', {
            detail: { targetId: targetId },
        }));
    }

    // Defilement doux vers la question dans le DOM (mode one_page ou
    // question deja visible). On cible le wrapper natif Odoo.
    function scrollToQuestionInDom(qid) {
        var selectors = [
            '.js_question-wrapper#' + cssEscape(String(qid)),
            '[data-question-id="' + qid + '"]',
        ];
        var target = null;
        for (var i = 0; i < selectors.length && !target; i++) {
            try {
                var nodes = document.querySelectorAll(selectors[i]);
                nodes.forEach(function (el) {
                    if (target) return;
                    if (el.closest && el.closest('#examQuestionGrid')) return;
                    target = el;
                });
            } catch (e) { /* selecteur invalide -> ignore */ }
        }
        // Fallback : wrapper dont l'id se termine par _<qid>
        if (!target) {
            document.querySelectorAll('.js_question-wrapper').forEach(function (el) {
                if (target) return;
                if (el.closest && el.closest('#examQuestionGrid')) return;
                var nums = (el.id || '').match(/\d+/g);
                if (nums && nums[nums.length - 1] === String(qid)) {
                    target = el;
                }
            });
        }
        if (target && target.scrollIntoView) {
            target.scrollIntoView({ behavior: 'smooth', block: 'center' });
            // Petit highlight visuel pour reperer la question
            flashHighlight(target);
        } else {
            log('scrollToQuestionInDom: cible introuvable pour', qid);
        }
    }

    // Surbrillance breve de la question ciblee
    function flashHighlight(el) {
        try {
            var prev = el.style.transition;
            el.style.transition = 'box-shadow 0.3s ease';
            el.style.boxShadow = '0 0 0 3px rgba(83,74,183,0.45)';
            setTimeout(function () {
                el.style.boxShadow = '';
                el.style.transition = prev || '';
            }, 900);
        } catch (e) { /* ignore */ }
    }

    // CSS.escape n'est pas garanti partout (vieux navigateurs) -> fallback
    function cssEscape(s) {
        if (window.CSS && window.CSS.escape) return window.CSS.escape(s);
        return s.replace(/[^a-zA-Z0-9_-]/g, '\\$&');
    }

    // -------------------------------------------------------------------
    // DETECTION DE LA QUESTION COURANTE
    //
    // Convention native Odoo Survey (depuis Odoo 16+) :
    //   <div class="js_question-wrapper"
    //        id="<surveyId>_<pageId>_<questionId>">
    //
    // Le DERNIER nombre est le questionId. C'est l'info la plus fiable.
    //
    // Strategies en cascade (on s'arrete a la 1ere qui retourne qqch) :
    //   1. .js_question-wrapper visible (id du DERNIER nombre)
    //   2. [data-question-id] visible
    //   3. inputs name=qid (premier nombre)
    //   4. recherche par titre dans le form
    // -------------------------------------------------------------------
    function detectCurrentQuestionIds() {
        var ids = {};
        var gridIds = grid.map(function (g) { return g.id; });

        function tryAdd(qid) {
            qid = parseInt(qid, 10);
            if (qid && gridIds.indexOf(qid) !== -1) ids[qid] = true;
        }

        function isVisible(el) {
            if (!el) return false;
            if (el.tagName === 'BODY' || el.tagName === 'HTML') return true;
            // offsetParent est null si display:none quelque part
            if (el.offsetParent === null) return false;
            return true;
        }

        function isOurNode(el) {
            if (!el) return true;
            if (el.id === 'examQuestionGrid' || el.id === 'examRuntimeConfig') return true;
            if (el.closest && (
                el.closest('#examQuestionGrid') ||
                el.closest('#examRuntimeConfig')
            )) return true;
            return false;
        }

        // STRATEGIE 1 : .js_question-wrapper (la plus fiable, native Odoo)
        // Format de l'id : "<surveyId>_<pageId>_<questionId>"
        // -> on extrait TOUS les nombres et on prend le DERNIER
        document.querySelectorAll('.js_question-wrapper').forEach(function (el) {
            if (isOurNode(el)) return;
            if (!isVisible(el)) return;

            // En priorite : data-question-id si Odoo l'a mis
            var dqid = el.dataset.questionId || el.getAttribute('data-question-id');
            if (dqid) {
                tryAdd(dqid);
                return;
            }
            // Sinon : dernier nombre de l'id
            if (el.id) {
                var nums = el.id.match(/\d+/g);
                if (nums && nums.length > 0) {
                    tryAdd(nums[nums.length - 1]);
                }
            }
        });

        // STRATEGIE 2 : [data-question-id] direct (si la 1 n'a rien donne)
        if (Object.keys(ids).length === 0) {
            document.querySelectorAll('[data-question-id]').forEach(function (el) {
                if (isOurNode(el)) return;
                if (!isVisible(el)) return;
                tryAdd(el.dataset.questionId);
            });
        }

        // STRATEGIE 3 : inputs name=qid (fallback)
        // Format Odoo : name="<question_id>" ou "<question_id>_<...>"
        if (Object.keys(ids).length === 0) {
            var scope = document.querySelector('.o_survey_form, form.js_surveyform, form') || document;
            scope.querySelectorAll('input[name], textarea[name], select[name]').forEach(function (el) {
                if (isOurNode(el)) return;
                if (!isVisible(el)) return;
                var name = el.getAttribute('name') || '';
                if (/csrf|token|input_token|access|page_id/i.test(name)) return;
                var first = name.match(/^\d+/);
                if (first) tryAdd(first[0]);
            });
        }

        // STRATEGIE 4 : recherche par titre (dernier fallback)
        if (Object.keys(ids).length === 0) {
            var formScope = document.querySelector('.o_survey_form, form.js_surveyform') || document.body;
            var pageText = (formScope.textContent || '').toLowerCase();
            grid.forEach(function (q) {
                if (q.title && q.title.length >= 8) {
                    if (pageText.indexOf(q.title.toLowerCase()) !== -1) {
                        tryAdd(q.id);
                    }
                }
            });
        }

        var result = Object.keys(ids).map(function (k) { return parseInt(k, 10); });
        var nums = result.map(function (id) { return idToNum[id] || '?'; });
        log('Current question IDs detected:', result, '(question N°', nums.join(', '), ')');
        return result;
    }

    function isQuestionAnswered(qid) {
        // Selecteurs pour trouver les inputs lies a la question qid.
        // Format Odoo : name commence par <qid> ou _<qid> dans certains cas.
        var sel =
            'input[name="' + qid + '"], ' +
            'input[name^="' + qid + '_"], ' +
            'textarea[name="' + qid + '"], ' +
            'textarea[name^="' + qid + '_"], ' +
            'select[name="' + qid + '"], ' +
            'select[name^="' + qid + '_"], ' +
            '[data-question-id="' + qid + '"] input, ' +
            '[data-question-id="' + qid + '"] textarea, ' +
            '[data-question-id="' + qid + '"] select';

        var nodes = document.querySelectorAll(sel);
        if (!nodes.length) return null;

        var hasAnswer = false;
        nodes.forEach(function (el) {
            if (hasAnswer) return;
            if (el.type === 'radio' || el.type === 'checkbox') {
                if (el.checked) hasAnswer = true;
            } else if (el.tagName === 'SELECT') {
                if (el.value && el.value !== '' && el.value !== '-1') {
                    hasAnswer = true;
                }
            } else {
                var v = (el.value || '').trim();
                if (v) hasAnswer = true;
            }
        });
        return hasAnswer;
    }

    function refreshCurrentPageStates() {
        var currentIds = detectCurrentQuestionIds();
        markCurrent(currentIds);
        currentIds.forEach(function (qid) {
            var ans = isQuestionAnswered(qid);
            if (ans === null) return;
            markAnswered(qid, ans);
        });
        // Aussi rafraichir les autres questions visibles (pour les
        // surveys "all questions on one page")
        grid.forEach(function (q) {
            if (currentIds.indexOf(q.id) !== -1) return;
            var ans = isQuestionAnswered(q.id);
            if (ans === true && !answeredIds[q.id]) {
                markAnswered(q.id, true);
            }
        });
    }

    // -------------------------------------------------------------------
    // Init
    // -------------------------------------------------------------------
    function init() {
        injectStyles();
        buildPanel();
        refreshCurrentPageStates();

        var resyncTimer = null;

        function scheduleResync() {
            if (resyncTimer) clearTimeout(resyncTimer);
            resyncTimer = setTimeout(refreshCurrentPageStates, 150);
        }

        // Observer les changements de DOM pour detecter les changements
        // de page (Odoo recharge le contenu du form en AJAX).
        // On ignore les changements DANS notre panneau pour eviter les
        // boucles inutiles.
        var observer = new MutationObserver(function (mutations) {
            for (var i = 0; i < mutations.length; i++) {
                var t = mutations[i].target;
                if (!t) continue;
                if (t.id === 'examQuestionGrid' ||
                    (t.closest && t.closest('#examQuestionGrid'))) {
                    continue;
                }
                scheduleResync();
                return;
            }
        });
        observer.observe(document.body, {
            childList: true,
            subtree: true,
        });

        // Mettre a jour le statut des reponses au fil de la frappe / clic
        var form = document.querySelector('.o_survey_form, form.js_surveyform, form') || document.body;
        ['change', 'input', 'click'].forEach(function (evt) {
            form.addEventListener(evt, function () {
                setTimeout(refreshCurrentPageStates, 0);
            }, true);
        });

        log('Init done.');
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
