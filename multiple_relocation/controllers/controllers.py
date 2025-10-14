# # -*- coding: utf-8 -*-
# # from odoo import http


# class ClientSupportAIController(http.Controller):
    
#     @http.route('/telegram/webhook', type='json', auth='public', methods=['POST'])
#     def telegram_webhook(self, **payload):
#         message = payload.get("message", {})
#         chat_id = message.get("chat", {}).get("id")
#         text = message.get("text")
    
#         # Create helpdesk ticket
#         ticket = request.env['helpdesk.ticket'].sudo().create({
#             "name": f"Telegram Question {chat_id}",
#             "description": text,
#         })
    
#         # Call AI
#         ai_answer = self._ask_ai(text)
    
#         # Save response in ticket
#         ticket.sudo().write({"x_ai_response": ai_answer})
    
#         # Send back to Telegram
#         bot_token = request.env['ir.config_parameter'].sudo().get_param("telegram.bot.token")
#         url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
#         requests.post(url, json={"chat_id": chat_id, "text": ai_answer})
    
#         return {"status": "ok"}
    
    
    
#     def _ask_ai(self, question):
#         tickets = request.env['helpdesk.ticket'].sudo().search([('description', 'ilike', question)], limit=3)
#         context = "\n".join([t.description[:200] for t in tickets])
#         prompt = f"Question: {question}\n\nContext from past tickets:\n{context}"
    
#         headers = {"Authorization": f"Bearer {AI_TOKEN}", "Content-Type": "application/json"}
#         payload = {
#             "model": "gpt-4",
#             "messages": [
#                 {"role": "system", "content": "You are a customer support assistant."},
#                 {"role": "user", "content": prompt}
#             ]
#         }
#         r = requests.post(AI_API_URL, json=payload, headers=headers)
#         return r.json()["choices"][0]["message"]["content"]






# module/
# │── __manifest__.py        # Module metadata
# │── __init__.py            # Imports models, controllers
# │── models/
# │   └── my_model.py        # Business logic (ORM models)
# │── controllers/
# │   └── main.py            # API / HTTP routes
# │── views/
# │   └── my_model_views.xml # Form, tree, kanban, search views
# │── security/
# │   ├── ir.model.access.csv
# │   └── security.xml
# │── data/
# │   └── data.xml           # Initial records (cron jobs, sequences, etc.)
# │── report/
# │   └── report.xml         # Report definitions
