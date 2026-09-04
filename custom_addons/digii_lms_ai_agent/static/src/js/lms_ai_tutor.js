/* Tuteur IA — panneau de chat sur la page du cours (site web / portail).
 *
 * S'injecte sur les pages eLearning. Un bouton flottant ouvre un panneau
 * de discussion. L'étudiant pose des questions sur la leçon ; les appels
 * partent vers les routes /lms_ai/* du contrôleur portail.
 *
 * Vanilla JS (pas de dépendance backend) pour rester léger côté site.
 */
(function () {
    "use strict";
    console.log("[Digii Tuteur IA] script chargé");

    // Récupère l'ID de la leçon courante depuis l'URL ou le DOM si présent.
    function currentSlideId() {
        // website_slides expose souvent l'id dans un attribut de données.
        var el = document.querySelector("[data-slide-id]");
        if (el) {
            return parseInt(el.getAttribute("data-slide-id"), 10) || null;
        }
        return null;
    }

    // Appel JSON-RPC vers une route Odoo type="json".
    function rpc(route, params) {
        return fetch(route, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                jsonrpc: "2.0",
                method: "call",
                params: params || {},
            }),
        })
            .then(function (r) { return r.json(); })
            .then(function (data) { return data.result || {}; });
    }

    var state = {
        open: false,
        sessionId: null,
        slideId: null,
        busy: false,
    };

    function el(tag, cls, html) {
        var e = document.createElement(tag);
        if (cls) e.className = cls;
        if (html !== undefined) e.innerHTML = html;
        return e;
    }

    function buildWidget() {
        // Bouton flottant
        var fab = el("button", "digii-ai-fab", "🎓");
        fab.title = "Tuteur IA";
        fab.setAttribute("aria-label", "Ouvrir le tuteur IA");

        // Panneau
        var panel = el("div", "digii-ai-panel");
        panel.innerHTML = [
            '<div class="digii-ai-header">',
            '  <span class="digii-ai-title">🎓 Tuteur IA</span>',
            '  <button class="digii-ai-close" aria-label="Fermer">×</button>',
            "</div>",
            '<div class="digii-ai-body" id="digiiAiBody">',
            '  <div class="digii-ai-welcome">',
            "    Bonjour ! Je suis ton tuteur pour cette leçon. ",
            "    Pose-moi une question sur ce que tu apprends.",
            "  </div>",
            "</div>",
            '<div class="digii-ai-input">',
            '  <textarea id="digiiAiText" rows="1" ',
            '     placeholder="Pose ta question..."></textarea>',
            '  <button id="digiiAiSend" aria-label="Envoyer">➤</button>',
            "</div>",
        ].join("");

        document.body.appendChild(fab);
        document.body.appendChild(panel);

        fab.addEventListener("click", function () { togglePanel(panel, true); });
        panel.querySelector(".digii-ai-close")
            .addEventListener("click", function () { togglePanel(panel, false); });

        var sendBtn = panel.querySelector("#digiiAiSend");
        var textArea = panel.querySelector("#digiiAiText");
        sendBtn.addEventListener("click", function () { send(panel); });
        textArea.addEventListener("keydown", function (ev) {
            if (ev.key === "Enter" && !ev.shiftKey) {
                ev.preventDefault();
                send(panel);
            }
        });
    }

    function togglePanel(panel, open) {
        state.open = open;
        panel.classList.toggle("digii-ai-open", open);
    }

    // Convertit un Markdown simple en HTML (titres, gras, listes, italique).
    function mdToHtml(md) {
        var text = md || "";
        // Échappe le HTML d'abord (sécurité).
        text = text.replace(/&/g, "&amp;").replace(/</g, "&lt;")
                   .replace(/>/g, "&gt;");
        var lines = text.split("\n");
        var html = [];
        var inList = false;
        lines.forEach(function (line) {
            var l = line.trim();
            // Titres ### / ## / #
            var h = l.match(/^(#{1,4})\s+(.*)$/);
            if (h) {
                if (inList) { html.push("</ul>"); inList = false; }
                var lvl = Math.min(h[1].length + 2, 6);
                html.push("<h" + lvl + ">" + inline(h[2]) + "</h" + lvl + ">");
                return;
            }
            // Puces - ou *
            var bullet = l.match(/^[-*]\s+(.*)$/);
            if (bullet) {
                if (!inList) { html.push("<ul>"); inList = true; }
                html.push("<li>" + inline(bullet[1]) + "</li>");
                return;
            }
            // Ligne vide
            if (l === "") {
                if (inList) { html.push("</ul>"); inList = false; }
                return;
            }
            // Paragraphe normal
            if (inList) { html.push("</ul>"); inList = false; }
            html.push("<p>" + inline(l) + "</p>");
        });
        if (inList) html.push("</ul>");
        return html.join("");
    }

    // Gras **x**, italique *x*, code `x`.
    function inline(s) {
        return s
            .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
            .replace(/\*([^*]+)\*/g, "<em>$1</em>")
            .replace(/`([^`]+)`/g, "<code>$1</code>");
    }

    function addBubble(body, role, text, isMarkdown) {
        var b = el("div", "digii-ai-msg digii-ai-" + role);
        if (isMarkdown) {
            b.innerHTML = mdToHtml(text);
        } else {
            b.textContent = text;
        }
        body.appendChild(b);
        body.scrollTop = body.scrollHeight;
        return b;
    }

    function send(panel) {
        if (state.busy) return;
        var body = panel.querySelector("#digiiAiBody");
        var textArea = panel.querySelector("#digiiAiText");
        var question = (textArea.value || "").trim();
        if (!question) return;

        addBubble(body, "user", question);
        textArea.value = "";
        state.busy = true;

        // Bulle "en train d'écrire"
        var typing = addBubble(body, "assistant", "…");
        typing.classList.add("digii-ai-typing");

        rpc("/lms_ai/tutor/ask", {
            question: question,
            slide_id: state.slideId,
            session_id: state.sessionId,
        })
            .then(function (res) {
                typing.remove();
                if (res.error) {
                    addBubble(body, "assistant", "⚠ " + res.error);
                } else {
                    state.sessionId = res.session_id;
                    addBubble(body, "assistant", res.answer, true);
                }
            })
            .catch(function () {
                typing.remove();
                addBubble(body, "assistant",
                    "⚠ Une erreur est survenue. Réessaie.");
            })
            .finally(function () { state.busy = false; });
    }

    // Init : sur les pages de cours/leçon uniquement.
    function init() {
        var onSlidesPage = /\/slides\//.test(window.location.pathname);
        if (!onSlidesPage) return;
        if (document.querySelector(".digii-ai-fab")) return;  // déjà injecté
        state.slideId = currentSlideId();
        buildWidget();
    }

    // Dans le site web Odoo, le script est souvent chargé APRÈS que le DOM
    // soit prêt : DOMContentLoaded ne se déclenchera plus. On gère les deux cas.
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
