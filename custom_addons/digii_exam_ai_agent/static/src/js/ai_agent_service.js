/** @odoo-module **/
import { registry } from "@web/core/registry";
import { AiAgentPanel } from "./ai_agent_panel";

/**
 * Service qui ouvre le panneau IA en overlay (drawer) par-dessus la vue
 * courante, sans navigation. Un seul panneau a la fois.
 */
export const aiAgentService = {
    dependencies: ["overlay"],
    start(env, { overlay }) {
        let remove = null;

        function open(props = {}) {
            if (remove) {
                remove();
                remove = null;
            }
            remove = overlay.add(AiAgentPanel, {
                ...props,
                close: () => {
                    if (remove) {
                        remove();
                        remove = null;
                    }
                },
            });
        }

        return { open };
    },
};

registry.category("services").add("digii_ai_agent", aiAgentService);
