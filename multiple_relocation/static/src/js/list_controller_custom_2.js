/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ListController } from "@web/views/list/list_controller";
import { onWillUnmount } from "@odoo/owl";

// Patch the ListController to add Alt+Q keyboard shortcut
patch(ListController.prototype, {
    setup() {
        super.setup();
        
        const handleKeyDown = (ev) => {
            // Check if Alt+Q is pressed
            if (ev.altKey && ev.key.toLowerCase() === 'q') {
                ev.preventDefault();
                ev.stopPropagation();
                
                // Find the "Select all" link using class or title attribute
                const selectAllButton = document.querySelector('.o_list_select_domain') || 
                                       document.querySelector('a[title="Select all records matching the search"]');
                
                if (selectAllButton) {
                    selectAllButton.click();
                }
            }
        };
        
        document.addEventListener('keydown', handleKeyDown);
        
        // Cleanup on component destroy
        onWillUnmount(() => {
            document.removeEventListener('keydown', handleKeyDown);
        });
    }
});