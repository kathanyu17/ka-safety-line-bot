from flask import Flask, request, abort, jsonify
import anthropic
import os
import json
import logging
import time
import hashlib
import hmac
import base64

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.environ['LINE_CHANNEL_ACCESS_TOKEN']
LINE_CHANNEL_SECRET = os.environ['LINE_CHANNEL_SECRET']
ANTHROPIC_API_KEY = os.environ['ANTHROPIC_API_KEY']
ADMIN_TOKEN = os.environ.get('ADMIN_TOKEN', 'kasafety2024')

claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# { conv_id: { 'paused': bool, 'admin_last_reply': float } }
chat_states = {}
last_webhook_events = []

SYSTEM_PROMPT = """คุณคือผู้ช่วย AI ของบริษัท KA Safety and Engineering ที่ตอบคำถามเป็นภาษาไทย
ข้อมูลหลักสูตรที่เปิดสอน:
- หลักสูตร จป.หัวหน้างาน / จป.บริหาร / คปอ.
- ระยะเวลาอบรม: 2 วัน 12 ชั่วโมง
- คุณสมบัติผู้เข้าอบรม: เป็นลูกจ้างระดับหัวหน้างานหรือผู้บังคับบัญชา
ข้อมูลติดต่อ:
- โทร 094-565-9777, 088-221-2777
- E-mail: kasafety.sale@gmail.com
กรุณาตอบคำถามของลูกค้าอย่างสุภาพและเป็นประโยชน์ โดยอ้างอิงข้อมูลด้านบนในการตอบ
หากคำถามไม่เกี่ยวข้องกับข้อมูลที่มี ให้ตอบตามความรู้ทั่วไปและแนะนำให้ติดต่อเจ้าหน้าที่หากต้องการข้อมูลเพิ่มเติม"""

def verify_signature(body, signature):
    hash_val = hmac.new(LINE_CHANNEL_SECRET.encode('utf-8'), body.encode('utf-8'), hashlib.sha256).digest()
    expected = base64.b64encode(hash_val).decode('utf-8')
    return hmac.compare_digest(expected, signature)

def get_conv_id(source):
    if source.get('type') == 'group':
        return source.get('groupId', 'unknown')
    elif source.get('type') == 'room':
        return source.get('roomId', 'unknown')
    else:
        return source.get('userId', 'unknown')

def is_paused(conv_id):
    state = chat_states.get(conv_id, {})
    if state.get('paused', False):
        return True
    admin_last = state.get('admin_last_reply', 0)
    if admin_last > 0 and (time.time() - admin_last) < 600:
        return True
    return False

def reply_message(reply_token, text):
    import requests as req
    url = 'https://api.line.me/v2/bot/message/reply'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {LINE_CHANNEL_ACCESS_TOKEN}'
    }
    data = {
        'replyToken': reply_token,
        'messages': [{'type': 'text', 'text': text}]
    }
    resp = req.post(url, headers=headers, json=data)
    logger.info(f"Reply status: {resp.status_code}")
    return resp

@app.route("/webhook", methods=['POST'])
def webhook():
    global last_webhook_events
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)

    if not verify_signature(body, signature):
        logger.error("Invalid signature")
        abort(400)

    try:
        body_json = json.loads(body)
        events = body_json.get('events', [])
        last_webhook_events = (events + last_webhook_events)[:10]

        for event in events:
            ev_type = event.get('type', '')
            source = event.get('source', {})
            conv_id = get_conv_id(source)
            user_id = source.get('userId', '')
            chat_mode = event.get('chatMode', '')
            reply_token = event.get('replyToken', '')

            logger.info(f"EVENT type={ev_type} conv={conv_id} user={user_id} chatMode='{chat_mode}'")

            if ev_type == 'message':
                msg = event.get('message', {})
                msg_type = msg.get('type', '')

                if chat_mode == 'chat':
                    logger.info(f"chatMode=chat -> Admin handling, bot skip")
                    continue

                if is_paused(conv_id):
                    logger.info(f"Bot paused for {conv_id}, skip")
                    continue

                if msg_type == 'text' and reply_token:
                    user_text = msg.get('text', '').strip()
                    logger.info(f"Responding to: {user_text[:50]}")

                    try:
                        resp = claude_client.messages.create(
                            model="claude-sonnet-4-5",
                            max_tokens=1024,
                            system=SYSTEM_PROMPT,
                            messages=[{"role": "user", "content": user_text}]
                        )
                        reply_text = resp.content[0].text
                        reply_message(reply_token, reply_text)

                        if conv_id not in chat_states:
                            chat_states[conv_id] = {}
                        chat_states[conv_id]['last_customer_id'] = user_id

                    except Exception as e:
                        logger.error(f"Claude error: {e}")

    except Exception as e:
        logger.error(f"Webhook error: {e}")

    return 'OK'

@app.route("/control")
def control_panel():
    token = request.args.get('token', '')
    if token != ADMIN_TOKEN:
        return '<h1>401 Unauthorized</h1>', 401

    states_html = ''
    for conv_id, state in chat_states.items():
        manual_paused = state.get('paused', False)
        admin_last = state.get('admin_last_reply', 0)
        cooldown_active = admin_last > 0 and (time.time() - admin_last) < 600
        bot_paused = manual_paused or cooldown_active

        if cooldown_active:
            mins_left = int((600 - (time.time() - admin_last)) / 60) + 1
            status = f'รอ {mins_left} นาที'
            color = '#e67e22'
        elif manual_paused:
            status = 'หยุดโดย Admin'
            color = '#e74c3c'
        else:
            status = 'Bot ทำงาน'
            color = '#27ae60'

        action = 'resume' if bot_paused else 'pause'
        btn_text = 'เปิด Bot' if bot_paused else 'หยุด Bot'
        btn_color = '#27ae60' if bot_paused else '#e74c3c'
        short_id = conv_id[-8:]

        states_html += f'<div style="background:white;border-radius:12px;padding:16px;margin:10px 0;box-shadow:0 2px 8px rgba(0,0,0,0.1);display:flex;justify-content:space-between;align-items:center;"><div><div style="font-weight:bold;color:#333;">...{short_id}</div><div style="color:{color};font-size:14px;margin-top:4px;">● {status}</div></div><button onclick="controlBot(\'{conv_id}\',\'{action}\')" style="background:{btn_color};color:white;border:none;border-radius:8px;padding:10px 20px;font-size:15px;cursor:pointer;">{btn_text}</button></div>'

    if not states_html:
        states_html = '<div style="text-align:center;color:#999;padding:40px;">ยังไม่มีแชท<br><small>เมื่อลูกค้าส่งข้อความ จะแสดงที่นี่</small></div>'

    html = f"""<!DOCTYPE html>
<html lang="th"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>KA Safety Bot Control</title>
<style>body{{margin:0;padding:0;background:#f0f4f8;font-family:-apple-system,sans-serif;}}
.header{{background:linear-gradient(135deg,#06C755,#05a847);color:white;padding:20px;text-align:center;}}
.header h1{{margin:0;font-size:22px;}}.header p{{margin:5px 0 0;opacity:.9;font-size:14px;}}
.container{{max-width:600px;margin:0 auto;padding:16px;}}
.global-btns{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:16px 0;}}
.btn{{padding:14px;border:none;border-radius:10px;font-size:16px;font-weight:bold;cursor:pointer;color:white;}}
.btn-pause{{background:#e74c3c;}}.btn-resume{{background:#27ae60;}}
.section-title{{color:#666;font-size:13px;font-weight:bold;margin:20px 0 8px;}}
.info-box{{background:#fff3cd;border:1px solid #ffc107;border-radius:10px;padding:14px;margin:10px 0;font-size:13px;}}
</style></head>
<body>
<div class="header"><h1>🤖 KA Safety Bot Control</h1><p>ควบคุม Bot ตอบข้อความ LINE</p></div>
<div class="container">
<div class="info-box">💡 กด "⏸ หยุด Bot ทั้งหมด" ก่อนตอบลูกค้า แล้วกด "▶️ เปิด Bot" เมื่อเสร็จแล้ว</div>
<div class="section-title">ควบคุมทุกห้องแชท</div>
<div class="global-btns">
<button class="btn btn-pause" onclick="pauseAll()">⏸ หยุด Bot ทั้งหมด</button>
<button class="btn btn-resume" onclick="resumeAll()">▶️ เปิด Bot ทั้งหมด</button>
</div>
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
  if(d.ok) location.reload(); else alert('Error: ' + (d.error||'unknown'));
}}
async function pauseAll() {{
  await fetch('/api/pause_all?token=' + token, {{method:'POST'}});
  location.reload();
}}
async function resumeAll() {{
  await fetch('/api/resume_all?token=' + token, {{method:'POST'}});
  location.reload();
}}
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
    chat_states[conv_id]['admin_last_reply'] = 0
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
        chat_states[conv_id]['admin_last_reply'] = 0
    return jsonify({'ok': True, 'resumed_count': len(chat_states)})

@app.route("/debug")
def debug():
    now = time.time()
    states_info = {}
    for k, v in chat_states.items():
        admin_last = v.get('admin_last_reply', 0)
        cooldown_active = admin_last > 0 and (now - admin_last) < 600
        states_info[k] = {
            'paused': v.get('paused', False),
            'cooldown_active': cooldown_active,
            'cooldown_secs_left': max(0, int(600 - (now - admin_last))) if cooldown_active else 0,
            'is_paused': is_paused(k)
        }
    return jsonify({
        'status': 'ok',
        'chat_states': states_info,
        'last_webhook_events': last_webhook_events[:5],
        'control_url': f'/control?token={ADMIN_TOKEN}'
    })

@app.route("/", methods=['GET'])
def index():
    return 'KA Safety LINE Bot is running!'

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
