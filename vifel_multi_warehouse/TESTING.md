# Testing — vifel_multi_warehouse

## Run

```bash
# whole module (Windows: use C:\Odoo17E\python\python.exe)
python odoo-bin -c odoo.conf -d <test_db> -i vifel_multi_warehouse --test-enable \
       --test-tags /vifel_multi_warehouse --stop-after-init --log-level=test

# one class
python odoo-bin -c odoo.conf -d <test_db> -u vifel_multi_warehouse --test-enable \
       --test-tags :TestWarehouseRecordRules --stop-after-init

# one method
python odoo-bin -c odoo.conf -d <test_db> -u vifel_multi_warehouse --test-enable \
       --test-tags :TestPartnerGuards.test_merge_across_warehouses_rejected --stop-after-init
```

Use a **disposable database** — the suite creates manual (Studio-style) fields on `res.partner`
in `setUpClass` to mirror production (`x_studio_warehouse`, `x_studio_client_unique_code_1`).

## Coverage

| Behavior | Test |
|---|---|
| Warehouses assigned directly on the user | `TestUserWarehouses.test_assign_warehouses` |
| default ∈ allowed accepted | `test_default_within_allowed_ok` |
| default ∉ allowed rejected | `test_default_outside_allowed_raises` |
| default with empty allowed accepted | `test_default_without_allowed_ok` |
| WH-B user can't see WH-A picking | `TestWarehouseRecordRules.test_restricted_user_cannot_see_other_warehouse_picking` |
| WH-B user can't see WH-A quant | `test_restricted_user_cannot_see_other_warehouse_quant` |
| WH-B user can't see WH-A location | `test_restricted_user_cannot_see_other_warehouse_location` |
| WH-B user sees own warehouse records | `test_restricted_user_sees_own_warehouse` |
| Warehouse list scoped to allowed | `test_warehouse_list_is_scoped` |
| Warehouse-less records stay visible | `test_warehouse_less_records_stay_visible` |
| Empty allowed list = unrestricted (admin/rollout) | `test_empty_allowed_list_is_unrestricted` |
| Client code without warehouse rejected | `TestPartnerGuards.test_client_without_warehouse_rejected` |
| Client with warehouse accepted | `test_client_with_warehouse_ok` |
| Clearing a client's warehouse rejected | `test_clearing_warehouse_on_client_rejected` |
| Warehouse change, no history → allowed | `test_warehouse_change_without_history_ok` |
| Warehouse change after done picking → rejected | `test_warehouse_change_with_history_rejected` |
| Migration bypass context works | `test_warehouse_change_with_bypass_context_ok` |
| Settings admin may change | `test_warehouse_change_as_settings_admin_ok` |
| Cross-warehouse merge rejected | `test_merge_across_warehouses_rejected` |
| Same-warehouse merge still works | `test_merge_same_warehouse_allowed` |

Not covered here (by design): PKR/audit/history record rules (need those modules' data — validated
on the staging clone), and the PKR-history immutability trigger.

## Prerequisites
- Dependencies installed: `stock`, `pallet_kilos_record_model`, `pallet_series_audit`,
  `stock_quant_history` (module depends pull them in). No demo data required.
