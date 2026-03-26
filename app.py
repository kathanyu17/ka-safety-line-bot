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

ADMIN_TOKEN = os.environ.get('ADMIN_TOKEN', 'kasafety2024')

chat_states = {}

def is_bot_paused(conversation_id):
        state = chat_states.get(conversation_id, {})
        if state.get('paused', False):
                    return True
                return False

def get_conversation_id(event):
        src = event.source
    if hasattr(src, 'group_id'): return src.group_id
elif hasattr(src, 'room_id'): return src.room_id
elif hasattr(src, 'user_id'): return src.user_id
    return 'unknown'

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
        conv_id = get_conversation_id(event)
    user_message = event.message.text.strip()
    logger.info(f"MSG in {conv_id}: {user_message[:50]}")

    if is_bot_paused(conv_id):
                logger.info(f"Bot paused for {conv_id}, skipping")
                return

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
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

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
                states_html += f'''
                <div style="background:white;border-radius:12px;padding:16px;margin:10px 0;box-shadow:0 2px 8px rgba(0,0,0,0.1);display:flex;justify-content:space-between;align-items:center;">
                    <div>
                        <div style="font-weight:bold;color:#333;">...{short_id}</div>
                        <div style="color:{color};font-size:14px;margin-top:4px;">● {status}</div>
                    </div>
                    <button onclick="controlBot('{conv_id}','{action}')" style="background:{btn_color};color:white;border:none;border-radius:8px;padding:10px 20px;font-size:15px;cursor:pointer;">{btn_text}</button>
                </div>'''

            if not states_html:
                states_html = '<div style="text-align:center;color:#999;padding:40px;">ยังไม่มีแชท<br><small>Bot จะแสดงแชทที่ได้รับข้อความที่นี่</small></div>'

            return f'''<!DOCTYPE html>
        <html lang="th">
        <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>KA Safety Bot Control</title>
        <style>
        body{{margin:0;padding:0;background:#f0f4f8;font-family:-apple-system,BlinkMacSystemFont,sans-serif;}}
        .header{{background:linear-gradient(135deg,#06C755,#05a847);color:white;padding:20px;text-align:center;}}
        .header h1{{margin:0;font-size:22px;}}
        .header p{{margin:5px 0 0;opacity:0.9;font-size:14px;}}
        .container{{max-width:600px;margin:0 auto;padding:16px;}}
        .global-btns{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:16px 0;}}
        .btn{{padding:14px;border:none;border-radius:10px;font-size:16px;font-weight:bold;cursor:pointer;color:white;}}
        .btn-pause{{background:#e74c3c;}}
        .btn-resume{{background:#27ae60;}}
        .section-title{{color:#666;font-size:13px;font-weight:bold;text-transform:uppercase;margin:20px 0 8px;letter-spacing:1px;}}
        .status-bar{{background:white;border-radius:10px;padding:12px 16px;margin-bottom:16px;display:flex;align-items:center;gap:10px;box-shadow:0 2px 8px rgba(0,0,0,0.08);}}
        </style>
        </head>
        <body>
        <div class="header">
            <h1>🤖 KA Safety Bot Control</h1>
            <p>ควบคุม Bot ตอบข้อความ LINE</p>
        </div>
        <div class="container">
            <div style="margin:16px 0;">
                <div class="section-title">ควบคุมทุกห้องแชท</div>
                <div class="global-btns">
                    <button class="btn btn-pause" onclick="pauseAll()">⏸ หยุด Bot ทั้งหมด</button>
                    <button class="btn btn-resume" onclick="resumeAll()">▶️ เปิด Bot ทั้งหมด</button>
                </div>
            </div>
            <div class="section-title">ห้องแชทที่ใช้งาน</div>
            <div id="states">{states_html}</div>
            <div style="text-align:center;margin:20px 0;">
                <button onclick="location.reload()" style="background:#f8f9fa;border:1px solid #ddd;border-radius:8px;padding:10px 24px;cursor:pointer;color:#666;">🔄 รีเฟรช</button>
            </div>
        </div>
        <script>
const token = '{token}';
async function controlBot(convId, action) {{
    const r = await fetch(`/api/${{action}}?token=${{token}}&conv_id=${{encodeURIComponent(convId)}}`, {{method:'POST'}});
    const d = await r.json();
    if(d.ok) location.reload();
    else alert('เกิดข้อผิดพลาด: ' + d.error);
}}
async function pauseAll() {{
    await fetch(`/api/pause_all?token=${{token}}`, {{method:'POST'}});
    location.reload();
}}
async function resumeAll() {{
    await fetch(`/api/resume_all?token=${{token}}`, {{method:'POST'}});
    location.reload();
}}
</script>
</body>
</html>'''

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
    logger.info(f"Bot paused for {conv_id} via control panel")
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
    logger.info(f"Bot resumed for {conv_id} via control panel")
    return jsonify({'ok': True, 'conv_id': conv_id, 'paused': False})

@app.route("/api/pause_all", methods=['POST'])
def api_pause_all():
    token = request.args.get('token', '')
    if token != ADMIN_TOKEN:
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    for conv_id in chat_states:
        chat_states[conv_id]['paused'] = True
    logger.info("All bots paused via control panel")
    return jsonify({'ok': True, 'paused_count': len(chat_states)})

@app.route("/api/resume_all", methods=['POST'])
def api_resume_all():
    token = request.args.get('token', '')
    if token != ADMIN_TOKEN:
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    for conv_id in chat_states:
        chat_states[conv_id]['paused'] = False
    logger.info("All bots resumed via control panel")
    return jsonify({'ok': True, 'resumed_count': len(chat_states)})

@app.route("/debug", methods=['GET'])
def debug():
    return jsonify({
        'admin_token_set': bool(ADMIN_TOKEN),
        'chat_states': {k: {**v, 'is_paused': is_bot_paused(k)} for k, v in chat_states.items()},
        'control_url': f'/control?token={ADMIN_TOKEN}'
})

@app.route("/", methods=['GET'])
def index():
    return 'KA Safety LINE Bot is running! Control panel: /control?token=YOUR_TOKEN'

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
