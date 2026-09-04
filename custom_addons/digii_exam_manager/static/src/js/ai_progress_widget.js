/** @odoo-module **/
/**
 * Widget OWL : barre de progression temps reel de l'analyse IA.
 *
 * Affiche dans la fiche (certificat ou session) :
 *  - un bouton "Analyser la video" si pas encore analyse
 *  - une barre de progression animee avec % pendant l'analyse (polling 2s)
 *  - le score + niveau + alertes des que c'est termine, SANS recharger
 *
 * Le widget appelle la methode Python get_ai_progress() qui interroge le
 * microservice et renvoie {state, progress, risk_score, ...}.
 */
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component, useState, onWillStart, onWillUnmount } from "@odoo/owl";

const POLL_INTERVAL_MS = 2000; // interroge toutes les 2 secondes

export class AiProgressWidget extends Component {
    static template = "digii_exam_manager.AiProgressWidget";
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");

        this.state = useState({
            analysisState: "not_started", // not_started|processing|done|error
            progress: 0,
            riskScore: 0,
            riskLevel: "",
            alertsCount: 0,
            errorMsg: "",
            launching: false,
        });

        this._pollTimer = null;

        onWillStart(async () => {
            // Lit l'etat initial depuis l'enregistrement.
            this._readInitialState();
            // Si une analyse etait deja en cours, on reprend le polling.
            if (this.state.analysisState === "processing") {
                this._startPolling();
            }
        });

        onWillUnmount(() => this._stopPolling());
    }

    get record() {
        return this.props.record;
    }

    get modelName() {
        return this.record.resModel;
    }

    get recordId() {
        return this.record.resId;
    }

    _readInitialState() {
        const data = this.record.data;
        this.state.analysisState = data.ai_analysis_state || "not_started";
        this.state.riskScore = data.ai_risk_score || 0;
        this.state.riskLevel = data.ai_risk_level || "";
        this.state.alertsCount = data.ai_alerts_count || 0;
        if (this.state.analysisState === "done") {
            this.state.progress = 100;
        }
    }

    // ---- Actions ----

    async onAnalyzeClick() {
        // Il faut que l'enregistrement soit sauvegarde pour avoir un id.
        if (!this.recordId) {
            this.notification.add("Enregistrez d'abord la fiche.", {
                type: "warning",
            });
            return;
        }
        this.state.launching = true;
        this.state.errorMsg = "";
        try {
            await this.orm.call(this.modelName, "action_analyze_video", [
                [this.recordId],
            ]);
            this.state.analysisState = "processing";
            this.state.progress = 0;
            this._startPolling();
        } catch (err) {
            this.state.errorMsg =
                "Impossible de lancer l'analyse. Verifiez le service IA.";
            this.notification.add(this.state.errorMsg, { type: "danger" });
        } finally {
            this.state.launching = false;
        }
    }

    // ---- Polling ----

    _startPolling() {
        this._stopPolling();
        this._pollTimer = setInterval(() => this._poll(), POLL_INTERVAL_MS);
        // Un premier appel immediat pour ne pas attendre 2s.
        this._poll();
    }

    _stopPolling() {
        if (this._pollTimer) {
            clearInterval(this._pollTimer);
            this._pollTimer = null;
        }
    }

    async _poll() {
        if (!this.recordId) {
            return;
        }
        let result;
        try {
            result = await this.orm.call(this.modelName, "get_ai_progress", [
                [this.recordId],
            ]);
        } catch (err) {
            // Erreur reseau ponctuelle : on reessaiera au prochain tick.
            return;
        }

        this.state.analysisState = result.state;

        if (result.state === "processing") {
            this.state.progress = result.progress || this.state.progress;
        } else if (result.state === "done") {
            this.state.progress = 100;
            this.state.riskScore = result.risk_score || 0;
            this.state.riskLevel = result.risk_level || "";
            this.state.alertsCount = result.alerts_count || 0;
            this._stopPolling();
            this.notification.add(
                `Analyse terminee : score ${this.state.riskScore}/100`,
                { type: "success" }
            );
            // Recharge les donnees du form pour afficher rapport/textes.
            await this.record.load();
        } else if (result.state === "error") {
            this.state.errorMsg = result.error || "Erreur d'analyse.";
            this._stopPolling();
        } else if (result.state === "not_started") {
            // Tache perdue (service redemarre).
            this.state.progress = 0;
            if (result.error) {
                this.state.errorMsg = result.error;
            }
            this._stopPolling();
        }
    }

    // ---- Helpers d'affichage ----

    get riskLevelLabel() {
        const labels = {
            none: "Aucun risque",
            suspect: "Suspect",
            high: "Tres suspect",
            very_high: "Triche probable",
        };
        return labels[this.state.riskLevel] || "";
    }

    get riskColorClass() {
        const map = {
            none: "text-success",
            suspect: "text-warning",
            high: "text-danger",
            very_high: "text-danger",
        };
        return map[this.state.riskLevel] || "text-muted";
    }

    get progressBarClass() {
        if (this.state.riskLevel === "none") return "bg-success";
        if (this.state.riskLevel === "suspect") return "bg-warning";
        if (["high", "very_high"].includes(this.state.riskLevel))
            return "bg-danger";
        return "bg-primary";
    }
}

export const aiProgressWidget = {
    component: AiProgressWidget,
    supportedTypes: ["char", "selection"],
};

registry.category("fields").add("ai_progress_widget", aiProgressWidget);
