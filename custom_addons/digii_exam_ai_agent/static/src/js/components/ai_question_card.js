/** @odoo-module **/
import { Component, useState } from "@odoo/owl";

export class AiQuestionCard extends Component {
    static template = "digii_exam_ai_agent.AiQuestionCard";
    static props = {
        question: Object,
        onApprove: Function,
        onReject: Function,
        onRegenerate: Function,
        onEdit: Function,
    };

    setup() {
        this.state = useState({
            busy: false,
            showRegen: false,
            regenText: "",
            editing: false,
            editTitle: this.props.question.title,
        });
    }

    get q() {
        return this.props.question;
    }

    get difficultyClass() {
        return (
            {
                easy: "o_ai_badge_easy",
                medium: "o_ai_badge_medium",
                hard: "o_ai_badge_hard",
            }[this.q.difficulty] || "o_ai_badge_neutral"
        );
    }

    async approve() {
        this.state.busy = true;
        await this.props.onApprove(this.q.id);
        this.state.busy = false;
    }

    async reject() {
        this.state.busy = true;
        await this.props.onReject(this.q.id);
        this.state.busy = false;
    }

    toggleRegen() {
        this.state.showRegen = !this.state.showRegen;
    }

    async submitRegen() {
        const text = this.state.regenText.trim();
        if (!text) {
            return;
        }
        this.state.busy = true;
        await this.props.onRegenerate(this.q.id, text);
        this.state.showRegen = false;
        this.state.regenText = "";
        this.state.busy = false;
    }

    toggleEdit() {
        this.state.editing = !this.state.editing;
        this.state.editTitle = this.q.title;
    }

    async saveEdit() {
        const title = this.state.editTitle.trim();
        if (!title) {
            return;
        }
        this.state.busy = true;
        await this.props.onEdit(this.q.id, { title });
        this.state.editing = false;
        this.state.busy = false;
    }
}
