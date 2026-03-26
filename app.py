from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import anthropic
import os

app = Flask(__name__)

line_bot_api = LineBotApi(os.environ['LINE_CHANNEL_ACCESS_TOKEN'])
handler = WebhookHandler(os.environ['LINE_CHANNEL_SECRET'])
claude_client = anthropic.Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])

@app.route("/webhook", methods=['POST'])
def webhook():
      signature = request.headers['X-Line-Signature']
      body = request.get_data(as_text=True)
      try:
                handler.handle(body, signature)
except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
      user_message = event.message.text

    response = claude_client.messages.create(
              model="claude-sonnet-4-5",
              max_tokens=1024,
              system="""You are a helpful AI assistant for KA Safety, a company that sells safety equipment and related products. Answer questions about the business, products, services, and general inquiries in Thai language. Be friendly, polite, and concise. If you don't know specific details, suggest contacting the team directly.""",
              messages=[{"role": "user", "content": user_message}]
    )

    reply_text = response.content[0].text
    line_bot_api.reply_message(
              event.reply_token,
              TextSendMessage(text=reply_text)
    )

@app.route("/", methods=['GET'])
def index():
      return 'KA Safety LINE Bot is running!'

if __name__ == "__main__":
      app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
