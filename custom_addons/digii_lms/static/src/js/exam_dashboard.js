/** @odoo-module **/

import { registry }    from "@web/core/registry";
import { rpc }         from "@web/core/network/rpc";
import { useService }  from "@web/core/utils/hooks";
import { Component, onMounted, onWillUnmount, useRef, useState } from "@odoo/owl";
import { loadJS }      from "@web/core/assets";
import { Layout }      from "@web/search/layout";

class DigiiExamDashboard extends Component {
    static template = "digii_lms.ExamDashboard";
    static components = { Layout };
    static props = ["*"];

    setup() {
        this.action = useService("action");
        // Affiche le control panel Odoo (breadcrumb) + zone .o_content scrollable
        this.display = { controlPanel: {} };

        this.state = useState({
            loading: true,
            stats: {
                total_exams: 0,    proctored_exams: 0,
                certified_exams: 0, total_attempts: 0,
                in_progress: 0,    passed_attempts: 0,
                pass_rate: 0,      avg_score: 0,
                cert_approved: 0,  cert_pending: 0,
                sessions_total: 0, sessions_with_video: 0,
                bank_questions: 0,
            },
            data: null,
        });

        this.chartRefs = {
            examType:      useRef("chartExamType"),
            results:       useRef("chartResults"),
            certStatus:    useRef("chartCertStatus"),
            sessionStatus: useRef("chartSessionStatus"),
            topAttempts:   useRef("chartTopAttempts"),
            avgScore:      useRef("chartAvgScore"),
        };
        this.charts = {};

        onMounted(async () => await this._loadData());
        onWillUnmount(() => this._destroyAll());
    }

    _destroyAll() {
        Object.values(this.charts).forEach(c => { try { c.destroy(); } catch (_) {} });
        this.charts = {};
    }

    // ── Chargement ────────────────────────────────────────────────────────────
    async _loadData() {
        this.state.loading = true;
        try {
            await loadJS("https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js");

            const result = await rpc("/digii/exam/dashboard/data", {});

            Object.assign(this.state.stats, result.kpi);
            this.state.data    = result;
            this.state.loading = false;

            setTimeout(() => this._renderAllCharts(), 80);
        } catch (err) {
            console.error("Exam dashboard error:", err);
            this.state.loading = false;
        }
    }

    // ── Rendu Charts ─────────────────────────────────────────────────────────
    _renderAllCharts() {
        const d = this.state.data;
        if (!d) return;

        const C = [
            "#4F46E5","#7C3AED","#EC4899","#F59E0B",
            "#10B981","#3B82F6","#EF4444","#06B6D4",
        ];

        if (d.exam_type_data?.length)
            this._make("examType", "doughnut",
                d.exam_type_data.map(x => x.label),
                [{ data: d.exam_type_data.map(x => x.count),
                   backgroundColor: ["#7C3AED", "#3B82F6"],
                   borderWidth: 3, borderColor: "#fff" }],
                { cutout: "70%", plugins: { legend: { position: "bottom" } } });

        if (d.results_data?.length)
            this._make("results", "doughnut",
                d.results_data.map(x => x.label),
                [{ data: d.results_data.map(x => x.count),
                   backgroundColor: ["#10B981", "#EF4444"],
                   borderWidth: 3, borderColor: "#fff" }],
                { cutout: "70%", plugins: { legend: { position: "bottom" } } });

        if (d.cert_status_data?.length)
            this._make("certStatus", "doughnut",
                d.cert_status_data.map(x => x.label),
                [{ data: d.cert_status_data.map(x => x.count),
                   backgroundColor: ["#10B981", "#F59E0B", "#EF4444"],
                   borderWidth: 3, borderColor: "#fff" }],
                { cutout: "70%", plugins: { legend: { position: "bottom" } } });

        if (d.session_status_data?.length)
            this._make("sessionStatus", "pie",
                d.session_status_data.map(x => x.label),
                [{ data: d.session_status_data.map(x => x.count),
                   backgroundColor: C, borderWidth: 3, borderColor: "#fff", hoverOffset: 8 }],
                { plugins: { legend: { position: "right" } } });

        if (d.top_attempts_data?.length)
            this._make("topAttempts", "bar",
                d.top_attempts_data.map(x => x.name),
                [{ label: "Tentatives", data: d.top_attempts_data.map(x => x.count),
                   backgroundColor: "#4F46E5CC", borderColor: "#4F46E5",
                   borderWidth: 2, borderRadius: 10, borderSkipped: false }],
                { plugins: { legend: { display: false } },
                  scales: { y: { beginAtZero: true, grid: { color: "#F3F4F6" } },
                            x: { grid: { display: false } } } });

        if (d.avg_by_exam?.length)
            this._make("avgScore", "bar",
                d.avg_by_exam.map(x => x.name),
                [{ label: "Score moyen (%)", data: d.avg_by_exam.map(x => x.avg),
                   backgroundColor: "#10B981CC", borderColor: "#10B981",
                   borderWidth: 2, borderRadius: 8 }],
                { indexAxis: "y",
                  plugins: { legend: { display: false } },
                  scales: { x: { beginAtZero: true, max: 100, grid: { color: "#F3F4F6" } },
                            y: { grid: { display: false } } } });
    }

    _make(key, type, labels, datasets, extra = {}) {
        const ref = this.chartRefs[key];
        if (!ref?.el) return;
        if (this.charts[key]) { this.charts[key].destroy(); }
        this.charts[key] = new Chart(ref.el, {
            type,
            data: { labels, datasets },
            options: {
                responsive: true, maintainAspectRatio: true,
                animation: { duration: 700, easing: "easeInOutQuart" },
                plugins: {
                    legend: { position: "bottom" },
                    tooltip: { backgroundColor: "#1F2937", titleColor: "#F9FAFB",
                               bodyColor: "#D1D5DB", padding: 12, cornerRadius: 8 },
                },
                ...extra,
            },
        });
    }

    // ── Navigation ────────────────────────────────────────────────────────────
    goToExams()        { this.action.doAction("survey.action_survey_form"); }
    goToResults()      { this.action.doAction("survey.action_survey_user_input"); }
    goToCertificates() { this.action.doAction("digii_exam_manager.action_exam_certificate"); }
    goToProctoring()   { this.action.doAction("digii_exam_manager.action_exam_proctoring_session"); }
}

registry.category("actions").add("digii_lms_exam_dashboard", DigiiExamDashboard);
