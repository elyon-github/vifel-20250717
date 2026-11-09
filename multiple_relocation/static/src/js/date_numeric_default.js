/** @odoo-module **/
/*
 * Odoo 19 shows dates as "Jun 1, 2025" but DROPS THE YEAR when the date is in
 * the current year ("Jan 1"), e.g. Production / Expiration Date in the
 * Inventory Overview. VIFEL wants the month name AND the year always:
 * "Feb 10, 2026". Same month-name style as Odoo 19, the year is just never
 * removed. A view that asks for options="{'numeric': True}" still gets the
 * numeric format. Display only: no stored value changes.
 */
import { patch } from "@web/core/utils/patch";
import { registry } from "@web/core/registry";
import { DateTimeField } from "@web/views/fields/datetime/datetime_field";
import "@web/views/fields/formatters";

const { DateTime } = luxon;

function dateWithYear(value) {
    return value ? value.toLocaleString(DateTime.DATE_MED) : "";
}

function dateTimeWithYear(value, options = {}) {
    if (!value) {
        return "";
    }
    const format = { ...DateTime.DATETIME_MED_WITH_SECONDS };
    if (!options.showSeconds) {
        delete format.second;
    }
    if (options.showDate === false) {
        delete format.day;
        delete format.month;
        delete format.year;
    }
    if (options.showTime === false) {
        delete format.hour;
        delete format.minute;
    }
    return value.setZone(options.tz || "default").toLocaleString(format);
}

// List cells, group headers, exports: the formatter registry.
const formatters = registry.category("formatters");
for (const [key, withYear] of [["date", dateWithYear], ["datetime", dateTimeWithYear]]) {
    if (!formatters.contains(key)) {
        continue;
    }
    const original = formatters.get(key);
    const patched = (value, options = {}) =>
        options.numeric ? original(value, options) : withYear(value, options);
    if (original.extractOptions) {
        patched.extractOptions = original.extractOptions;
    }
    formatters.add(key, patched, { force: true });
}

// Date / datetime field widgets (form and list).
patch(DateTimeField.prototype, {
    getFormattedValue(valueIndex, numeric = this.props.numeric) {
        if (numeric) {
            return super.getFormattedValue(valueIndex, numeric);
        }
        const values = this.values;
        const value = values[valueIndex];
        if (!value) {
            return "";
        }
        if (this.field.type === "date") {
            return dateWithYear(value);
        }
        const { showSeconds, showTime } = this.props;
        const showDate =
            !showTime || valueIndex !== 1 || !values[0] || !values[0].hasSame(value, "day");
        return dateTimeWithYear(value, { showSeconds, showTime, showDate });
    },
});
