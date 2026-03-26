from flask import Flask, request, abort, jsonify
import anthropic
import os
import json
import logging
import time
import hashlib
import hmac
import base64
import requests as req

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.environ['LINE_CHANNEL_ACCESS_TOKEN']
LINE_CHANNEL_SECRET = os.environ['LINE_CHANNEL_SECRET']
ANTHROPIC_API_KEY = os.environ['ANTHROPIC_API_KEY']
ADMIN_TOKEN = os.environ.get('ADMIN_TOKEN', 'kasafety2024')

claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# เก็บ user_id ของลูกค้าแต่ละห้อง เพื่อใช้ตรวจสอบว่าใครเป็นลูกค้า
# { conv_id: { 'customer_ids': set(), 'paused': bool } }
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


def is_manually_paused(conv_id):
    """ตรวจสอบว่า Admin กด Pause ด้วยมือหรือไม่"""
    state = chat_states.get(conv_id, {})
    return state.get('paused', False)


def get_recent_messages(user_id, count=5):
    """
    ดึงข้อความล่าสุดจาก LINE Get Follow Stats API
    ใช้ Insight API เพื่อดูว่ามีข้อความจาก OA ถูกส่งออกไปล่าสุดไหม
    """
    try:
        url = f"https://api.line.me/v2/bot/message/quota/consumption"
        headers = {"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"}
        resp = req.get(url, headers=headers, timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


def check_admin_replied_recently(conv_id, customer_user_id, current_timestamp_ms):
    """
    ตรวจว่า Admin เพิ่งส่งข้อความในห้องนี้ก่อน event ปัจจุบันหรือเปล่า
    โดยเช็คจาก admin_last_reply ที่เก็บไว้ใน chat_states
    และเวลา cooldown 10 นาที
    """
    state = chat_states.get(conv_id, {})
    admin_last = state.get('admin_last_reply', 0)
    if admin_last <= 0:
        return False
    # ถ้า Admin ตอบภายใน 10 นาที ให้ Bot หยุด
    elapsed = time.time() - admin_last
    return elapsed < 600


def reply_line_message(reply_token, text):
    url = 'https://api.line.me/v2/bot/message/reply'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {LINE_CHANNEL_ACCESS_TOKEN}'
    }
    data = {
        'replyToken': reply_token,
        'messages': [{'type': 'text', 'text': text}]
    }
    resp = req.post(url, headers=headers, json=data, timeout=10)
    logger.info(f"Reply API: {resp.status_code}")
    return resp


def push_line_message(user_id, text):
    """ส่งข้อความแบบ push (ไม่ต้องมี replyToken)"""
    url = 'https://api.line.me/v2/bot/message/push'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {LINE_CHANNEL_ACCESS_TOKEN}'
    }
    data = {
        'to': user_id,
        'messages': [{'type': 'text', 'text': text}]
    }
    resp = req.post(url, headers=headers, json=data, timeout=10)
    logger.info(f"Push API: {resp.status_code}")
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

        # เก็บ events ล่าสุดไว้ debug (เก็บแค่ 10)
        last_webhook_events = (events + last_webhook_events)[:10]

        for event in events:
            ev_type = event.get('type', '')
            source = event.get('source', {})
            conv_id = get_conv_id(source)
            sender_user_id = source.get('userId', '')
            reply_token = event.get('replyToken', '')
            timestamp_ms = event.get('timestamp', 0)

            # Log ทุก event
            logger.info(f"EVENT type={ev_type} conv={conv_id} sender={sender_user_id}")

            # สนใจเฉพาะ message event
            if ev_type != 'message':
                continue

            msg = event.get('message', {})
            msg_type = msg.get('type', '')

            # บันทึก sender ว่าเป็นลูกค้าของห้องนี้
            if conv_id not in chat_states:
                chat_states[conv_id] = {
                    'paused': False,
                    'admin_last_reply': 0,
                    'customer_ids': []
                }

            # เพิ่ม sender เข้า customer_ids ถ้ายังไม่มี
            if sender_user_id and sender_user_id not in chat_states[conv_id].get('customer_ids', []):
                chat_states[conv_id].setdefault('customer_ids', []).append(sender_user_id)

            # ตรวจสอบ chatMode (ถ้า LINE ส่งมา)
            chat_mode = event.get('chatMode', '')
            if chat_mode == 'chat':
                logger.info(f"chatMode=chat -> Admin handling, bot skip")
                continue

            # ตรวจสอบ Manual Pause (กดจาก Control Panel)
            if is_manually_paused(conv_id):
                logger.info(f"Manually paused conv={conv_id}, skip")
                continue

            # ตรวจสอบ Admin cooldown
            if check_admin_replied_recently(conv_id, sender_user_id, timestamp_ms):
                elapsed = int(time.time() - chat_states[conv_id].get('admin_last_reply', 0))
                logger.info(f"Admin replied {elapsed}s ago -> bot skip conv={conv_id}")
                continue

            # ตอบเฉพาะ text message
            if msg_type != 'text' or not reply_token:
                continue

            user_text = msg.get('text', '').strip()
            logger.info(f"Bot responding to: {user_text[:60]}")

            try:
                resp = claude_client.messages.create(
                    model="claude-sonnet-4-5",
                    max_tokens=1024,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_text}]
                )
                reply_text = resp.content[0].text
                reply_line_message(reply_token, reply_text)
                logger.info(f"Bot replied successfully")

            except Exception as e:
                logger.error(f"Claude error: {e}")

    except Exception as e:
        logger.error(f"Webhook error: {e}")
        import traceback
        logger.error(traceback.format_exc())

    return 'OK'


@app.route("/admin-replied", methods=['POST'])
def admin_replied():
    """
    Admin เรียก endpoint นี้เพื่อบอกว่าเพิ่งตอบลูกค้าแล้ว
    Bot จะหยุดตอบห้องนั้น 10 นาที
    ใช้: POST /admin-replied?token=kasafety2024&conv_id=Uxxxxx
    หรือไม่ระบุ conv_id เพื่อ cooldown ทุกห้อง
    """
    token = request.args.get('token', '')
    if token != ADMIN_TOKEN:
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401

    conv_id = request.args.get('conv_id', '')
    now = time.time()

    if conv_id:
        if conv_id not in chat_states:
            chat_states[conv_id] = {'paused': False, 'admin_last_reply': 0, 'customer_ids': []}
        chat_states[conv_id]['admin_last_reply'] = now
        mins_left = 10
        return jsonify({'ok': True, 'conv_id': conv_id, 'cooldown_minutes': mins_left})
    else:
        count = 0
        for cid in chat_states:
            chat_states[cid]['admin_last_reply'] = now
            count += 1
        return jsonify({'ok': True, 'action': 'all_rooms_cooldown', 'rooms_count': count})


@app.route("/control")
def control_panel():
    token = request.args.get('token', '')
    if token != ADMIN_TOKEN:
        return '<h1>401 Unauthorized</h1>', 401

    now = time.time()
    states_html = ''

    for conv_id, state in chat_states.items():
        manual_paused = state.get('paused', False)
        admin_last = state.get('admin_last_reply', 0)
        cooldown_active = admin_last > 0 and (now - admin_last) < 600
        bot_paused = manual_paused or cooldown_active

        if cooldown_active:
            mins_left = int((600 - (now - admin_last)) / 60) + 1
            status = f'Admin ตอบล่าสุด (อีก {mins_left} นาที Bot กลับมา)'
            color = '#e67e22'
        elif manual_paused:
            status = 'หยุดโดย Admin (ถาวร)'
            color = '#e74c3c'
        else:
            status = 'Bot ทำงานปกติ'
            color = '#27ae60'

        action = 'resume' if bot_paused else 'pause'
        btn_text = 'เปิด Bot' if bot_paused else 'หยุด Bot'
        btn_color = '#27ae60' if bot_paused else '#e74c3c'
        short_id = conv_id[-8:]

        states_html += f'<div style="background:white;border-radius:12px;padding:16px;margin:10px 0;box-shadow:0 2px 8px rgba(0,0,0,0.1);display:flex;justify-content:space-between;align-items:center;"><div><div style="font-weight:bold;color:#333;">...{short_id}</div><div style="color:{color};font-size:13px;margin-top:4px;">● {status}</div></div><button onclick="controlBot(\'{conv_id}\',\'{action}\')" style="background:{btn_color};color:white;border:none;border-radius:8px;padding:10px 18px;font-size:14px;cursor:pointer;">{btn_text}</button></div>'

    if not states_html:
        states_html = '<div style="text-align:center;color:#999;padding:40px;">ยังไม่มีแชท<br><small>เมื่อลูกค้าส่งข้อความ จะแสดงที่นี่</small></div>'

    html = f"""<!DOCTYPE html>
<html lang="th"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>KA Safety Bot Control</title>
<style>
body{{margin:0;padding:0;background:#f0f4f8;font-family:-apple-system,sans-serif;}}
.header{{background:linear-gradient(135deg,#06C755,#05a847);color:white;padding:20px;text-align:center;}}
.header h1{{margin:0;font-size:22px;}}.header p{{margin:5px 0 0;opacity:.9;font-size:14px;}}
.container{{max-width:600px;margin:0 auto;padding:16px;}}
.global-btns{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:12px 0;}}
.btn{{padding:14px;border:none;border-radius:10px;font-size:16px;font-weight:bold;cursor:pointer;color:white;}}
.btn-pause{{background:#e74c3c;}}.btn-resume{{background:#27ae60;}}
.section-title{{color:#666;font-size:13px;font-weight:bold;margin:16px 0 8px;text-transform:uppercase;letter-spacing:.5px;}}
.info-box{{background:#e8f4fd;border:1px solid #3498db;border-radius:10px;padding:14px;margin:10px 0;font-size:13px;line-height:1.6;}}
.info-box b{{color:#2980b9;}}
.step{{background:white;border-radius:10px;padding:12px 16px;margin:6px 0;font-size:13px;border-left:4px solid #06C755;}}
</style></head>
<body>
<div class="header">
  <h1>🤖 KA Safety Bot Control</h1>
  <p>ควบคุม AI Bot ตอบข้อความ LINE</p>
</div>
<div class="container">
  <div class="info-box">
    <b>วิธีใช้เมื่อต้องการตอบลูกค้าเอง:</b><br>
    1️⃣ กดปุ่ม <b>"⏸ หยุด Bot ทั้งหมด"</b> ด้านล่าง<br>
    2️⃣ ตอบลูกค้าใน LINE ได้เลย<br>
    3️⃣ กด <b>"▶️ เปิด Bot ทั้งหมด"</b> เมื่อเสร็จแล้ว
  </div>

  <div class="section-title">ควบคุมทุกห้องแชท</div>
  <div class="global-btns">
    <button class="btn btn-pause" onclick="pauseAll()">⏸ หยุด Bot ทั้งหมด</button>
    <button class="btn btn-resume" onclick="resumeAll()">▶️ เปิด Bot ทั้งหมด</button>
  </div>

  <div class="section-title">ห้องแชทที่ใช้งาน ({len(chat_states)} ห้อง)</div>
  <div id="states">{states_html}</div>

  <div style="text-align:center;margin:20px 0;">
    <button onclick="location.reload()" style="background:#f8f9fa;border:1px solid #ddd;border-radius:8px;padding:10px 24px;cursor:pointer;color:#666;font-size:14px;">🔄 รีเฟรช</button>
  </div>
</div>
<script>
const token = '{token}';
async function controlBot(convId, action) {{
  try {{
    const r = await fetch('/api/' + action + '?token=' + token + '&conv_id=' + encodeURIComponent(convId), {{method:'POST'}});
    const d = await r.json();
    if(d.ok) location.reload();
    else alert('Error: ' + (d.error||'unknown'));
  }} catch(e) {{ alert('Network error'); }}
}}
async function pauseAll() {{
  try {{
    await fetch('/api/pause_all?token=' + token, {{method:'POST'}});
    location.reload();
  }} catch(e) {{ alert('Network error'); }}
}}
async function resumeAll() {{
  try {{
    await fetch('/api/resume_all?token=' + token, {{method:'POST'}});
    location.reload();
  }} catch(e) {{ alert('Network error'); }}
}}
</script>
</body></html>"""
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
        chat_states[conv_id] = {'paused': False, 'admin_last_reply': 0, 'customer_ids': []}
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
        chat_states[conv_id] = {'paused': False, 'admin_last_reply': 0, 'customer_ids': []}
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
            'is_paused': is_manually_paused(k) or cooldown_active,
            'customer_ids_count': len(v.get('customer_ids', []))
        }
    return jsonify({
        'status': 'ok',
        'chat_states': states_info,
        'last_webhook_events': last_webhook_events[:3],
        'control_url': f'/control?token={ADMIN_TOKEN}',
        'admin_replied_url': f'/admin-replied?token={ADMIN_TOKEN}&conv_id=CONV_ID_HERE'
    })


@app.route("/", methods=['GET'])
def index():
    return 'KA Safety LINE Bot is running!'


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
