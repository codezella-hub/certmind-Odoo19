/** @odoo-module **/

import { registry }    from "@web/core/registry";
import { rpc }         from "@web/core/network/rpc";
import { useService }  from "@web/core/utils/hooks";
import { Component, onMounted, onWillUnmount, useRef, useState } from "@odoo/owl";
import { loadJS }      from "@web/core/assets";
import { Layout }      from "@web/search/layout";

class DigiiLmsDashboard extends Component {
    static template = "digii_lms.Dashboard";
    static components = { Layout };
    static props = ["*"];

    setup() {
        this.action = useService("action");
        this.display = { controlPanel: {} };

        this.state = useState({
            loading: true,
            stats: {
                total_courses: 0,       published_courses: 0,
                unpublished_courses: 0, total_slides: 0,
                published_slides: 0,    total_learners: 0,
                completed_learners: 0,  total_categories: 0,
                total_views: 0,
            },
            data: null,
        });

        this.chartRefs = {
            categories: useRef("chartCategories"),
            slideTypes: useRef("chartSlideTypes"),
            difficulty: useRef("chartDifficulty"),
            status:     useRef("chartStatus"),
            languages:  useRef("chartLanguages"),
            topCourses: useRef("chartTopCourses"),
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

            // UN SEUL appel vers notre controller HTTP → plus de 404
            const result = await rpc("/digii/dashboard/data", {});

            Object.assign(this.state.stats, result.kpi);
            this.state.data    = result;
            this.state.loading = false;

            setTimeout(() => this._renderAllCharts(), 80);
        } catch (err) {
            console.error("Dashboard error:", err);
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

        if (d.courses_by_category?.length)
            this._make("categories", "pie",
                d.courses_by_category.map(x => x.name),
                [{ data: d.courses_by_category.map(x => x.count),
                   backgroundColor: C, borderWidth: 3, borderColor: "#fff", hoverOffset: 8 }],
                { plugins: { legend: { position: "right" } } });

        if (d.slide_types?.length)
            this._make("slideTypes", "bar",
                d.slide_types.map(x => x.label),
                [{ label: "Leçons", data: d.slide_types.map(x => x.count),
                   backgroundColor: C.map(c => c + "CC"), borderColor: C,
                   borderWidth: 2, borderRadius: 10, borderSkipped: false }],
                { plugins: { legend: { display: false } },
                  scales: { y: { beginAtZero: true, grid: { color: "#F3F4F6" } },
                            x: { grid: { display: false } } } });

        if (d.difficulty_data?.length)
            this._make("difficulty", "doughnut",
                d.difficulty_data.map(x => x.label),
                [{ data: d.difficulty_data.map(x => x.count),
                   backgroundColor: ["#10B981","#F59E0B","#EF4444","#8B5CF6"],
                   borderWidth: 3, borderColor: "#fff" }],
                { cutout: "70%", plugins: { legend: { position: "bottom" } } });

        if (d.status_data?.length)
            this._make("status", "doughnut",
                d.status_data.map(x => x.label),
                [{ data: d.status_data.map(x => x.count),
                   backgroundColor: ["#6366F1","#F59E0B","#3B82F6","#10B981"],
                   borderWidth: 3, borderColor: "#fff" }],
                { cutout: "70%", plugins: { legend: { position: "bottom" } } });

        if (d.language_data?.length)
            this._make("languages", "bar",
                d.language_data.map(x => x.label),
                [{ label: "Cours", data: d.language_data.map(x => x.count),
                   backgroundColor: "#EF4444CC", borderColor: "#EF4444",
                   borderWidth: 2, borderRadius: 10, borderSkipped: false }],
                { plugins: { legend: { display: false } },
                  scales: { y: { beginAtZero: true, grid: { color: "#F3F4F6" } },
                            x: { grid: { display: false } } } });

        if (d.top_courses?.length)
            this._make("topCourses", "bar",
                d.top_courses.map(x => x.name),
                [
                    { label: "Inscrits",  data: d.top_courses.map(x => x.learners),
                      backgroundColor: "#4F46E5CC", borderColor: "#4F46E5",
                      borderWidth: 2, borderRadius: 8 },
                    { label: "Complétés", data: d.top_courses.map(x => x.completed),
                      backgroundColor: "#10B981CC", borderColor: "#10B981",
                      borderWidth: 2, borderRadius: 8 },
                ],
                { indexAxis: "y",
                  plugins: { legend: { position: "top" } },
                  scales: { x: { beginAtZero: true, grid: { color: "#F3F4F6" } },
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
    _nav(id) { this.action.doAction(id); }
    goToCourses()    { this._nav("digii_lms.action_digii_slide_channel"); }
    goToSlides()     { this._nav("digii_lms.action_digii_slide_slide"); }
    goToLearners()   { this._nav("digii_lms.action_digii_slide_channel_partner"); }
    goToCategories() { this._nav("digii_lms.action_digii_course_category"); }
}

registry.category("actions").add("digii_lms_dashboard", DigiiLmsDashboard);
