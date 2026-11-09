/** @odoo-module **/
/*
 * Odoo 19 shows dates as "Jun 1, 2025" and DROPS THE YEAR when the date is in
 * the current year ("Jan 1"), e.g. Production / Expiration Date in the
 * Inventory Overview. Odoo 17 always showed the full numeric date
 * (01/01/2026). Default every date / datetime display back to the numeric
 * format; a view that sets options="{'numeric': ...}" explicitly still wins.
 * Display only: no stored value changes.
 */
import { registry } from "@web/core/registry";
import { exprToBoolean } from "@web/core/utils/strings";
import "@web/views/fields/formatters";
import "@web/views/fields/datetime/datetime_field";
import "@web/views/fields/datetime/list_datetime_field";

const formatters = registry.category("formatters");
for (const key of ["date", "datetime"]) {
    if (!formatters.contains(key)) {
        continue;
    }
    const original = formatters.get(key);
    const patched = (value, options = {}) =>
        original(value, { ...options, numeric: options.numeric ?? true });
    patched.extractOptions = (info) => ({
        ...(original.extractOptions ? original.extractOptions(info) : {}),
        numeric: exprToBoolean(info.options?.numeric ?? true),
    });
    formatters.add(key, patched, { force: true });
}

const fields = registry.category("fields");
for (const key of ["date", "datetime", "daterange", "list.date", "list.datetime", "list.daterange"]) {
    if (!fields.contains(key)) {
        continue;
    }
    const field = fields.get(key);
    if (!field.extractProps) {
        continue;
    }
    const originalExtract = field.extractProps;
    fields.add(
        key,
        {
            ...field,
            extractProps: (info, dynamicInfo) => {
                const props = originalExtract(info, dynamicInfo);
                if (info.options?.numeric === undefined && "numeric" in props) {
                    props.numeric = true;
                }
                return props;
            },
        },
        { force: true }
    );
}
