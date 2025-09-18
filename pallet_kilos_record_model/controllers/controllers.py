# # -*- coding: utf-8 -*-
# # from odoo import http


# class TelegramRAGController(http.Controller):

#     AI_API_URL = "https://api.openai.com/v1/chat/completions"

#     @http.route('/telegram/support_question', type='json', auth='public', methods=['POST'])
#     def support_question(self, **kwargs):
#         question = kwargs.get("question")
#         chat_id = kwargs.get("chat_id")  # so we know where to reply in Telegram

#         if not question or not chat_id:
#             return {"error": "Missing parameters"}

#         # 🔹 Step 1: Retrieve Helpdesk context
#         Helpdesk = request.env['helpdesk.ticket'].sudo()
#         tickets = Helpdesk.search([('description', 'ilike', question)], limit=3)

#         context_text = "No related tickets found."
#         if tickets:
#             context_text = "Relevant helpdesk tickets:\n"
#             for t in tickets:
#                 context_text += f"- Ticket {t.id}: {t.description[:300]}\n"

#         # 🔹 Step 2: Build AI prompt
#         token = request.env['ir.config_parameter'].sudo().get_param("ai.api.token")
#         headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
#         payload = {
#             "model": "gpt-4",
#             "messages": [
#                 {"role": "system", "content": "You are a customer support assistant. Answer based on helpdesk history."},
#                 {"role": "user", "content": f"Question: {question}\n\nContext:\n{context_text}"}
#             ]
#         }

#         # 🔹 Step 3: Call AI
#         try:
#             response = requests.post(self.AI_API_URL, json=payload, headers=headers, timeout=30)
#             response.raise_for_status()
#             ai_answer = response.json()["choices"][0]["message"]["content"]
#         except Exception as e:
#             ai_answer = f"Sorry, error calling AI: {str(e)}"

#         # 🔹 Step 4: Send back to Telegram
#         telegram_token = request.env['ir.config_parameter'].sudo().get_param("telegram.bot.token")
#         telegram_url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
#         telegram_payload = {"chat_id": chat_id, "text": ai_answer}
#         try:
#             requests.post(telegram_url, json=telegram_payload, timeout=15)
#         except Exception as e:
#             return {"error": f"Telegram send failed: {str(e)}"}

#         return {"answer": ai_answer, "context_used": context_text}