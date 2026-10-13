/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { FormController } from "@web/views/form/form_controller";
import { onWillUnmount } from "@odoo/owl";

// Patch the FormController to add keyboard shortcuts
patch(FormController.prototype, {
    setup() {
        super.setup();
        
        const handleKeyDown = (ev) => {
            // Alt+L: Add a line in one2many/many2many fields
            if (ev.altKey && ev.key.toLowerCase() === 'l') {
                ev.preventDefault();
                ev.stopPropagation();
                
                const addLineButton = document.querySelector('.o_field_x2many_list_row_add a') ||
                                     document.querySelector('a.o_field_x2many_list_row_add') ||
                                     document.querySelector('a[title="Add a line"]') ||
                                     document.querySelector('.o_form_view .o_field_one2many .o_field_x2many .o_field_x2many_list_row_add a') ||
                                     document.querySelector('.o_form_view .o_field_many2many .o_field_x2many .o_field_x2many_list_row_add a');
                
                if (addLineButton) {
                    addLineButton.click();
                }
            }
            
            // Alt+Right Arrow: Next notebook page
            if (ev.altKey && ev.key === 'ArrowRight') {
                ev.preventDefault();
                ev.stopPropagation();
                this.navigateNotebookPage('next');
            }
            
            // Alt+Left Arrow: Previous notebook page
            if (ev.altKey && ev.key === 'ArrowLeft') {
                ev.preventDefault();
                ev.stopPropagation();
                this.navigateNotebookPage('prev');
            }
            
            // Alt+1 through Alt+9: Jump to specific notebook page
            if (ev.altKey && ev.key >= '1' && ev.key <= '9') {
                ev.preventDefault();
                ev.stopPropagation();
                const pageIndex = parseInt(ev.key) - 1;
                this.navigateNotebookPage('jump', pageIndex);
            }
        };
        
        document.addEventListener('keydown', handleKeyDown);
        
        // Cleanup on component destroy
        onWillUnmount(() => {
            document.removeEventListener('keydown', handleKeyDown);
        });
    },
    
    navigateNotebookPage(direction, pageIndex = null) {
        // Find the active notebook in the current form view
        const activeNotebook = document.querySelector('.o_form_sheet_bg .o_notebook, .o_form_view .o_notebook');
        
        if (!activeNotebook) return;
        
        // Get all notebook page tabs
        const tabs = activeNotebook.querySelectorAll('.nav-link');
        if (tabs.length === 0) return;
        
        // Find the currently active tab
        let activeIndex = -1;
        tabs.forEach((tab, index) => {
            if (tab.classList.contains('active')) {
                activeIndex = index;
            }
        });
        
        let targetTab = null;
        
        if (direction === 'next') {
            // Navigate to next page (wrap around to first if at end)
            const nextIndex = (activeIndex + 1) % tabs.length;
            targetTab = tabs[nextIndex];
        } else if (direction === 'prev') {
            // Navigate to previous page (wrap around to last if at beginning)
            const prevIndex = activeIndex === 0 ? tabs.length - 1 : activeIndex - 1;
            targetTab = tabs[prevIndex];
        } else if (direction === 'jump' && pageIndex !== null) {
            // Jump to specific page by index
            if (pageIndex >= 0 && pageIndex < tabs.length) {
                targetTab = tabs[pageIndex];
            }
        }
        
        if (targetTab) {
            targetTab.click();
            
            // Focus on first field in the new page
            setTimeout(() => {
                this.focusFirstFieldInActivePage(activeNotebook);
            }, 100);
        }
    },
    
    focusFirstFieldInActivePage(notebook) {
        // Find the active tab pane
        const activePane = notebook.querySelector('.tab-pane.active');
        if (!activePane) return;
        
        // List of focusable field selectors in priority order
        const fieldSelectors = [
            'input[type="text"]:not([readonly]):not([disabled])',
            'input[type="number"]:not([readonly]):not([disabled])',
            'input[type="email"]:not([readonly]):not([disabled])',
            'input[type="tel"]:not([readonly]):not([disabled])',
            'input[type="url"]:not([readonly]):not([disabled])',
            'textarea:not([readonly]):not([disabled])',
            'select:not([readonly]):not([disabled])',
            '.o_field_widget input:not([readonly]):not([disabled])',
            '.o_field_widget textarea:not([readonly]):not([disabled])',
            '.o_input:not([readonly]):not([disabled])'
        ];
        
        // Try each selector until we find a visible, focusable field
        for (const selector of fieldSelectors) {
            const fields = activePane.querySelectorAll(selector);
            
            for (const field of fields) {
                // Check if field is visible
                const rect = field.getBoundingClientRect();
                const isVisible = rect.width > 0 && rect.height > 0 &&
                                window.getComputedStyle(field).visibility !== 'hidden' &&
                                window.getComputedStyle(field).display !== 'none';
                
                if (isVisible) {
                    field.focus();
                    // Also select text if it's an input field
                    if (field.select && typeof field.select === 'function') {
                        field.select();
                    }
                    return;
                }
            }
        }
    }
});