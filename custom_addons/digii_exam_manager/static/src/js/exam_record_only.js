/**
 * Demarrage des examens depuis le portail "Mes examens".
 *
 * Pattern IIFE classique (pas @odoo-module) pour fonctionner de facon
 * fiable sur les pages portail/website, comme exam_recording.js.
 *
 * Deux modes :
 *  - Standard (.o_exam_standard_start) -> /my/exam/<id>/start
 *  - Enregistrement seul (.o_exam_record_start) -> /my/exam/<id>/record-start
 *
 * Les deux routes creent un user_input et renvoient l'URL complete de
 * l'examen (avec answer_token), necessaire pour les certifications.
 */
(function () {
    "use strict";

    // Appel JSON-RPC "a la main" (pas d'import ES6, robuste sur le portail).
    function callRoute(url) {
        return fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                jsonrpc: "2.0",
                method: "call",
                params: {},
            }),
        })
            .then(function (resp) { return resp.json(); })
            .then(function (data) {
                // Odoo enveloppe la reponse dans "result".
                if (data.error) {
                    throw new Error(data.error.data
                        ? data.error.data.message
                        : "Erreur serveur");
                }
                return data.result || {};
            });
    }

    function startExam(btn, routeTemplate) {
        var examId = btn.getAttribute("data-exam-id");
        if (!examId) {
            return;
        }
        var original = btn.innerHTML;
        btn.innerHTML = '<i class="fa fa-spinner fa-spin"></i> Demarrage...';
        btn.style.pointerEvents = "none";

        var url = routeTemplate.replace("{id}", examId);
        callRoute(url)
            .then(function (result) {
                if (result.error) {
                    alert(result.error);
                    btn.innerHTML = original;
                    btn.style.pointerEvents = "auto";
                    return;
                }
                if (result.survey_url) {
                    window.location.href = result.survey_url;
                } else {
                    btn.innerHTML = original;
                    btn.style.pointerEvents = "auto";
                }
            })
            .catch(function (err) {
                alert(err.message || "Impossible de demarrer l'examen.");
                btn.innerHTML = original;
                btn.style.pointerEvents = "auto";
            });
    }

    function bindButtons() {
        var standard = document.querySelectorAll(".o_exam_standard_start");
        standard.forEach(function (btn) {
            btn.addEventListener("click", function (ev) {
                ev.preventDefault();
                startExam(btn, "/my/exam/{id}/start");
            });
        });

        var record = document.querySelectorAll(".o_exam_record_start");
        record.forEach(function (btn) {
            btn.addEventListener("click", function (ev) {
                ev.preventDefault();
                startExam(btn, "/my/exam/{id}/record-start");
            });
        });
    }

    // Le DOM peut deja etre pret quand ce script s'execute : on gere les
    // deux cas (contrairement a un simple addEventListener DOMContentLoaded
    // qui ne se declenche jamais si le DOM est deja charge).
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", bindButtons);
    } else {
        bindButtons();
    }
})();
