/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
/**
 * If your list_renderer.js is truly at "@web/views/list/list_renderer",
 * then use that path. Adjust if it's different in your system.
 */
import { ListRenderer } from "@web/views/list/list_renderer";
/**
 * IMPORTANT: The new patch API in Odoo 17 does not allow
 * a second argument as the patch name. We pass only the object.
 */

// Selection totals (pallets / qty / kg / packs of the ticked rows) moved to selection_totals.js:
// Odoo 19 renders the "N selected" box in its own SelectionBox component, not the ListController.
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
                console.log("Modified Enter logic");
                const index = list.records.indexOf(record);
                const oldCellIndex = cell.cellIndex;
                
                // Store the current active element to prevent unwanted focus changes
                const currentFocusElement = document.activeElement;
                
                // Prevent default focus behavior during save
                const preventFocusLoss = (e) => {
                    if (e.target !== currentFocusElement) {
                        e.preventDefault();
                        e.stopImmediatePropagation();
                    }
                };
                
                // Add temporary focus listeners to prevent cursor jump
                document.addEventListener('focusin', preventFocusLoss, true);
                document.addEventListener('focus', preventFocusLoss, true);
                
                let futureRecord = list.records[index + 1];
            
                if (topReCreate && index === 0) {
                    futureRecord = null;
                }
                if (!futureRecord && !this.canCreate) {
                    futureRecord = list.records[0];
                }
                
                if (futureRecord) {
                    // Commit the current row
                    list.leaveEditMode({ validate: true }).then((canProceed) => {
                        // Remove focus prevention listeners
                        document.removeEventListener('focusin', preventFocusLoss, true);
                        document.removeEventListener('focus', preventFocusLoss, true);
                        
                        if (canProceed) {
                            // Enter edit mode on the next record
                            list.enterEditMode(futureRecord).then(() => {
                                // Use requestAnimationFrame for smoother DOM updates
                                requestAnimationFrame(() => {
                                    const rowEls = this.tableRef.el.querySelectorAll("tr.o_data_row");
                                    const rowEl = rowEls[index + 1];
                                    if (rowEl) {
                                        const tds = rowEl.querySelectorAll("td");
                                        if (tds[oldCellIndex]) {
                                            const input = tds[oldCellIndex].querySelector("input, select, textarea");
                                            if (input) {
                                                input.focus();
                                                // Select all content for fast data entry
                                                if (input.type === 'text' || input.tagName === 'TEXTAREA') {
                                                    input.select();
                                                } else if (input.type === 'number') {
                                                    input.select();
                                                }
                                            }
                                        }
                                    }
                                });
                            });
                        } else {
                            // If save failed, restore focus to current cell
                            if (currentFocusElement && currentFocusElement.isConnected) {
                                currentFocusElement.focus();
                            }
                        }
                    }).catch(() => {
                        // Clean up listeners on error
                        document.removeEventListener('focusin', preventFocusLoss, true);
                        document.removeEventListener('focus', preventFocusLoss, true);
                    });
                } else if (
                    this.lastIsDirty ||
                    !record.canBeAbandoned ||
                    this.displayRowCreates
                ) {
                    document.removeEventListener('focusin', preventFocusLoss, true);
                    document.removeEventListener('focus', preventFocusLoss, true);
                    this.add({ group });
                } else {
                    document.removeEventListener('focusin', preventFocusLoss, true);
                    document.removeEventListener('focus', preventFocusLoss, true);
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



