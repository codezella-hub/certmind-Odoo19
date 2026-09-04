/** @odoo-module **/
import { Component } from "@odoo/owl";
import { renderMarkdown } from "../markdown";

export class AiMessage extends Component {
    static template = "digii_exam_ai_agent.AiMessage";
    static props = {
        role: String, // 'user' | 'assistant'
        content: { type: String, optional: true },
    };

    get rendered() {
        return renderMarkdown(this.props.content || "");
    }
}
