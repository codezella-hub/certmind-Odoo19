/** @odoo-module **/
import { markup } from "@odoo/owl";

/**
 * Mini-rendu markdown -> HTML, sans dependance externe.
 * Couvre : gras, italique, code inline, titres, listes a puces et numerotees,
 * sauts de ligne. Le texte est d'abord echappe pour eviter toute injection
 * (le contenu vient du modele IA, on reste prudent).
 */
function escapeHtml(text) {
    return String(text)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
}

function inlineFormat(text) {
    // code inline `...`
    text = text.replace(/`([^`]+)`/g, '<code>$1</code>');
    // gras **...**
    text = text.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    // italique *...*
    text = text.replace(/(^|[^*])\*([^*]+)\*/g, "$1<em>$2</em>");
    return text;
}

export function renderMarkdown(rawText) {
    const text = escapeHtml(rawText || "");
    const lines = text.split(/\r?\n/);
    const html = [];
    let listType = null; // 'ul' | 'ol' | null

    const closeList = () => {
        if (listType) {
            html.push(`</${listType}>`);
            listType = null;
        }
    };

    for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) {
            closeList();
            continue;
        }
        // Titres
        const h = trimmed.match(/^(#{1,3})\s+(.*)$/);
        if (h) {
            closeList();
            const level = h[1].length + 2; // h3..h5
            html.push(`<h${level}>${inlineFormat(h[2])}</h${level}>`);
            continue;
        }
        // Liste numerotee
        const ol = trimmed.match(/^\d+\.\s+(.*)$/);
        if (ol) {
            if (listType !== "ol") {
                closeList();
                html.push("<ol>");
                listType = "ol";
            }
            html.push(`<li>${inlineFormat(ol[1])}</li>`);
            continue;
        }
        // Liste a puces
        const ul = trimmed.match(/^[-*]\s+(.*)$/);
        if (ul) {
            if (listType !== "ul") {
                closeList();
                html.push("<ul>");
                listType = "ul";
            }
            html.push(`<li>${inlineFormat(ul[1])}</li>`);
            continue;
        }
        // Paragraphe
        closeList();
        html.push(`<p>${inlineFormat(trimmed)}</p>`);
    }
    closeList();
    return markup(html.join(""));
}
