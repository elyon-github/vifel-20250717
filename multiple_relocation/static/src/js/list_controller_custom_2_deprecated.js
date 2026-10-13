/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { ListController } from "@web/views/list/list_controller";

// Global flag to ensure only one listener is active
let globalListKeyboardListenerActive = false;

// Patch the ListController to add keyboard shortcuts
patch(ListController.prototype, {
    setup() {
        super.setup();
        
        // Only add the listener once globally, not per instance
        if (!globalListKeyboardListenerActive) {
            globalListKeyboardListenerActive = true;
            
            const handleKeyDown = (ev) => {
                // Check if Alt+D is pressed
                if (ev.altKey && ev.key.toLowerCase() === 'd') {
                    ev.preventDefault();
                    ev.stopPropagation();
                    
                    // Use setTimeout to defer execution and avoid timing issues
                    setTimeout(() => {
                        // Find the "Select all" link using class or title attribute
                        const selectAllButton = document.querySelector('.o_list_select_domain') || 
                                               document.querySelector('a[title="Select all records matching the search"]');
                        
                        if (selectAllButton && selectAllButton.offsetParent !== null) {
                            // Dispatch a proper click event instead of using .click()
                            const clickEvent = new MouseEvent('click', {
                                view: window,
                                bubbles: true,
                                cancelable: true
                            });
                            selectAllButton.dispatchEvent(clickEvent);
                        }
                    }, 0);
                }
                
                // Check if Alt+W is pressed (Add a line in editable list)
                if (ev.altKey && ev.key.toLowerCase() === 'w') {
                    ev.preventDefault();
                    ev.stopPropagation();
                    
                    // Find the "Add a line" button in editable list views
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
            
            document.addEventListener('keydown', handleKeyDown, true);
        }
    }
});