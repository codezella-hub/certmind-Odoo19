/** @odoo-module **/
import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

/**
 * Widget bouton "Assistant IA" pour la fiche examen (survey.survey).
 * Ouvre le panneau pre-lie a l'examen courant, en mode co-pilote de regles.
 * Visible uniquement quand is_exam est coche.
 */
export class AiSurveyButton extends Component {
    static template = "digii_exam_ai_agent.AiSurveyButton";
    static props = {
        "*": true,
    };

    setup() {
        this.aiAgent = useService("digii_ai_agent");
    }

    get record() {
        return this.props.record;
    }

    get isExam() {
        const rec = this.record;
        return rec && rec.data && rec.data.is_exam;
    }

    onClick() {
        const rec = this.record;
        this.aiAgent.open({
            surveyId: rec && rec.resId ? rec.resId : false,
            surveyName: rec && rec.data ? rec.data.title || "" : "",
            defaultMode: "rules",
        });
    }
}

export const aiSurveyButton = {
    component: AiSurveyButton,
};

registry.category("view_widgets").add("digii_ai_assistant_button", aiSurveyButton);
