/** @odoo-module **/
/**
 * Navigation par saut dans un examen (panneau lateral cliquable).
 *
 * OBJECTIF
 * --------
 * Permettre au candidat de cliquer sur un numero de question dans le panneau
 * lateral (#examQuestionGrid) pour SAUTER directement a cette question /
 * section, SANS PERDRE ses reponses, et en respectant le mode natif Odoo
 * `questions_layout` :
 *
 *   - one_page          : toutes les questions sont dans le DOM -> le saut est
 *                         un simple scroll (gere cote exam_question_grid.js).
 *   - page_per_question : une question a la fois -> on cible question.id.
 *   - page_per_section  : une section a la fois -> on cible page_id (section).
 *
 * POURQUOI LES REPONSES NE SONT PAS PERDUES
 * -----------------------------------------
 * On reutilise le mecanisme NATIF d'Odoo : `submitForm({ previousPageId })`.
 * Cote serveur (`/survey/submit`), AVANT de naviguer vers la cible, Odoo
 * appelle `_save_lines(...)` qui enregistre les reponses de la page/question
 * actuellement affichee. Le parametre `previous_page_id` fait ensuite afficher
 * directement la question/section ciblee (cf. _prepare_survey_data, branche
 * "Bypass all if page_id is specified"). C'est le meme chemin que le bouton
 * "Precedent" et le fil d'ariane natif -> 100% supporte, aucune triche.
 *
 * COMMENT
 * -------
 * Ce module PATCHE l'Interaction publique `SurveyForm` pour, a son demarrage,
 * ecouter un evenement custom `exam:goto` dispatche par le panneau lateral.
 * A reception, il appelle la methode native `submitForm({ previousPageId })`.
 *
 * Le panneau lateral (exam_question_grid.js, script classique) reste decouple :
 * il se contente de faire `document.dispatchEvent(new CustomEvent('exam:goto',
 * { detail: { targetId } }))`.
 */
import { patch } from "@web/core/utils/patch";
import { SurveyForm } from "@survey/interactions/survey_form";

patch(SurveyForm.prototype, {
    setup() {
        super.setup(...arguments);

        // N'activer la navigation par saut que sur les pages d'examen
        // (presence du config runtime injecte par digii_exam_manager).
        const cfg = document.getElementById("examRuntimeConfig");
        if (!cfg) {
            return;
        }

        // Handler stocke pour pouvoir le retirer a la destruction.
        this._examGotoHandler = (ev) => {
            try {
                this._examGoTo(ev && ev.detail ? ev.detail : {});
            } catch (e) {
                // Ne jamais casser l'examen a cause d'un saut.
                // eslint-disable-next-line no-console
                console.warn("[ExamJump] saut impossible:", e);
            }
        };
        document.addEventListener("exam:goto", this._examGotoHandler);

        // Informer le panneau que la navigation par saut est disponible
        // (utile pour activer le curseur "pointer" sur les items).
        document.dispatchEvent(new CustomEvent("exam:jump-ready"));
    },

    /**
     * Effectue le saut vers la cible en sauvegardant les reponses courantes.
     *
     * @param {Object} detail
     * @param {Number} detail.targetId  id de la question (page_per_question)
     *                                  OU id de la section (page_per_section)
     */
    _examGoTo(detail) {
        const targetId = parseInt(detail.targetId, 10);
        if (!targetId) {
            return;
        }
        // En cours de soumission : on ignore (evite les doubles navigations).
        if (this.submitting) {
            return;
        }
        // Mode one_page : rien a faire cote serveur, le scroll est gere par le
        // panneau lui-meme. On ne devrait pas recevoir d'evenement dans ce cas,
        // mais on protege par securite.
        if (this.options.questionsLayout === "one_page") {
            return;
        }
        // Reutilise le chemin natif "aller a une page precise" :
        //   - valide la page courante,
        //   - sauvegarde les reponses (cote serveur via _save_lines),
        //   - affiche la question/section ciblee.
        this.submitForm({ previousPageId: targetId });
    },

    /**
     * Nettoyage : retirer l'ecouteur quand l'interaction est detruite
     * (changement de page complet, etc.).
     */
    destroy() {
        if (this._examGotoHandler) {
            document.removeEventListener("exam:goto", this._examGotoHandler);
            this._examGotoHandler = null;
        }
        if (super.destroy) {
            super.destroy(...arguments);
        }
    },
});
