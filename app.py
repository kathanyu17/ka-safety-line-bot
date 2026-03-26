from flask import Flask, request, abort, jsonify
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import anthropic
import os
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

line_bot_api = LineBotApi(os.environ['LINE_CHANNEL_ACCESS_TOKEN'])
handler = WebhookHandler(os.environ['LINE_CHANNEL_SECRET'])
claude_client = anthropic.Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])

# Admin User IDs - Bot จะไม่ตอบข้อความจาก Admin
ADMIN_USER_IDS = set(filter(None, os.environ.get('ADMIN_LINE_USER_ID', '').split(',')))

# Store last webhooks for debugging
last_webhooks = []


@app.route("/webhook", methods=['POST'])
def webhook():
    global last_webhooks
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)

    # Store webhook for debugging
    try:
        body_json = json.loads(body)
        for ev in body_json.get('events', []):
            src = ev.get('source', {})
            info = {
                'type': ev.get('type'),
                'userId': src.get('userId'),
                'chatMode': src.get('chatMode'),
                'msgText': ev.get('message', {}).get('text', '') if ev.get('type') == 'message' else '',
                'replyToken': ev.get('replyToken', '')[:20] if ev.get('replyToken') else ''
            }
            last_webhooks.append(info)
            if len(last_webhooks) > 20:
                last_webhooks = last_webhooks[-20:]
            logger.info(f"WEBHOOK EVENT: {info}")
        logger.info(f"ADMIN_USER_IDS: {ADMIN_USER_IDS}")
    except Exception as e:
        logger.error(f"Log error: {e}")

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'


@app.route("/debug", methods=['GET'])
def debug():
    return jsonify({
        'last_webhooks': last_webhooks,
        'admin_user_ids': list(ADMIN_USER_IDS),
        'count': len(last_webhooks)
    })


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    sender_id = event.source.user_id if hasattr(event.source, 'user_id') else None
    logger.info(f"HANDLE: sender_id={sender_id}, admin_ids={ADMIN_USER_IDS}, match={sender_id in ADMIN_USER_IDS if sender_id and ADMIN_USER_IDS else 'N/A'}")

    if sender_id and ADMIN_USER_IDS and sender_id in ADMIN_USER_IDS:
        logger.info(f"BLOCKED: Admin {sender_id}")
        return

    # ตรวจสอบ chatMode
    try:
        body = request.get_data(as_text=True)
        body_json = json.loads(body)
        for ev in body_json.get('events', []):
            if ev.get('replyToken') == event.reply_token:
                chat_mode = ev.get('source', {}).get('chatMode', 'bot')
                logger.info(f"chatMode: {chat_mode}")
                if chat_mode == 'chat':
                    logger.info("BLOCKED: chatMode=chat")
                    return
    except Exception as e:
        logger.error(f"chatMode error: {e}")

    user_message = event.message.text
    logger.info(f"BOT RESPONDING to: {user_message[:50]}")

    response = claude_client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1024,
        system="""คุณคือผู้ช่วย AI ของบริษัท KA Safety and Engineering ที่ตอบคำถามเป็นภาษาไทย

ข้อมูลหลักสูตรที่เปิดสอน:
- หลักสูตร จป.หัวหน้างาน / จป.บริหาร / คปอ.
- ระยะเวลาอบรม: 2 วัน 12 ชั่วโมง
- คุณสมบัติผู้เข้าอบรม: เป็นลูกจ้างระดับหัวหน้างานหรือผู้บังคับบัญชา

ข้อมูลติดต่อ:
- โทร 094-565-9777, 088-221-2777
- E-mail: kasafety.sale@gmail.com

กรุณาตอบคำถามของลูกค้าอย่างสุภาพและเป็นประโยชน์""",
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
