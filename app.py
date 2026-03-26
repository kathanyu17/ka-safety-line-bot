from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import anthropic
import os
import json

app = Flask(__name__)

line_bot_api = LineBotApi(os.environ['LINE_CHANNEL_ACCESS_TOKEN'])
handler = WebhookHandler(os.environ['LINE_CHANNEL_SECRET'])
claude_client = anthropic.Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])

# Admin User IDs - Bot จะไม่ตอบข้อความจาก Admin
ADMIN_USER_IDS = set(filter(None, os.environ.get('ADMIN_LINE_USER_ID', '').split(',')))


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
    # ตรวจสอบว่าผู้ส่งเป็น Admin หรือไม่
    # เมื่อ Admin ตอบจาก chat.line.biz Bot จะไม่ตอบซ้ำ
    sender_id = event.source.user_id if hasattr(event.source, 'user_id') else None

    if sender_id and ADMIN_USER_IDS and sender_id in ADMIN_USER_IDS:
        # ข้อความนี้มาจาก Admin ไม่ให้ Bot ตอบ
        return

    # ตรวจสอบ chatMode (สำหรับ LINE OA App บนมือถือ)
    try:
        body = request.get_data(as_text=True)
        body_json = json.loads(body)
        events = body_json.get('events', [])
        for ev in events:
            if ev.get('replyToken') == event.reply_token:
                chat_mode = ev.get('source', {}).get('chatMode', 'bot')
                if chat_mode == 'chat':
                    return  # Admin กำลังดูแลอยู่ ไม่ให้ Claude ตอบ
    except Exception:
        pass

    user_message = event.message.text
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

กรุณาตอบคำถามของลูกค้าอย่างสุภาพและเป็นประโยชน์ โดยอ้างอิงข้อมูลด้านบนในการตอบ หากคำถามไม่เกี่ยวข้องกับข้อมูลที่มี ให้ตอบตามความรู้ทั่วไปและแนะนำให้ติดต่อเจ้าหน้าที่หากต้องการข้อมูลเพิ่มเติม""",
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
