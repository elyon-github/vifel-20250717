/** @odoo-module **/
/*
 * Dates and times show in numeric, 24-hour ("military") format, as on 17:
 *     date      02/05/2026
 *     datetime  02/05/2026 08:00:00
 *
 * Odoo 19 shows month names instead ("Feb 5, 2026, 5:50 AM", and drops the
 * year inside the current year). Here every date / datetime field and list
 * cell uses the user's language format instead - VIFEL's en_US is
 * %m/%d/%Y + %H:%M:%S (the 19.0.0.4.11 upgrade puts the 24-hour time back:
 * the 17 -> 19 upgrade had reset it to %I:%M:%S %p). Typing a date into a
 * field is parsed with that same format. Display only: no stored value changes.
 */
import { patch } from "@web/core/utils/patch";
import { registry } from "@web/core/registry";
import { DateTimeField } from "@web/views/fields/datetime/datetime_field";
import { formatDate, formatDateTime } from "@web/core/l10n/dates";
import "@web/views/fields/formatters";

function numericDate(value) {
    return value ? formatDate(value) : "";
}

function numericDateTime(value, options = {}) {
    if (!value) {
        return "";
    }
    if (options.showTime === false) {
        return formatDate(value.setZone(options.tz || "default"));
    }
    return formatDateTime(value, { tz: options.tz });
}

// List cells, group headers, kanban, exports: the formatter registry.
const formatters = registry.category("formatters");
for (const [key, numeric] of [["date", numericDate], ["datetime", numericDateTime]]) {
    if (!formatters.contains(key)) {
        continue;
    }
    const original = formatters.get(key);
    const patched = (value, options = {}) => numeric(value, options);
    if (original.extractOptions) {
        patched.extractOptions = original.extractOptions;
    }
    formatters.add(key, patched, { force: true });
}

// Date / datetime field widgets (form and list).
patch(DateTimeField.prototype, {
    getFormattedValue(valueIndex) {
        const value = this.values[valueIndex];
        if (!value) {
            return "";
        }
        if (this.field.type === "date") {
            return numericDate(value);
        }
        return numericDateTime(value, { showTime: this.props.showTime });
    },
});
