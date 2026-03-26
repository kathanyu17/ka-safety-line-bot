from flask import Flask, request, abort, jsonify
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import anthropic
import os
import json
import logging
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

line_bot_api = LineBotApi(os.environ['LINE_CHANNEL_ACCESS_TOKEN'])
handler = WebhookHandler(os.environ['LINE_CHANNEL_SECRET'])
claude_client = anthropic.Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])

# Admin User IDs
ADMIN_USER_IDS = set(filter(None, os.environ.get('ADMIN_LINE_USER_ID', '').split(',')))

# Auto-cooldown: นาที ที่ bot จะหยุดตอบหลัง Admin ส่งข้อความ
ADMIN_COOLDOWN_MINUTES = int(os.environ.get('ADMIN_COOLDOWN_MINUTES', '10'))

# เก็บ state ของแต่ละห้องแชท
# { conversation_id: { 'paused': bool, 'admin_last_msg': timestamp } }
chat_states = {}


def is_bot_paused(conversation_id):
    state = chat_states.get(conversation_id, {})
    
    # ถ้า paused ด้วย #หยุด
    if state.get('paused', False):
        return True
    
    # ถ้า Admin ส่งข้อความล่าสุดภายใน cooldown period
    admin_last = state.get('admin_last_msg', 0)
    if admin_last > 0:
        elapsed = time.time() - admin_last
        if elapsed < ADMIN_COOLDOWN_MINUTES * 60:
            remaining = int((ADMIN_COOLDOWN_MINUTES * 60 - elapsed) / 60)
            logger.info(f"Bot paused for {conversation_id}: {remaining} min remaining")
            return True
    
    return False


def get_conversation_id(event):
    src = event.source
    if hasattr(src, 'group_id'):
        return src.group_id
    elif hasattr(src, 'room_id'):
        return src.room_id
    elif hasattr(src, 'user_id'):
        return src.user_id
    return 'unknown'


@app.route("/webhook", methods=['POST'])
def webhook():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)

    # ตรวจจับ Admin ส่งข้อความ -> อัปเดต cooldown
    try:
        body_json = json.loads(body)
        for ev in body_json.get('events', []):
            src = ev.get('source', {})
            user_id = src.get('userId', '')
            
            if user_id and ADMIN_USER_IDS and user_id in ADMIN_USER_IDS:
                # Admin ส่งข้อความ -> set cooldown
                conv_id = (src.get('groupId') or src.get('roomId') or src.get('userId', 'unknown'))
                if conv_id not in chat_states:
                    chat_states[conv_id] = {}
                chat_states[conv_id]['admin_last_msg'] = time.time()
                logger.info(f"Admin {user_id} sent message in {conv_id} -> cooldown started")
    except Exception as e:
        logger.error(f"Pre-process error: {e}")

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    sender_id = event.source.user_id if hasattr(event.source, 'user_id') else None
    conv_id = get_conversation_id(event)
    user_message = event.message.text.strip()

    logger.info(f"MSG from {sender_id} in {conv_id}: {user_message[:50]}")

    # ถ้าเป็น Admin ส่งคำสั่งพิเศษ
    if sender_id and ADMIN_USER_IDS and sender_id in ADMIN_USER_IDS:
        if user_message == '#หยุด':
            if conv_id not in chat_states:
                chat_states[conv_id] = {}
            chat_states[conv_id]['paused'] = True
            chat_states[conv_id]['admin_last_msg'] = time.time()
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text='⏸ Bot หยุดตอบในห้องนี้แล้ว พิมพ์ #เปิด เพื่อเปิด Bot กลับมา'))
            return
        elif user_message == '#เปิด':
            chat_states[conv_id] = {'paused': False, 'admin_last_msg': 0}
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text='▶️ Bot เปิดตอบในห้องนี้แล้ว'))
            return
        elif user_message == '#สถานะ':
            paused = is_bot_paused(conv_id)
            state = chat_states.get(conv_id, {})
            admin_last = state.get('admin_last_msg', 0)
            if admin_last > 0:
                elapsed = int((time.time() - admin_last) / 60)
                remaining = max(0, ADMIN_COOLDOWN_MINUTES - elapsed)
                status = f'⏸ หยุด (เหลือ {remaining} นาที)' if paused else '▶️ ทำงานปกติ'
            else:
                status = '⏸ หยุด (ถาวร)' if paused else '▶️ ทำงานปกติ'
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f'Bot status: {status}'))
            return
        else:
            # Admin ส่งข้อความปกติ -> อัปเดต cooldown แต่ไม่ตอบ
            if conv_id not in chat_states:
                chat_states[conv_id] = {}
            chat_states[conv_id]['admin_last_msg'] = time.time()
            logger.info(f"Admin message -> cooldown updated for {conv_id}")
            return

    # ตรวจสอบ chatMode (LINE OA App)
    try:
        body = request.get_data(as_text=True)
        body_json = json.loads(body)
        for ev in body_json.get('events', []):
            if ev.get('replyToken') == event.reply_token:
                chat_mode = ev.get('source', {}).get('chatMode', 'bot')
                if chat_mode == 'chat':
                    logger.info(f"chatMode=chat for {conv_id}, not responding")
                    return
    except Exception as e:
        logger.error(f"chatMode check: {e}")

    # ตรวจสอบว่า Bot ถูก pause หรือไม่
    if is_bot_paused(conv_id):
        logger.info(f"Bot is paused for {conv_id}, skipping")
        return

    # Bot ตอบลูกค้า
    logger.info(f"Bot responding to: {user_message[:50]}")
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


@app.route("/debug", methods=['GET'])
def debug():
    return jsonify({
        'admin_user_ids': list(ADMIN_USER_IDS),
        'cooldown_minutes': ADMIN_COOLDOWN_MINUTES,
        'chat_states': {k: {**v, 'is_paused': is_bot_paused(k)} for k, v in chat_states.items()}
    })


@app.route("/", methods=['GET'])
def index():
    return 'KA Safety LINE Bot is running!'


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
