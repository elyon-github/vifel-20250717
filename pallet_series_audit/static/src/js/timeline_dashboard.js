/** @odoo-module */
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";

export class PalletSeriesTimeline extends Component {
    static template = "pallet_series_audit.TimelineDashboard";
    static props = { action: { type: Object, optional: true }, actionId: { type: Number, optional: true }, className: { type: String, optional: true }, "*": true };

    /* ------------------------------------------------------------------ */
    /*  Colour / icon helpers (static, shared across instances)            */
    /* ------------------------------------------------------------------ */
    static EVENT_COLORS = {
        assigned:         { bg: "#28a745", fg: "#fff", icon: "fa-plus-circle",    label: "Assigned" },
        pulled_from_pool: { bg: "#28a745", fg: "#fff", icon: "fa-download",       label: "Pulled from Pool" },
        generated_new:    { bg: "#28a745", fg: "#fff", icon: "fa-magic",          label: "Generated New" },
        synced:           { bg: "#17a2b8", fg: "#fff", icon: "fa-refresh",        label: "Synced" },
        restored:         { bg: "#17a2b8", fg: "#fff", icon: "fa-undo",           label: "Restored" },
        reassigned:       { bg: "#17a2b8", fg: "#fff", icon: "fa-exchange",       label: "Reassigned" },
        recycled:         { bg: "#17a2b8", fg: "#fff", icon: "fa-recycle",        label: "Recycled" },
        pallet_assigned:  { bg: "#6f42c1", fg: "#fff", icon: "fa-cube",           label: "Pallet Changed" },
        pushed_to_pool:   { bg: "#fd7e14", fg: "#fff", icon: "fa-upload",         label: "Pushed to Pool" },
        cleared:          { bg: "#dc3545", fg: "#fff", icon: "fa-times-circle",   label: "Cleared" },
        line_deleted:     { bg: "#dc3545", fg: "#fff", icon: "fa-trash",          label: "Line Deleted" },
    };

    static SOURCE_LABELS = {
        server_action:   "Assign Pallet Series (SA)",
        wizard:          "Magic Wizard",
        generate_lines:  "Generate Lines",
        write_override:  "Pallet Change",
        ondelete:        "Line Delete Handler",
        regenerate:      "Regenerate Move Lines",
        pool_operation:  "Pool Operation",
        system:          "System",
    };

    /* ------------------------------------------------------------------ */
    /*  Setup                                                              */
    /* ------------------------------------------------------------------ */
    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");

        this.state = useState({
            loading: true,
            auditId: null,
            pickingName: "",
            partnerName: "",
            pickingState: "",
            eventCount: 0,
            uniqueSeries: 0,
            currentLines: 0,
            currentSeries: 0,
            currentPallets: 0,
            linesWithoutSeries: 0,
            palletsPending: false,
            events: [],
            groupMode: "timeline",   // "timeline" | "series" | "line" | "pallet" | "user"
            filterType: "",          // "" = all
            filterSource: "",        // "" = all
            filterUser: "",          // "" = all, otherwise user_id[0] as string
            sortOrder: "desc",       // "desc" = latest first (default), "asc" = oldest first
            searchText: "",
            collapsedGroups: {},     // key -> true/false
        });

        const params = this.props.action.params || {};
        this.state.auditId = params.audit_id || false;

        onWillStart(() => this.loadData());
    }

    /* ------------------------------------------------------------------ */
    /*  Data loading                                                       */
    /* ------------------------------------------------------------------ */
    async loadData() {
        this.state.loading = true;
        if (!this.state.auditId) {
            this.state.loading = false;
            return;
        }

        try {
            /* header */
            const [header] = await this.orm.read(
                "pallet.series.audit",
                [this.state.auditId],
                [
                    "picking_name", "partner_id", "picking_state",
                    "event_count", "unique_series_count",
                    "current_line_count", "current_series_count",
                    "current_pallet_count", "lines_without_series",
                    "pallets_pending",
                ],
            );
            this.state.pickingName  = header.picking_name || "";
            this.state.partnerName  = header.partner_id ? header.partner_id[1] : "";
            this.state.pickingState = header.picking_state || "";
            this.state.eventCount   = header.event_count || 0;
            this.state.uniqueSeries = header.unique_series_count || 0;
            this.state.currentLines   = header.current_line_count || 0;
            this.state.currentSeries  = header.current_series_count || 0;
            this.state.currentPallets = header.current_pallet_count || 0;
            this.state.linesWithoutSeries = header.lines_without_series || 0;
            this.state.palletsPending = !!header.pallets_pending;

            /* events */
            const eventIds = await this.orm.search(
                "pallet.series.audit.line",
                [["audit_id", "=", this.state.auditId]],
                { order: "event_date desc, id desc" },
            );
            if (eventIds.length) {
                this.state.events = await this.orm.read(
                    "pallet.series.audit.line",
                    eventIds,
                    [
                        "event_date", "event_type", "source", "pallet_series_id",
                        "previous_series", "new_series", "line_number",
                        "result_package_name", "pool_delta", "pool_size_after",
                        "user_id", "notes",
                    ],
                );
            } else {
                this.state.events = [];
            }
        } catch (e) {
            console.error("PalletSeriesTimeline: failed to load data", e);
            this.state.events = [];
        }
        this.state.loading = false;
    }

    /* ------------------------------------------------------------------ */
    /*  Filtering                                                          */
    /* ------------------------------------------------------------------ */
    get filteredEvents() {
        let evts = this.state.events;
        if (this.state.filterType) {
            evts = evts.filter(e => e.event_type === this.state.filterType);
        }
        if (this.state.filterSource) {
            evts = evts.filter(e => e.source === this.state.filterSource);
        }
        if (this.state.filterUser) {
            const uid = parseInt(this.state.filterUser);
            evts = evts.filter(e => e.user_id && e.user_id[0] === uid);
        }
        if (this.state.searchText) {
            const q = this.state.searchText.toLowerCase();
            evts = evts.filter(e =>
                (e.pallet_series_id || "").toLowerCase().includes(q) ||
                (e.previous_series || "").toLowerCase().includes(q) ||
                (e.new_series || "").toLowerCase().includes(q) ||
                (e.result_package_name || "").toLowerCase().includes(q) ||
                (e.notes || "").toLowerCase().includes(q) ||
                String(e.line_number || "").includes(q)
            );
        }
        // Sort: data loaded as desc; flip if user wants asc
        if (this.state.sortOrder === "asc") {
            evts = [...evts].reverse();
        }
        return evts;
    }

    _groupBy(evts, keyFn) {
        const grouped = {};
        for (const ev of evts) {
            const key = keyFn(ev);
            if (!grouped[key]) grouped[key] = [];
            grouped[key].push(ev);
        }
        return grouped;
    }

    get filteredGrouped() {
        return this._groupBy(this.filteredEvents, ev => ev.pallet_series_id || "(no series)");
    }

    get filteredSeriesKeys() {
        return Object.keys(this.filteredGrouped).sort();
    }

    get groupedByLine() {
        return this._groupBy(this.filteredEvents, ev =>
            ev.line_number ? `Line #${ev.line_number}` : "(no line)"
        );
    }

    get lineKeys() {
        return Object.keys(this.groupedByLine).sort((a, b) => {
            const na = parseInt(a.replace(/\D/g, "")) || 0;
            const nb = parseInt(b.replace(/\D/g, "")) || 0;
            return na - nb;
        });
    }

    get groupedByPallet() {
        return this._groupBy(this.filteredEvents, ev =>
            ev.result_package_name || "(no pallet)"
        );
    }

    get palletKeys() {
        return Object.keys(this.groupedByPallet).sort();
    }

    get groupedByUser() {
        return this._groupBy(this.filteredEvents, ev =>
            ev.user_id ? ev.user_id[1] : "(unknown user)"
        );
    }

    get userKeys() {
        return Object.keys(this.groupedByUser).sort();
    }

    get eventTypes() {
        const types = new Set(this.state.events.map(e => e.event_type));
        return [...types].sort();
    }

    get sourceTypes() {
        const types = new Set(this.state.events.map(e => e.source));
        return [...types].sort();
    }

    get userList() {
        const map = {};
        for (const e of this.state.events) {
            if (e.user_id) map[e.user_id[0]] = e.user_id[1];
        }
        return Object.entries(map).sort((a, b) => a[1].localeCompare(b[1]));
    }

    /* ------------------------------------------------------------------ */
    /*  Summary stats                                                      */
    /* ------------------------------------------------------------------ */
    /* Plain-language verdict on the CURRENT document, shown above the log.
       COMP-2026-00048: a supervisor read "0 Pallets" plus 43 "Line Deleted"
       events as data loss on an RR that was already fully re-encoded.  The
       log is history; this states what the RR holds now. */
    get currentStateVerdict() {
        const lines = this.state.currentLines;
        const series = this.state.currentSeries;
        const blank = this.state.linesWithoutSeries;
        const name = this.state.pickingName || "This RR";

        if (!lines) {
            return {
                level: "danger",
                icon: "fa-exclamation-triangle",
                message: `${name} has no move lines right now. The events below are history — nothing on this document currently carries a pallet series.`,
            };
        }
        if (blank === lines) {
            return {
                level: "danger",
                icon: "fa-exclamation-triangle",
                message: `${name} has ${lines} line(s), none of which carry a pallet series. Run Assign Pallet Series to fix this.`,
            };
        }
        if (blank) {
            return {
                level: "warning",
                icon: "fa-exclamation-circle",
                message: `${name} has ${lines} line(s), but ${blank} of them carry no pallet series. Assign the missing series before validating.`,
            };
        }
        /* Note: series < lines is NOT a defect — several lines legitimately
           share one pallet series (different products or batches on the same
           pallet), so it is reported, never flagged. */
        const shared = series < lines
            ? ` ${series} distinct series are shared across those lines, which is normal.`
            : "";
        const pallets = this.state.palletsPending
            ? " Pallets are only created on validation, so the pallet count is blank until then."
            : "";
        return {
            level: "ok",
            icon: "fa-check-circle",
            message: `${name} currently holds ${lines} line(s), all carrying a pallet series.${shared} Any deletions below already happened and have since been re-encoded.${pallets}`,
        };
    }

    get summaryStats() {
        const evts = this.state.events;
        const byType = {};
        for (const ev of evts) {
            byType[ev.event_type] = (byType[ev.event_type] || 0) + 1;
        }
        // Pallet / line counts deliberately live on the header now: they are
        // read off the picking, not inferred from the log (COMP-2026-00048).
        return {
            byType,
            totalEvents: evts.length,
        };
    }

    /* ------------------------------------------------------------------ */
    /*  Formatting helpers used by the template                            */
    /* ------------------------------------------------------------------ */
    eventMeta(eventType) {
        return PalletSeriesTimeline.EVENT_COLORS[eventType] || {
            bg: "#6c757d", fg: "#fff", icon: "fa-question-circle", label: eventType,
        };
    }

    sourceLabel(source) {
        return PalletSeriesTimeline.SOURCE_LABELS[source] || source;
    }

    seriesArrow(ev) {
        if (ev.event_type === "pallet_assigned") {
            // For pallet change events, previous_series = old pallet name, new_series = new pallet name
            if (ev.previous_series && ev.new_series) {
                return `${ev.previous_series}  →  ${ev.new_series}`;
            }
            if (ev.new_series) return `→  ${ev.new_series}`;
            if (ev.previous_series) return `${ev.previous_series}  →  ∅`;
        }
        if (ev.previous_series && ev.new_series) {
            return `${ev.previous_series}  →  ${ev.new_series}`;
        }
        if (ev.new_series) return `→  ${ev.new_series}`;
        if (ev.previous_series) return `${ev.previous_series}  →  ∅`;
        return ev.pallet_series_id || "";
    }

    /** Odoo returns datetimes as "2026-03-20 08:43:12" with NO timezone suffix,
     *  meaning new Date() parses them as local time. We must force UTC parsing
     *  by appending 'Z', then add the +8 h offset. */
    _toUtc8(dt) {
        if (!dt) return null;
        // Normalize: replace space with 'T', ensure trailing 'Z' for UTC
        const iso = String(dt).replace(" ", "T").replace(/Z?$/, "Z");
        return new Date(new Date(iso).getTime() + (8 * 60 * 60 * 1000));
    }

    formatDate(dt) {
        const utc8 = this._toUtc8(dt);
        if (!utc8) return "";
        const pad = n => String(n).padStart(2, "0");
        return `${utc8.getUTCFullYear()}-${pad(utc8.getUTCMonth()+1)}-${pad(utc8.getUTCDate())} ${pad(utc8.getUTCHours())}:${pad(utc8.getUTCMinutes())}:${pad(utc8.getUTCSeconds())}`;
    }

    formatTime(dt) {
        const utc8 = this._toUtc8(dt);
        if (!utc8) return "";
        const pad = n => String(n).padStart(2, "0");
        return `${pad(utc8.getUTCHours())}:${pad(utc8.getUTCMinutes())}:${pad(utc8.getUTCSeconds())}`;
    }

    formatDateOnly(dt) {
        const utc8 = this._toUtc8(dt);
        if (!utc8) return "";
        const pad = n => String(n).padStart(2, "0");
        return `${utc8.getUTCFullYear()}-${pad(utc8.getUTCMonth()+1)}-${pad(utc8.getUTCDate())}`;
    }

    /* ------------------------------------------------------------------ */
    /*  UI Actions                                                         */
    /* ------------------------------------------------------------------ */
    setGroupMode(mode) {
        this.state.groupMode = mode;
    }

    setFilterType(ev) {
        this.state.filterType = ev.target.value;
    }

    setFilterSource(ev) {
        this.state.filterSource = ev.target.value;
    }

    setFilterUser(ev) {
        this.state.filterUser = ev.target.value;
    }

    setSortOrder(ev) {
        this.state.sortOrder = ev.target.value;
    }

    setSearchText(ev) {
        this.state.searchText = ev.target.value;
    }

    clearFilters() {
        this.state.filterType = "";
        this.state.filterSource = "";
        this.state.filterUser = "";
        this.state.searchText = "";
        this.state.sortOrder = "desc";
    }

    toggleGroup(key) {
        this.state.collapsedGroups[key] = !this.state.collapsedGroups[key];
    }

    isGroupCollapsed(key) {
        return !!this.state.collapsedGroups[key];
    }

    goBack() {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "pallet.series.audit",
            res_id: this.state.auditId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    quickFilter(eventType) {
        this.state.filterType = eventType;
        this.state.groupMode = "timeline";
    }
}

registry.category("actions").add("pallet_series_audit.timeline_dashboard", PalletSeriesTimeline);
