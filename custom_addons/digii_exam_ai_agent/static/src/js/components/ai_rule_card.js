/** @odoo-module **/
import { Component, useState } from "@odoo/owl";

export class AiRuleCard extends Component {
    static template = "digii_exam_ai_agent.AiRuleCard";
    static props = {
        rule: Object,
        onAccept: Function,
        onReject: Function,
    };

    setup() {
        this.state = useState({ busy: false });
    }

    get r() {
        return this.props.rule;
    }

    async accept() {
        this.state.busy = true;
        await this.props.onAccept(this.r.id);
        this.state.busy = false;
    }

    async reject() {
        this.state.busy = true;
        await this.props.onReject(this.r.id);
        this.state.busy = false;
    }
}
