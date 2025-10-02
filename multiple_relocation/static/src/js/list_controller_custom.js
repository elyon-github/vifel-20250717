/** @odoo-module **/
import { ListController } from "@web/views/list/list_controller";
import { patch } from "@web/core/utils/patch";

// Global flag to ensure only one listener is active
let globalKeyboardListenerActive = false;

patch(ListController.prototype, {
    setup() {
        super.setup();
        
        // Only add the listener once globally, not per instance
        if (!globalKeyboardListenerActive) {
            globalKeyboardListenerActive = true;
            
            const handleKeyPress = (event) => {
                if (event.altKey && event.key.toLowerCase() === 'a') {
                    event.preventDefault();
                    event.stopPropagation();
                    this.clickSelectAllCheckbox();
                }
            };
            
            document.addEventListener('keydown', handleKeyPress, true);
        }
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