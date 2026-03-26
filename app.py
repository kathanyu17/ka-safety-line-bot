from flask import Flask, request, abort, jsonify
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import anthropic
import os
import json
import logging
import time
import requests as http_requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.environ['LINE_CHANNEL_ACCESS_TOKEN']
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(os.environ['LINE_CHANNEL_SECRET'])
claude_client = anthropic.Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])

ADMIN_TOKEN = os.environ.get('ADMIN_TOKEN', 'kasafety2024')

# chat_states: { conv_id: { 'paused': bool, 'last_bot_msg_time': float } }
chat_states = {}

# เก็บ raw webhook events ล่าสุดไว้ debug
last_webhook_events = []


def is_bot_paused(conv_id):
    state = chat_states.get(conv_id, {})
    return state.get('paused', False)


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
    global last_webhook_events
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)

    # Log raw webhook for debugging
    try:
        body_json = json.loads(body)
        # เก็บ events ล่าสุด 20 ข้อความ
        last_webhook_events = (body_json.get('events', []) + last_webhook_events)[:20]
        for ev in body_json.get('events', []):
            # Log ข้อมูลสำคัญทั้งหมด
            ev_type = ev.get('type', '')
            src = ev.get('source', {})
            user_id = src.get('userId', '')
            chat_mode = ev.get('chatMode', 'N/A')
            delivery = ev.get('deliveryContext', {})
            logger.info(f"WEBHOOK event={ev_type} userId={user_id} chatMode={chat_mode} delivery={delivery}")
    except Exception as e:
        logger.error(f"Webhook parse error: {e}")

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    conv_id = get_conversation_id(event)
    customer_user_id = event.source.user_id if hasattr(event.source, 'user_id') else None
    user_message = event.message.text.strip()

    # ดึง raw event data เพื่อตรวจ chatMode
    try:
        body = request.get_data(as_text=True)
        body_json = json.loads(body)
        raw_event = None
        for ev in body_json.get('events', []):
            if ev.get('replyToken') == event.reply_token:
                raw_event = ev
                break
        if raw_event is None and body_json.get('events'):
            raw_event = body_json['events'][0]

        chat_mode = 'bot'
        if raw_event:
            # LINE ส่ง chatMode ใน source หรือ top-level ของ event
            chat_mode = raw_event.get('chatMode',
                        raw_event.get('source', {}).get('chatMode', 'bot'))
            logger.info(f"MSG conv={conv_id} user={customer_user_id} chatMode={chat_mode} msg={user_message[:30]}")

            # ถ้า chatMode = 'chat' แสดงว่า Admin กำลัง handle อยู่ -> Bot หยุดตอบ
            if chat_mode == 'chat':
                logger.info(f"chatMode=chat -> Admin handling, bot skip")
                return
    except Exception as e:
        logger.error(f"chatMode check error: {e}")

    # ถ้า Admin pause ด้วย control panel -> หยุดตอบ
    if is_bot_paused(conv_id):
        logger.info(f"Bot paused for {conv_id}, skipping")
        return

    logger.info(f"Bot responding to: {user_message[:50]}")
    try:
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
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

        # บันทึกเวลา Bot ตอบล่าสุด
        if conv_id not in chat_states:
            chat_states[conv_id] = {}
        chat_states[conv_id]['last_bot_msg_time'] = time.time()
        chat_states[conv_id]['last_customer_user_id'] = customer_user_id

    except Exception as e:
        logger.error(f"Error generating response: {e}")


@app.route("/control")
def control_panel():
    token = request.args.get('token', '')
    if token != ADMIN_TOKEN:
        return '<h1>401 Unauthorized</h1><p>Token required</p>', 401

    states_html = ''
    for conv_id, state in chat_states.items():
        paused = state.get('paused', False)
        status = 'หยุด' if paused else 'ทำงาน'
        color = '#e74c3c' if paused else '#27ae60'
        action = 'resume' if paused else 'pause'
        btn_text = 'เปิด Bot' if paused else 'หยุด Bot'
        btn_color = '#27ae60' if paused else '#e74c3c'
        short_id = conv_id[-8:] if len(conv_id) > 8 else conv_id
        states_html += f'<div style="background:white;border-radius:12px;padding:16px;margin:10px 0;box-shadow:0 2px 8px rgba(0,0,0,0.1);display:flex;justify-content:space-between;align-items:center;"><div><div style="font-weight:bold;color:#333;">...{short_id}</div><div style="color:{color};font-size:14px;margin-top:4px;">● {status}</div></div><button onclick="controlBot(\'{conv_id}\',\'{action}\')" style="background:{btn_color};color:white;border:none;border-radius:8px;padding:10px 20px;font-size:15px;cursor:pointer;">{btn_text}</button></div>'

    if not states_html:
        states_html = '<div style="text-align:center;color:#999;padding:40px;">ยังไม่มีแชท<br><small>เมื่อลูกค้าส่งข้อความ ห้องแชทจะแสดงที่นี่</small></div>'

    html = f"""<!DOCTYPE html>
<html lang="th"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>KA Safety Bot Control</title>
<style>body{{margin:0;padding:0;background:#f0f4f8;font-family:-apple-system,BlinkMacSystemFont,sans-serif;}}
.header{{background:linear-gradient(135deg,#06C755,#05a847);color:white;padding:20px;text-align:center;}}
.header h1{{margin:0;font-size:22px;}}.header p{{margin:5px 0 0;opacity:0.9;font-size:14px;}}
.container{{max-width:600px;margin:0 auto;padding:16px;}}
.global-btns{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:16px 0;}}
.btn{{padding:14px;border:none;border-radius:10px;font-size:16px;font-weight:bold;cursor:pointer;color:white;}}
.btn-pause{{background:#e74c3c;}}.btn-resume{{background:#27ae60;}}
.section-title{{color:#666;font-size:13px;font-weight:bold;margin:20px 0 8px;}}</style></head>
<body><div class="header"><h1>🤖 KA Safety Bot Control</h1><p>ควบคุม Bot ตอบข้อความ LINE</p></div>
<div class="container"><div style="margin:16px 0;"><div class="section-title">ควบคุมทุกห้องแชท</div>
<div class="global-btns">
<button class="btn btn-pause" onclick="pauseAll()">⏸ หยุด Bot ทั้งหมด</button>
<button class="btn btn-resume" onclick="resumeAll()">▶️ เปิด Bot ทั้งหมด</button>
</div></div>
<div class="section-title">ห้องแชทที่ใช้งาน</div>
<div id="states">{states_html}</div>
<div style="text-align:center;margin:20px 0;">
<button onclick="location.reload()" style="background:#f8f9fa;border:1px solid #ddd;border-radius:8px;padding:10px 24px;cursor:pointer;color:#666;">🔄 รีเฟรช</button>
</div></div>
<script>
const token = '{token}';
async function controlBot(convId, action) {{
const r = await fetch('/api/' + action + '?token=' + token + '&conv_id=' + encodeURIComponent(convId), {{method:'POST'}});
const d = await r.json();
if(d.ok) location.reload(); else alert('Error: ' + d.error);
}}
async function pauseAll() {{ await fetch('/api/pause_all?token=' + token, {{method:'POST'}}); location.reload(); }}
async function resumeAll() {{ await fetch('/api/resume_all?token=' + token, {{method:'POST'}}); location.reload(); }}
</script></body></html>"""
    return html


@app.route("/api/pause", methods=['POST'])
def api_pause():
    token = request.args.get('token', '')
    if token != ADMIN_TOKEN:
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    conv_id = request.args.get('conv_id', '')
    if not conv_id:
        return jsonify({'ok': False, 'error': 'missing conv_id'}), 400
    if conv_id not in chat_states:
        chat_states[conv_id] = {}
    chat_states[conv_id]['paused'] = True
    return jsonify({'ok': True, 'conv_id': conv_id, 'paused': True})


@app.route("/api/resume", methods=['POST'])
def api_resume():
    token = request.args.get('token', '')
    if token != ADMIN_TOKEN:
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    conv_id = request.args.get('conv_id', '')
    if not conv_id:
        return jsonify({'ok': False, 'error': 'missing conv_id'}), 400
    if conv_id not in chat_states:
        chat_states[conv_id] = {}
    chat_states[conv_id]['paused'] = False
    return jsonify({'ok': True, 'conv_id': conv_id, 'paused': False})


@app.route("/api/pause_all", methods=['POST'])
def api_pause_all():
    token = request.args.get('token', '')
    if token != ADMIN_TOKEN:
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    for conv_id in chat_states:
        chat_states[conv_id]['paused'] = True
    return jsonify({'ok': True, 'paused_count': len(chat_states)})


@app.route("/api/resume_all", methods=['POST'])
def api_resume_all():
    token = request.args.get('token', '')
    if token != ADMIN_TOKEN:
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    for conv_id in chat_states:
        chat_states[conv_id]['paused'] = False
    return jsonify({'ok': True, 'resumed_count': len(chat_states)})


@app.route("/debug", methods=['GET'])
def debug():
    return jsonify({
        'chat_states': {k: {**v, 'is_paused': is_bot_paused(k)} for k, v in chat_states.items()},
        'last_webhook_events': last_webhook_events[:5],
        'control_url': f'/control?token={ADMIN_TOKEN}'
    })


@app.route("/", methods=['GET'])
def index():
    return 'KA Safety LINE Bot is running!'


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
