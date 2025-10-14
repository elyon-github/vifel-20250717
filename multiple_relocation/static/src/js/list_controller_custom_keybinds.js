/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { ListController } from "@web/views/list/list_controller";
import { onWillUnmount } from "@odoo/owl";

// Store the handler reference and active instances count
let keyboardHandler = null;
let activeInstances = 0;

// Patch the ListController to add keyboard shortcuts
patch(ListController.prototype, {
    setup() {
        super.setup();
        
        // Increment instance counter
        activeInstances++;
        
        // Only add the listener once globally
        if (!keyboardHandler) {
            keyboardHandler = (ev) => {
                // Only handle if we're in a list view context
                const isInListView = document.querySelector('.o_list_view') !== null;
                if (!isInListView) return;
                
                // Alt+A: Select all checkbox
                if (ev.altKey && ev.key.toLowerCase() === 'a') {
                    ev.preventDefault();
                    ev.stopPropagation();
                    this.clickSelectAllCheckbox();
                }
                
                // Alt+D: Select all records matching search
                if (ev.altKey && ev.key.toLowerCase() === 'd') {
                    ev.preventDefault();
                    ev.stopPropagation();
                    
                    setTimeout(() => {
                        const selectAllButton = document.querySelector('.o_list_select_domain') || 
                                               document.querySelector('a[title="Select all records matching the search"]');
                        
                        if (selectAllButton && selectAllButton.offsetParent !== null) {
                            const clickEvent = new MouseEvent('click', {
                                view: window,
                                bubbles: true,
                                cancelable: true
                            });
                            selectAllButton.dispatchEvent(clickEvent);
                        }
                    }, 0);
                }
                
                // Alt+L: Add a line in editable list
                if (ev.altKey && ev.key.toLowerCase() === 'l') {
                    ev.preventDefault();
                    ev.stopPropagation();
                    
                    const addLineButton = document.querySelector('.o_list_view .o_list_table .o_field_x2many_list_row_add a') ||
                                         document.querySelector('.o_list_view a.o_field_x2many_list_row_add') ||
                                         document.querySelector('.o_list_view a[title="Add a line"]') ||
                                         document.querySelector('.o_list_table_grouped .o_group_field_row_add a') ||
                                         document.querySelector('a.o_list_button_add');
                    
                    if (addLineButton) {
                        addLineButton.click();
                    }
                }
            };
            
            document.addEventListener('keydown', keyboardHandler, true);
        }
        
        // Clean up when component is unmounted
        onWillUnmount(() => {
            activeInstances--;
            
            // Remove listener only when no list view instances remain
            if (activeInstances === 0 && keyboardHandler) {
                document.removeEventListener('keydown', keyboardHandler, true);
                keyboardHandler = null;
            }
        });
    },
    
    clickSelectAllCheckbox() {
        let checkbox = null;
        
        // Priority 1: Check active modal/dialog first
        const modal = document.querySelector('.modal:not(.o_inactive_modal), .o_dialog');
        if (modal) {
            const selectors = [
                'thead .o_list_record_selector input[type="checkbox"]',
                'thead input[type="checkbox"]',
                '.o_list_table thead input[type="checkbox"]'
            ];
            
            for (const selector of selectors) {
                checkbox = modal.querySelector(selector);
                if (checkbox) break;
            }
        }
        
        // Priority 2: Check the current component's element
        if (!checkbox) {
            const root = this.root?.el || this.el;
            if (root) {
                const selectors = [
                    'thead .o_list_record_selector input[type="checkbox"]',
                    'thead input.o_list_record_selector',
                    'thead th.o_list_record_selector input',
                    'thead input[type="checkbox"]',
                    '.o_list_table thead input[type="checkbox"]'
                ];
                
                for (const selector of selectors) {
                    checkbox = root.querySelector(selector);
                    if (checkbox) break;
                }
            }
        }
        
        // Priority 3: Find the topmost visible checkbox
        if (!checkbox) {
            const allCheckboxes = document.querySelectorAll('thead .o_list_record_selector input[type="checkbox"], thead input[type="checkbox"]');
            const visibleCheckboxes = Array.from(allCheckboxes).filter(cb => {
                const rect = cb.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0 && 
                       window.getComputedStyle(cb).visibility !== 'hidden' &&
                       window.getComputedStyle(cb).display !== 'none';
            });
            
            if (visibleCheckboxes.length > 0) {
                checkbox = visibleCheckboxes[visibleCheckboxes.length - 1];
            }
        }
        
        if (checkbox) {
            checkbox.click();
        }
    }
});