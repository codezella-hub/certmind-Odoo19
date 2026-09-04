/** @odoo-module **/
import { Component, useState, useRef, onMounted, onWillStart } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";
import { useService } from "@web/core/utils/hooks";
import { AiMessage } from "./components/ai_message";
import { AiQuestionCard } from "./components/ai_question_card";
import { AiRuleCard } from "./components/ai_rule_card";
import { AiTypingIndicator } from "./components/ai_typing_indicator";

let MSG_SEQ = 1;

export class AiAgentPanel extends Component {
    static template = "digii_exam_ai_agent.AiAgentPanel";
    static components = { AiMessage, AiQuestionCard, AiRuleCard, AiTypingIndicator };
    static props = {
        close: { type: Function },
        surveyId: { type: [Number, Boolean], optional: true },
        surveyName: { type: String, optional: true },
        defaultMode: { type: String, optional: true },
    };

    setup() {
        this.notification = useService("notification");
        this.scrollRef = useRef("scroll");
        this.inputRef = useRef("input");

        this.state = useState({
            visible: false, // pour l'animation d'entree
            mode: this.props.defaultMode || (this.props.surveyId ? "rules" : "questions"),
            messages: [],
            input: "",
            loading: false,
            configured: true,
            model: "",
            // parametres generation questions
            sourceType: this.props.surveyId ? "course" : "topic",
            count: 5,
            questionType: "simple_choice",
            cognitiveType: "",       // type cognitif (memoire, application...)
            categoryId: false,       // categorie cible
            difficultyMode: "balanced", // 'balanced' | 'custom'
            diffEasy: 2,
            diffMedium: 2,
            diffHard: 1,
            // contexte
            courses: [],
            exams: [],
            categories: [],          // liste des categories pour le menu
            courseId: false,
            surveyId: this.props.surveyId || false,
            lastQuestionsMsgId: null, // pour les actions groupees
            // --- mode assistant Q&A ---
            chatSessionId: false,      // conversation courante
            chatSessions: [],          // historique des conversations
            showSessions: false,       // afficher la liste des conversations
            userLang: "fr",            // langue de l'utilisateur (fr / en)
            confirmDeleteId: null,     // session en attente de confirmation ('all' = tout)
        });

        onWillStart(async () => {
            try {
                const status = await rpc("/digii_exam_ai_agent/config_status", {});
                this.state.configured = status.configured;
                this.state.model = status.model || "";
                // Interface en francais par defaut (chips, accueil), quelle que
                // soit la langue du compte Odoo. L'IA repond quand meme dans la
                // langue de la question posee.
                this.state.userLang = "fr";
            } catch {
                this.state.configured = false;
            }
            try {
                const ctx = await rpc("/digii_exam_ai_agent/context_data", {});
                this.state.courses = ctx.courses || [];
                this.state.exams = ctx.exams || [];
                this.state.categories = ctx.categories || [];
            } catch {
                // contexte optionnel
            }
        });

        onMounted(() => {
            // declenche la transition slide-in
            requestAnimationFrame(() => {
                this.state.visible = true;
            });
            this._greet();
        });
    }

    // ----------------------------------------------------------------
    // Helpers conversation
    // ----------------------------------------------------------------

    _greet() {
        if (!this.state.configured) {
            this._pushAssistant(
                "L'assistant IA n'est pas encore configure. Renseignez la cle " +
                    "API Groq dans **Parametres > Technique > Parametres systeme** " +
                    "(`digii_exam_ai_agent.api_key`)."
            );
            return;
        }
        if (this.state.mode === "rules") {
            const exam = this.props.surveyName || "cet examen";
            this._pushAssistant(
                `Bonjour ! Decrivez l'examen souhaite pour **${exam}** ` +
                    "(ex: *40 questions, 60% Reseaux, equilibre facile/moyen/difficile*) " +
                    "et je proposerai des regles de generation, en verifiant si la " +
                    "banque a assez de questions."
            );
        } else if (this.state.mode === "assistant") {
            if (this.state.userLang === "en") {
                this._pushAssistant(
                    "Hello! I am your **analytics assistant**. Ask me anything " +
                        "about your courses, exams, results, certificates, " +
                        "proctoring or question bank. I answer with **real " +
                        "numbers**, **charts** and **tables**. You can write in " +
                        "English or French."
                );
            } else {
                this._pushAssistant(
                    "Bonjour ! Je suis votre **assistant analytique**. Posez-moi " +
                        "n'importe quelle question sur vos cours, examens, resultats, " +
                        "certificats, proctoring ou banque de questions. Je reponds " +
                        "avec les **chiffres reels**, des **graphiques** et des " +
                        "**tableaux**. Vous pouvez ecrire en francais ou en anglais."
                );
            }
        } else {
            this._pushAssistant(
                "Bonjour ! Je peux generer des questions d'examen a partir d'un " +
                    "cours, d'un texte, ou d'un simple sujet. Reglez les options " +
                    "ci-dessus puis decrivez ce que vous voulez."
            );
        }
    }

    _pushUser(content) {
        this.state.messages.push({ id: MSG_SEQ++, type: "text", role: "user", content });
        this._scrollSoon();
    }

    _pushAssistant(content) {
        this.state.messages.push({ id: MSG_SEQ++, type: "text", role: "assistant", content });
        this._scrollSoon();
    }

    _pushQuestions(cards) {
        const msgId = MSG_SEQ++;
        this.state.messages.push({ id: msgId, type: "questions", cards });
        this.state.lastQuestionsMsgId = msgId;
        this._scrollSoon();
    }

    /** Approuve toutes les questions non encore traitees du dernier lot. */
    approveAllQuestions = async () => {
        const msg = this.state.messages.find(
            (m) => m.id === this.state.lastQuestionsMsgId && m.type === "questions"
        );
        if (!msg) {
            return;
        }
        const pending = msg.cards.filter(
            (c) => c.validation_state !== "approved" && c.validation_state !== "rejected"
        );
        if (!pending.length) {
            this.notification.add("Aucune question à approuver.", { type: "info" });
            return;
        }
        let ok = 0;
        for (const card of pending) {
            try {
                await this.onApproveQuestion(card.id);
                ok++;
            } catch {
                // on continue meme si une echoue
            }
        }
        this.notification.add(`${ok} question(s) ajoutée(s) à la banque.`, {
            type: "success",
        });
    };

    /** Nombre de questions approuvées dans le dernier lot (pour le compteur). */
    get lastBatchStats() {
        const msg = this.state.messages.find(
            (m) => m.id === this.state.lastQuestionsMsgId && m.type === "questions"
        );
        if (!msg) {
            return null;
        }
        const total = msg.cards.length;
        const approved = msg.cards.filter((c) => c.validation_state === "approved").length;
        return { total, approved };
    }

    _pushRules(notes, cards) {
        this.state.messages.push({ id: MSG_SEQ++, type: "rules", notes, cards });
        this._scrollSoon();
    }

    _scrollSoon() {
        setTimeout(() => {
            const el = this.scrollRef.el;
            if (el) {
                el.scrollTop = el.scrollHeight;
            }
        }, 50);
    }

    // ----------------------------------------------------------------
    // UI : mode / chips / input
    // ----------------------------------------------------------------

    setMode(mode) {
        if (this.state.mode === mode) {
            return;
        }
        this.state.mode = mode;
        this._greet();
    }

    onChipClick(text) {
        this.state.input = text;
        if (this.inputRef.el) {
            this.inputRef.el.focus();
            this._autoResize();
        }
    }

    onInput(ev) {
        this.state.input = ev.target.value;
        this._autoResize();
    }

    _autoResize() {
        const el = this.inputRef.el;
        if (!el) {
            return;
        }
        el.style.height = "auto";
        el.style.height = Math.min(el.scrollHeight, 160) + "px";
    }

    onKeydown(ev) {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            this.send();
        }
    }

    get canSend() {
        return !this.state.loading && this.state.input.trim().length > 0;
    }

    close() {
        this.state.visible = false;
        setTimeout(() => this.props.close(), 220);
    }

    // ----------------------------------------------------------------
    // Envoi
    // ----------------------------------------------------------------

    async send() {
        if (!this.canSend) {
            return;
        }
        const text = this.state.input.trim();
        this.state.input = "";
        if (this.inputRef.el) {
            this.inputRef.el.style.height = "auto";
        }
        this._pushUser(text);

        if (this.state.mode === "rules") {
            await this._sendRules(text);
        } else if (this.state.mode === "assistant") {
            await this._sendAssistant(text);
        } else {
            await this._sendQuestions(text);
        }
    }

    // ----------------------------------------------------------------
    // Mode ASSISTANT Q&A (analytique, avec sessions + historique)
    // ----------------------------------------------------------------

    async _sendAssistant(text) {
        this.state.loading = true;
        try {
            const res = await rpc("/digii_exam_ai_agent/chat/ask", {
                session_id: this.state.chatSessionId || false,
                question: text,
            });
            if (res.error) {
                this._pushAssistant("⚠ " + res.error);
            } else {
                this.state.chatSessionId = res.session_id;
                const msg = res.message || {};
                // Message avec eventuels graphiques et tableaux.
                this.state.messages.push({
                    id: MSG_SEQ++,
                    type: "analytics",
                    role: "assistant",
                    content: msg.content || "",
                    charts: this._prepareCharts(msg.charts || []),
                    tables: this._prepareTables(msg.tables || []),
                });
                this._scrollSoon();
                this._refreshChatSessions();
            }
        } catch (err) {
            this._pushAssistant("⚠ Erreur de communication avec l'assistant.");
        } finally {
            this.state.loading = false;
        }
    }

    async _refreshChatSessions() {
        try {
            const res = await rpc("/digii_exam_ai_agent/chat/sessions", {});
            this.state.chatSessions = res.sessions || [];
        } catch {
            // silencieux
        }
    }

    async openChatSession(sessionId) {
        try {
            const res = await rpc("/digii_exam_ai_agent/chat/history", {
                session_id: sessionId,
            });
            if (res.error) {
                this.notification.add(res.error, { type: "warning" });
                return;
            }
            this.state.chatSessionId = res.session_id;
            this.state.showSessions = false;
            // Recharge l'historique dans la zone de messages.
            this.state.messages = [];
            for (const m of res.messages || []) {
                if (m.role === "user") {
                    this._pushUser(m.content);
                } else {
                    this.state.messages.push({
                        id: MSG_SEQ++,
                        type: "analytics",
                        role: "assistant",
                        content: m.content || "",
                        charts: this._prepareCharts(m.charts || []),
                        tables: this._prepareTables(m.tables || []),
                    });
                }
            }
            this._scrollSoon();
        } catch {
            this.notification.add("Impossible de charger la conversation.",
                { type: "warning" });
        }
    }

    async newChatSession() {
        this.state.chatSessionId = false;
        this.state.showSessions = false;
        this.state.messages = [];
        this._greet();
    }

    /** 1er clic : passe en mode "Confirmer ?". 2e clic : supprime. */
    async deleteChatSession(sessionId, ev) {
        if (ev) {
            ev.stopPropagation(); // ne pas ouvrir la conversation en meme temps
        }
        if (this.state.confirmDeleteId !== sessionId) {
            // Premier clic : demander confirmation inline.
            this._armConfirm(sessionId);
            return;
        }
        // Deuxieme clic : suppression reelle.
        this._clearConfirm();
        try {
            const res = await rpc("/digii_exam_ai_agent/chat/delete", {
                session_id: sessionId,
            });
            if (res.error) {
                this.notification.add(res.error, { type: "warning" });
                return;
            }
            if (this.state.chatSessionId === sessionId) {
                this.newChatSession();
                this.state.showSessions = true; // rester sur la liste
            }
            await this._refreshChatSessions();
        } catch {
            this.notification.add(
                this.state.userLang === "en"
                    ? "Unable to delete the conversation."
                    : "Impossible de supprimer la conversation.",
                { type: "warning" });
        }
    }

    /** 1er clic : "Confirmer ?". 2e clic : supprime tout. */
    async deleteAllChatSessions() {
        if (this.state.confirmDeleteId !== "all") {
            this._armConfirm("all");
            return;
        }
        this._clearConfirm();
        try {
            const res = await rpc("/digii_exam_ai_agent/chat/delete_all", {});
            if (res.error) {
                this.notification.add(res.error, { type: "warning" });
                return;
            }
            this.notification.add(
                this.state.userLang === "en"
                    ? `${res.deleted} conversation(s) deleted.`
                    : `${res.deleted} conversation(s) supprimee(s).`,
                { type: "success" });
            this.newChatSession();
            this.state.chatSessions = [];
        } catch {
            this.notification.add(
                this.state.userLang === "en"
                    ? "Unable to delete conversations."
                    : "Impossible de supprimer les conversations.",
                { type: "warning" });
        }
    }

    /** Active le mode confirmation, avec auto-annulation apres 4 s. */
    _armConfirm(id) {
        this.state.confirmDeleteId = id;
        if (this._confirmTimer) {
            clearTimeout(this._confirmTimer);
        }
        this._confirmTimer = setTimeout(() => {
            this.state.confirmDeleteId = null;
        }, 4000);
    }

    _clearConfirm() {
        this.state.confirmDeleteId = null;
        if (this._confirmTimer) {
            clearTimeout(this._confirmTimer);
            this._confirmTimer = null;
        }
    }

    toggleSessions() {
        this.state.showSessions = !this.state.showSessions;
        if (this.state.showSessions) {
            this._refreshChatSessions();
        }
    }

    /** Palette pour les camemberts et courbes. */
    static CHART_COLORS = [
        "#6366f1", "#8b5cf6", "#ec4899", "#f59e0b",
        "#10b981", "#06b6d4", "#ef4444", "#84cc16",
    ];

    /** Prepare les charts pour le rendu selon leur type. */
    _prepareCharts(charts) {
        const COLORS = this.constructor.CHART_COLORS;
        return (charts || []).map((c) => {
            const values = (c.values || []).map((v) => Number(v) || 0);
            const labels = (c.labels || []).map((l) => String(l));
            const type = c.type || "bar";
            const out = { type, title: c.title || "" };

            if (type === "pie") {
                const total = values.reduce((a, b) => a + b, 0) || 1;
                let acc = 0;
                const segs = [];
                const stops = [];
                values.forEach((v, i) => {
                    const pct = (v / total) * 100;
                    const color = COLORS[i % COLORS.length];
                    stops.push(`${color} ${acc.toFixed(2)}% ${(acc + pct).toFixed(2)}%`);
                    segs.push({
                        label: labels[i], value: v,
                        pct: Math.round(pct), color,
                    });
                    acc += pct;
                });
                out.gradient = `conic-gradient(${stops.join(", ")})`;
                out.segments = segs;
            } else if (type === "line") {
                // Normalise les points dans un viewBox 100 x 40.
                const max = Math.max(...values, 1);
                const min = Math.min(...values, 0);
                const range = max - min || 1;
                const n = values.length;
                const pts = values.map((v, i) => {
                    const x = n > 1 ? (i / (n - 1)) * 96 + 2 : 50;
                    const y = 36 - ((v - min) / range) * 32;
                    return { x: x.toFixed(1), y: y.toFixed(1) };
                });
                out.points = pts.map((p) => `${p.x},${p.y}`).join(" ");
                out.dots = pts.map((p, i) => ({
                    x: p.x, y: p.y, label: labels[i], value: values[i],
                }));
                out.firstLabel = labels[0] || "";
                out.lastLabel = labels[labels.length - 1] || "";
                out.maxValue = max;
            } else {
                // bar (defaut)
                const max = Math.max(...values, 1);
                out.rows = labels.map((label, i) => ({
                    label,
                    value: values[i],
                    pct: Math.round((values[i] / max) * 100),
                }));
            }
            return out;
        });
    }

    /** Prepare les tableaux (validation legere cote client). */
    _prepareTables(tables) {
        return (tables || [])
            .filter((t) => t && Array.isArray(t.headers) && Array.isArray(t.rows))
            .map((t) => ({
                title: t.title || "",
                headers: t.headers.map((h) => String(h)),
                rows: t.rows.map((r) => r.map((cell) => String(cell))),
            }));
    }

    /** Valeur max d'un chart (pour normaliser les barres). */
    chartMax(chart) {
        const vals = (chart.values || []).map((v) => Number(v) || 0);
        return Math.max(...vals, 1);
    }

    _difficultyDistribution() {
        if (this.state.difficultyMode !== "custom") {
            return null;
        }
        return {
            easy: Number(this.state.diffEasy) || 0,
            medium: Number(this.state.diffMedium) || 0,
            hard: Number(this.state.diffHard) || 0,
        };
    }

    async _sendQuestions(text) {
        this.state.loading = true;
        try {
            const params = {
                source_type: this.state.sourceType,
                count: this.state.count,
                question_type: this.state.questionType,
                cognitive_type: this.state.cognitiveType || false,
                category_id: this.state.categoryId || false,
                difficulty_distribution: this._difficultyDistribution(),
                user_prompt: text,
            };
            if (this.state.sourceType === "course") {
                params.source_course_id = this.state.courseId || false;
            } else if (this.state.sourceType === "text") {
                params.source_text = text;
            } else {
                params.topic = text;
            }
            const res = await rpc("/digii_exam_ai_agent/generate_questions", params);
            if (res.error) {
                this._pushAssistant("⚠ " + res.error);
            } else if (res.questions && res.questions.length) {
                this._pushAssistant(
                    `Voici **${res.questions.length} question(s)** proposee(s). ` +
                        "Approuvez celles qui vous conviennent : elles entreront alors " +
                        "dans la banque."
                );
                this._pushQuestions(res.questions);
            } else {
                this._pushAssistant("Aucune question n'a pu etre generee.");
            }
        } catch (err) {
            this._pushAssistant("⚠ Une erreur est survenue lors de la generation.");
        } finally {
            this.state.loading = false;
        }
    }

    async _sendRules(text) {
        const surveyId = this.state.surveyId;
        if (!surveyId) {
            this._pushAssistant(
                "Selectionnez d'abord un examen cible dans le menu ci-dessus."
            );
            return;
        }
        this.state.loading = true;
        try {
            const res = await rpc("/digii_exam_ai_agent/generate_rules", {
                survey_id: surveyId,
                description: text,
            });
            if (res.error) {
                this._pushAssistant("⚠ " + res.error);
            } else {
                if (res.notes) {
                    this._pushAssistant(res.notes);
                }
                if (res.rules && res.rules.length) {
                    this._pushRules(res.notes || "", res.rules);
                } else {
                    this._pushAssistant("Aucune regle n'a pu etre proposee.");
                }
            }
        } catch (err) {
            this._pushAssistant("⚠ Une erreur est survenue lors de la generation des regles.");
        } finally {
            this.state.loading = false;
        }
    }

    // ----------------------------------------------------------------
    // Actions sur les cartes question
    // ----------------------------------------------------------------

    _findQuestionCard(qid) {
        for (const msg of this.state.messages) {
            if (msg.type === "questions") {
                const card = msg.cards.find((c) => c.id === qid);
                if (card) {
                    return { msg, card };
                }
            }
        }
        return {};
    }

    onApproveQuestion = async (qid) => {
        const res = await rpc("/digii_exam_ai_agent/review_action", {
            question_id: qid,
            action: "approve",
        });
        if (res.error) {
            this.notification.add(res.error, { type: "danger" });
            return;
        }
        const { card } = this._findQuestionCard(qid);
        if (card) {
            card.validation_state = "approved";
        }
        this.notification.add("Question ajoutee a la banque.", { type: "success" });
    };

    onRejectQuestion = async (qid) => {
        const res = await rpc("/digii_exam_ai_agent/review_action", {
            question_id: qid,
            action: "reject",
        });
        if (res.error) {
            this.notification.add(res.error, { type: "danger" });
            return;
        }
        const { msg } = this._findQuestionCard(qid);
        if (msg) {
            msg.cards = msg.cards.filter((c) => c.id !== qid);
        }
    };

    onEditQuestion = async (qid, payload) => {
        const res = await rpc("/digii_exam_ai_agent/review_action", {
            question_id: qid,
            action: "edit",
            payload,
        });
        if (res.error) {
            this.notification.add(res.error, { type: "danger" });
            return;
        }
        const { msg, card } = this._findQuestionCard(qid);
        if (msg && res.question) {
            const idx = msg.cards.findIndex((c) => c.id === qid);
            if (idx >= 0) {
                msg.cards[idx] = res.question;
            }
        }
    };

    onRegenerateQuestion = async (qid, instruction) => {
        const res = await rpc("/digii_exam_ai_agent/review_action", {
            question_id: qid,
            action: "regenerate",
            payload: { instruction },
        });
        if (res.error) {
            this.notification.add(res.error, { type: "danger" });
            return;
        }
        const { msg } = this._findQuestionCard(qid);
        if (msg && res.question) {
            const idx = msg.cards.findIndex((c) => c.id === qid);
            if (idx >= 0) {
                msg.cards[idx] = res.question;
            }
        }
    };

    // ----------------------------------------------------------------
    // Actions sur les cartes regle
    // ----------------------------------------------------------------

    _findRuleCard(rid) {
        for (const msg of this.state.messages) {
            if (msg.type === "rules") {
                const card = msg.cards.find((c) => c.id === rid);
                if (card) {
                    return { msg, card };
                }
            }
        }
        return {};
    }

    onAcceptRule = async (rid) => {
        const res = await rpc("/digii_exam_ai_agent/accept_rule", {
            proposal_id: rid,
        });
        if (res.error) {
            this.notification.add(res.error, { type: "danger" });
            return;
        }
        const { card } = this._findRuleCard(rid);
        if (card && res.proposal) {
            Object.assign(card, res.proposal);
        }
        this.notification.add("Regle ajoutee a l'examen.", { type: "success" });
    };

    onRejectRule = async (rid) => {
        const res = await rpc("/digii_exam_ai_agent/reject_rule", {
            proposal_id: rid,
        });
        if (res.error) {
            this.notification.add(res.error, { type: "danger" });
            return;
        }
        const { msg } = this._findRuleCard(rid);
        if (msg) {
            msg.cards = msg.cards.filter((c) => c.id !== rid);
        }
    };

    // ----------------------------------------------------------------
    // Chips contextuels
    // ----------------------------------------------------------------

    get chips() {
        if (this.state.mode === "rules") {
            return [
                "Examen final équilibré de 30 questions",
                "20 questions, surtout du niveau moyen",
                "Répartis 50% théorie / 50% pratique",
                "Un examen court de 10 questions faciles",
            ];
        }
        if (this.state.mode === "assistant") {
            if (this.state.userLang === "en") {
                return [
                    "Which exam has the best pass rate?",
                    "Compare enrollments across my courses",
                    "Summarize high-risk proctoring sessions",
                    "Is my question bank well balanced?",
                ];
            }
            return [
                "Quel examen a le meilleur taux de réussite ?",
                "Compare les inscriptions de mes cours",
                "Résume les sessions de proctoring à risque",
                "Ma banque de questions est-elle équilibrée ?",
            ];
        }
        return [
            "Génère des questions sur ce sujet",
            "Des questions de mémoire (définitions)",
            "Des questions d'application pratique",
            "Des questions d'analyse, niveau difficile",
        ];
    }
}
