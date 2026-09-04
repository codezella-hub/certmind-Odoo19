/** @odoo-module **/
import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

/**
 * Bouton systray "Assistant IA" : point d'entree universel vers le panneau,
 * visible en haut a droite du back-office pour les membres du groupe IA.
 */
export class AiAgentSystray extends Component {
    static template = "digii_exam_ai_agent.AiAgentSystray";
    static props = {};

    setup() {
        this.aiAgent = useService("digii_ai_agent");
    }

    onClick() {
        this.aiAgent.open({ defaultMode: "questions" });
    }
}

registry.category("systray").add(
    "digii_exam_ai_agent.systray",
    { Component: AiAgentSystray },
    { sequence: 50 }
);
