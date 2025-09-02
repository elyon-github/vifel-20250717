/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
/**
 * If your list_renderer.js is truly at "@web/views/list/list_renderer",
 * then use that path. Adjust if it's different in your system.
 */
import { ListRenderer } from "@web/views/list/list_renderer";
import { ListController } from "@web/views/list/list_controller";
/**
 * IMPORTANT: The new patch API in Odoo 17 does not allow
 * a second argument as the patch name. We pass only the object.
 */

console.log("🔥 Patch file loading!"); 
patch(ListController.prototype, {
    // Helper function to format numbers with commas
    formatNumberWithCommas(number) {
        return parseFloat(number).toLocaleString('en-US', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        });
    },
    
    // Cache for domain totals
    _domainTotals: null,
    
    // Method to fetch domain totals from server
    async fetchDomainTotals() {
        if (!this.model.root.isDomainSelected) {
            return null;
        }
        
        try {
            // Use readGroup for aggregation (Odoo 17 compatible)
            const result = await this.orm.readGroup(
                this.model.root.resModel,
                this.model.root.domain,
                ['x_studio_2nd_uom:sum', 'available_quantity:sum', 'x_studio_total_units:sum'],
                []
            );
            
            if (result && result.length > 0) {
                this._domainTotals = {
                    quantity: result[0].x_studio_2nd_uom || 0,
                    kg: result[0].available_quantity || 0,
                    packs: result[0].x_studio_total_units || 0
                };
            }
            
            // Get unique pallets count
            const palletResult = await this.orm.searchRead(
                this.model.root.resModel,
                this.model.root.domain,
                ['package_id']
            );
            
            const uniquePallets = new Set();
            palletResult.forEach(record => {
                const palletId = record.package_id;
                if (palletId) {
                    const palletValue = Array.isArray(palletId) ? palletId[0] : palletId;
                    if (palletValue) {
                        uniquePallets.add(palletValue);
                    }
                }
            });
            
            this._domainTotals.pallets = uniquePallets.size;
            return this._domainTotals;
            
        } catch (error) {
            console.error('Error fetching domain totals:', error);
            return null;
        }
    },
    
    // Add getter for selected quantity sum
    get selectedQuantitySum() {
        if (this.model.root.isDomainSelected) {
            if (this._domainTotals && this._domainTotals.quantity !== undefined) {
                return this.formatNumberWithCommas(this._domainTotals.quantity);
            }
            return "Loading...";
        }
        
        const selection = this.model.root.selection;
        if (!selection || selection.length === 0) {
            return "0.00";
        }
        
        const total = selection.reduce((sum, record) => {
            const qty = parseFloat(record.data.x_studio_2nd_uom) || 0;
            return sum + qty;
        }, 0);
        
        return this.formatNumberWithCommas(total);
    },
    
    // Add getter for selected KG sum
    get selectedKgSum() {
        if (this.model.root.isDomainSelected) {
            if (this._domainTotals && this._domainTotals.kg !== undefined) {
                return this.formatNumberWithCommas(this._domainTotals.kg);
            }
            return "Loading...";
        }
        
        const selection = this.model.root.selection;
        if (!selection || selection.length === 0) {
            return "0.00";
        }
        
        const total = selection.reduce((sum, record) => {
            const kg = parseFloat(record.data.available_quantity) || 0;
            return sum + kg;
        }, 0);
        
        return this.formatNumberWithCommas(total);
    },
    
    // Add getter for selected packs sum
    get selectedPacksSum() {
        if (this.model.root.isDomainSelected) {
            if (this._domainTotals && this._domainTotals.packs !== undefined) {
                return this.formatNumberWithCommas(this._domainTotals.packs);
            }
            return "Loading...";
        }
        
        const selection = this.model.root.selection;
        if (!selection || selection.length === 0) {
            return "0.00";
        }
        
        const total = selection.reduce((sum, record) => {
            const pcks = parseFloat(record.data.x_studio_total_units) || 0;
            return sum + pcks;
        }, 0);
        
        return this.formatNumberWithCommas(total);
    },
    
    // Add getter for unique pallets count
    get selectedPalletsCount() {
        if (this.model.root.isDomainSelected) {
            if (this._domainTotals && this._domainTotals.pallets !== undefined) {
                return this._domainTotals.pallets.toString();
            }
            return "...";
        }
        
        const selection = this.model.root.selection;
        if (!selection || selection.length === 0) {
            return "0";
        }
        
        const uniquePallets = new Set();
        selection.forEach(record => {
            const palletId = record.data.package_id;
            if (palletId) {
                const palletValue = Array.isArray(palletId) ? palletId[0] : palletId;
                if (palletValue) {
                    uniquePallets.add(palletValue);
                }
            }
        });
        
        return uniquePallets.size.toString();
    },


// Add numeric getters for template comparisons
    get selectedQuantitySumNumeric() {
        if (this.model.root.isDomainSelected) {
            return this._domainTotals ? (this._domainTotals.quantity || 0) : 0;
        }
        
        const selection = this.model.root.selection;
        if (!selection || selection.length === 0) {
            return 0;
        }
        
        return selection.reduce((sum, record) => {
            const qty = parseFloat(record.data.x_studio_2nd_uom) || 0;
            return sum + qty;
        }, 0);
    },
    
    get selectedKgSumNumeric() {
        if (this.model.root.isDomainSelected) {
            return this._domainTotals ? (this._domainTotals.kg || 0) : 0;
        }
        
        const selection = this.model.root.selection;
        if (!selection || selection.length === 0) {
            return 0;
        }
        
        return selection.reduce((sum, record) => {
            const kg = parseFloat(record.data.available_quantity) || 0;
            return sum + kg;
        }, 0);
    },
    
    get selectedPacksSumNumeric() {
        if (this.model.root.isDomainSelected) {
            return this._domainTotals ? (this._domainTotals.packs || 0) : 0;
        }
        
        const selection = this.model.root.selection;
        if (!selection || selection.length === 0) {
            return 0;
        }
        
        return selection.reduce((sum, record) => {
            const pcks = parseFloat(record.data.x_studio_total_units) || 0;
            return sum + pcks;
        }, 0);
    },
    
    get selectedPalletsCountNumeric() {
        if (this.model.root.isDomainSelected) {
            return this._domainTotals ? (this._domainTotals.pallets || 0) : 0;
        }
        
        const selection = this.model.root.selection;
        if (!selection || selection.length === 0) {
            return 0;
        }
        
        const uniquePallets = new Set();
        selection.forEach(record => {
            const palletId = record.data.package_id;
            if (palletId) {
                const palletValue = Array.isArray(palletId) ? palletId[0] : palletId;
                if (palletValue) {
                    uniquePallets.add(palletValue);
                }
            }
        });
        
        return uniquePallets.size;
    },
    
    // Override onSelectDomain (this handles "Select all")
    async onSelectDomain() {
        const result = await super.onSelectDomain();
        
        // Clear previous totals and fetch new ones
        this._domainTotals = null;
        this.render(false);
        
        // Fetch domain totals from server
        await this.fetchDomainTotals();
        this.render(false);
        
        return result;
    },
    
    // Override onUnselectAll to clear domain totals
    onUnselectAll() {
        this._domainTotals = null;
        return super.onUnselectAll();
    },
    
    setup() {
        super.setup();
        console.log("Custom ListController setup completed");
    }
});
// I Flippin DID IT!!! I was here Mark Angelo Templanza. 
patch(ListRenderer.prototype, {
    onCellKeydownEditMode(hotkey, cell, group, record) {
        const { cycleOnTab, list } = this.props;
        const row = cell.parentElement;
        const applyMultiEditBehavior = record && record.selected && list.model.multiEdit;
        const topReCreate = this.props.editable === "top" && record.isNew;

        if (
            applyMultiEditBehavior &&
            this.applyCellKeydownMultiEditMode(hotkey, cell, group, record)
        ) {
            return true;
        }

        if (this.applyCellKeydownEditModeStayOnRow(hotkey, cell, group, record)) {
            return true;
        }

        if (group && this.applyCellKeydownEditModeGroup(hotkey, cell, group, record)) {
            return true;
        }

        switch (hotkey) {
            case "tab": {
                const index = list.records.indexOf(record);
                const lastIndex = topReCreate ? 0 : list.records.length - 1;
                if (index === lastIndex || index === list.records.length - 1) {
                    if (this.displayRowCreates) {
                        if (record.isNew && !record.dirty) {
                            list.leaveEditMode();
                            return false;
                        }
                        // add a line
                        const { context } = this.creates[0];
                        this.add({ context });
                    } else if (
                        this.canCreate &&
                        !record.canBeAbandoned &&
                        (record.dirty || this.lastIsDirty)
                    ) {
                        this.add({ group });
                    } else if (cycleOnTab) {
                        if (record.canBeAbandoned) {
                            list.leaveEditMode();
                        }
                        const futureRecord = list.records[0];
                        if (record === futureRecord) {
                            // Refocus first cell of same record
                            const toFocus = this.findNextFocusableOnRow(row);
                            this.focus(toFocus);
                        } else {
                            list.enterEditMode(futureRecord);
                        }
                    } else {
                        return false;
                    }
                } else {
                    const futureRecord = list.records[index + 1];
                    list.enterEditMode(futureRecord);
                }
                break;
            }
            case "shift+tab": {
                const index = list.records.indexOf(record);
                if (index === 0) {
                    if (cycleOnTab) {
                        if (record.canBeAbandoned) {
                            list.leaveEditMode();
                        }
                        const futureRecord = list.records[list.records.length - 1];
                        if (record === futureRecord) {
                            // Refocus first cell of same record
                            const toFocus = this.findPreviousFocusableOnRow(row);
                            this.focus(toFocus);
                        } else {
                            this.cellToFocus = { forward: false, record: futureRecord };
                            list.enterEditMode(futureRecord);
                        }
                    } else {
                        list.leaveEditMode();
                        return false;
                    }
                } else {
                    const futureRecord = list.records[index - 1];
                    this.cellToFocus = { forward: false, record: futureRecord };
                    list.enterEditMode(futureRecord);
                }
                break;
            }
            case "enter": {
                // --- MOD: This is where we change the logic to keep the same column on the next row ---
                console.log("Modified Enter logic");

                // Current row index and column index
                const index = list.records.indexOf(record);
                const oldCellIndex = cell.cellIndex;
                
                const activeEl = document.activeElement;
                if (activeEl) {
                    activeEl.blur();
                }
                console.log("Hi")
                // By default, Odoo wants to go to the next record
                let futureRecord = list.records[index + 1];
    
                // If "topReCreate" logic is relevant
                if (topReCreate && index === 0) {
                    futureRecord = null;
                }

                // If there is no next record and creation isn't allowed, fallback to first record
                if (!futureRecord && !this.canCreate) {
                    futureRecord = list.records[0];
                }

                // If we do have a next record:
                if (futureRecord) {
                    // 1) Commit the current row
                    list.leaveEditMode({ validate: true }).then((canProceed) => {
                        if (canProceed) {
                            // 2) Enter edit mode on the next record
                            list.enterEditMode(futureRecord).then(() => {
                                // 3) After DOM updates, re-focus the *same column*
                                setTimeout(() => {
                                    // We expect the next row to be at index + 1
                                    const rowEls = this.tableRef.el.querySelectorAll("tr.o_data_row");
                                    const rowEl = rowEls[index + 1];
                                    if (rowEl) {
                                        const tds = rowEl.querySelectorAll("td");
                                        if (tds[oldCellIndex]) {
                                            const input = tds[oldCellIndex].querySelector("input, select, textarea");
                                            if (input) {
                                                input.focus();
                                            }
                                        }
                                    }
                                }, 0);
                            });
                        }
                    });
                } else if (
                    this.lastIsDirty ||
                    !record.canBeAbandoned ||
                    this.displayRowCreates
                ) {
                    // If we have unsaved data, or must add a new row
                    this.add({ group });
                } else {
                    // Otherwise, fallback to the first record
                    futureRecord = list.records.at(0);
                    list.enterEditMode(futureRecord);
                }
                break;
            }
            case "escape": {
                // Keep the original "escape" logic
                list.leaveEditMode({ discard: true });
                const firstAddButton = this.tableRef.el.querySelector(
                    ".o_field_x2many_list_row_add a"
                );

                if (firstAddButton) {
                    this.focus(firstAddButton);
                } else if (group && record.isNew) {
                    const children = [...row.parentElement.children];
                    const idx = children.indexOf(row);
                    for (let i = idx + 1; i < children.length; i++) {
                        const r = children[i];
                        if (r.classList.contains("o_group_header")) {
                            break;
                        }
                        const addCell = [...r.children].find((c) =>
                            c.classList.contains("o_group_field_row_add")
                        );
                        if (addCell) {
                            const toFocus = addCell.querySelector("a");
                            this.focus(toFocus);
                            return true;
                        }
                    }
                    this.focus(cell);
                } else {
                    this.focus(cell);
                }
                break;
            }
            default:
                return false;
        }
        return true;
    },
});
