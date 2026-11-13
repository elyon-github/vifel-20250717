/** @odoo-module **/
// List footer / group totals: round half-up (Odoo's float_round) before
// formatting. Odoo 17 formats float totals with Number.toFixed, which rounds
// the binary float: the Pallet Breakdown of M/WR/10648 summed to 6531.165
// (stored as 6531.16499...) and showed 6,531.16, while the Picklist and WR
// reports print 6,531.17. Only the registry "float" formatter is wrapped;
// list aggregates use it, single field values (FloatField) do not.

import { registry } from "@web/core/registry";
import { roundDecimals } from "@web/core/utils/numbers";

const formatters = registry.category("formatters");
const coreFormatFloat = formatters.get("float");

function vifelFormatFloatHalfUp(value, options = {}) {
    if (typeof value === "number" && isFinite(value) && !options.humanReadable) {
        const digits =
            options.digits && options.digits[1] !== undefined ? options.digits[1] : 2;
        value = roundDecimals(value, digits);
    }
    return coreFormatFloat(value, options);
}

formatters.add("float", vifelFormatFloatHalfUp, { force: true });
