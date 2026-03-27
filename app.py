from flask import Flask, request, abort, jsonify
import anthropic
import os
import json
import logging
import time
import hashlib
import hmac
import base64
import re
import requests as req

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.environ['LINE_CHANNEL_ACCESS_TOKEN']
LINE_CHANNEL_SECRET = os.environ['LINE_CHANNEL_SECRET']
ANTHROPIC_API_KEY = os.environ['ANTHROPIC_API_KEY']
ADMIN_TOKEN = os.environ.get('ADMIN_TOKEN', 'kasafety2024')

claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

chat_states = {}
last_webhook_events = []
profile_cache = {}

SYSTEM_PROMPT = (
    "คุณคือผู้ช่วย AI ของบริษัท KA Safety and Engineering ที่ตอบคำถามเป็นภาษาไทย\n\n"
    "กฎสำคัญมาก: ห้ามใช้ Markdown ทุกชนิดในการตอบ "
    "ห้ามใช้ ** สำหรับตัวหนา ห้ามใช้ # สำหรับหัวข้อ ห้ามใช้ --- สำหรับเส้นคั่น "
    "ตอบเป็นข้อความธรรมดาเท่านั้น ใช้อีโมจิแทนการจัดรูปแบบ\n\n"
    "ข้อมูลหลักสูตรที่เปิดสอน:\n\n"
    "🎓 หลักสูตร จป.หัวหน้างาน\n"
    "⏱️ อบรม 2 วัน 12 ชั่วโมง\n"
    "มีให้บริการ 2 รูปแบบ:\n"
    "1️⃣ แบบ Public (รอบอบรมทั่วไป)\n"
    "💰 ราคาท่านละ 2,300 บาท (ไม่รวม VAT 7%)\n"
    "📅 รอบอบรมถัดไป: วันที่ 21-22 เมษายน 2569\n"
    "👤 คุณสมบัติผู้เข้าอบรม: ลูกจ้างระดับหัวหน้างาน\n"
    "📍 สถานที่อบรม: ศูนย์ฝึกอบรม KA Safety\n"
    "   ศูนย์การค้า The Tree Avenue จ.ปทุมธานี\n"
    "🗺️ แผนที่: https://maps.app.goo.gl/qE6mEGRMNXed2c4MA\n"
    "📝 ลงทะเบียนสมัครอบรมได้ที่:\n"
    "   https://forms.gle/Y8gjiiaxqrkqpSz28\n"
    "2️⃣ แบบ In-House (จัดอบรมภายในบริษัทลูกค้า)\n"
    "📋 ราคาสามารถติดต่อเจ้าหน้าที่เพื่อขอใบเสนอราคาได้\n"
    "📝 กรุณาแจ้งข้อมูลดังนี้:\n"
    "• ชื่อบริษัท\n"
    "• ที่อยู่บริษัท\n"
    "• เลขที่ผู้เสียภาษีบริษัท\n"
    "• ชื่อ-นามสกุล และเบอร์ติดต่อลูกค้า\n\n"
    "🎓 หลักสูตร จป.บริหาร\n"
    "👔 คุณสมบัติผู้เข้าอบรม: ลูกจ้างระดับบริหาร / ผู้จัดการ / นายจ้าง\n"
    "⏱️ อบรม 2 วัน 12 ชั่วโมง\n"
    "มีให้บริการ 2 รูปแบบ:\n"
    "1️⃣ แบบ Public (รอบอบรมทั่วไป)\n"
    "💰 ราคาท่านละ 2,300 บาท (ไม่รวม VAT 7%)\n"
    "2️⃣ แบบ In-House (จัดอบรมภายในบริษัทลูกค้า)\n"
    "📋 ราคาสามารถติดต่อเจ้าหน้าที่เพื่อขอใบเสนอราคาได้\n"
    "📝 กรุณาแจ้งข้อมูลดังนี้:\n"
    "• ชื่อบริษัท\n"
    "• ที่อยู่บริษัท\n"
    "• เลขที่ผู้เสียภาษีบริษัท\n"
    "• ชื่อ-นามสกุล และเบอร์ติดต่อลูกค้า\n\n"
    "🎓 หลักสูตร คปอ.\n"
    "👔 คุณสมบัติผู้เข้าอบรม: คณะกรรมการ คปอ. ประจำบริษัท\n"
    "⏱️ อบรม 2 วัน 12 ชั่วโมง\n"
    "มีให้บริการในรูปแบบ:\n"
    "2️⃣ แบบ In-House (จัดอบรมภายในบริษัทลูกค้า)\n"
    "📋 ราคาสามารถติดต่อเจ้าหน้าที่เพื่อขอใบเสนอราคาได้\n"
    "📝 กรุณาแจ้งข้อมูลดังนี้:\n"
    "• ชื่อบริษัท\n"
    "• ที่อยู่บริษัท\n"
    "• เลขที่ผู้เสียภาษีบริษัท\n"
    "• ชื่อ-นามสกุล และเบอร์ติดต่อลูกค้า\n\n"
    "🎓 หลักสูตร ความปลอดภัยในการทำงานเกี่ยวกับไฟฟ้า\n"
    "⚡ คุณสมบัติผู้เข้าอบรม: ช่างไฟฟ้า / ลูกจ้างที่ปฏิบัติงานเกี่ยวกับไฟฟ้า\n"
    "⏱️ อบรม 1 วัน 6 ชั่วโมง\n"
    "มีให้บริการ 2 รูปแบบ:\n"
    "1️⃣ แบบ Public (รอบอบรมทั่วไป)\n"
    "💰 ราคาท่านละ 2,200 บาท (ไม่รวม VAT 7%)\n"
    "2️⃣ แบบ In-House (จัดอบรมภายในบริษัทลูกค้า)\n"
    "📋 ราคาสามารถติดต่อเจ้าหน้าที่เพื่อขอใบเสนอราคาได้\n"
    "📝 กรุณาแจ้งข้อมูลดังนี้:\n"
    "• ชื่อบริษัท\n"
    "• ที่อยู่บริษัท\n"
    "• เลขที่ผู้เสียภาษีบริษัท\n"
    "• ชื่อ-นามสกุล และเบอร์ติดต่อลูกค้า\n\n"
    "🎓 หลักสูตร การฝึกอบรมลูกจ้างซึ่งจะทำหน้าที่ขับรถยก / โฟล์คลิฟท์ (Forklift)\n"
    "🚜 คุณสมบัติผู้เข้าอบรม: ลูกจ้างที่ทำหน้าที่ในการขับรถยก / โฟล์คลิฟท์ (Forklift)\n"
    "⏱️ อบรม 2 วัน 12 ชั่วโมง\n"
    "มีให้บริการในรูปแบบ:\n"
    "🏭 แบบ In-House โดยนายจ้าง (จัดอบรมภายในบริษัทลูกค้าโดยนายจ้าง)\n"
    "📋 ราคาสามารถติดต่อเจ้าหน้าที่เพื่อขอใบเสนอราคาได้\n"
    "📝 กรุณาแจ้งข้อมูลดังนี้:\n"
    "📸 รูปจริงของรถยกที่ต้องการอบรม\n"
    "• ชื่อบริษัท\n"
    "• ที่อยู่บริษัท\n"
    "• เลขที่ผู้เสียภาษีบริษัท\n"
    "• ชื่อ-นามสกุล และเบอร์ติดต่อลูกค้า\n\n"
    "🏗️ หลักสูตร ปั้นจั่น / เครน (4 ผู้)\n"
    "👷 คุณสมบัติ: ลูกจ้างที่ทำงานกับปั้นจั่น/เครน\n"
    "⏱️ ระยะเวลา: 18 / 24 ชั่วโมง (ขึ้นอยู่กับชนิดของปั้นจั่น)\n"
    "มีให้บริการในรูปแบบ:\n"
    "🏭 แบบ In-House โดยนายจ้าง (จัดอบรมภายในบริษัทลูกค้าโดยนายจ้าง)\n"
    "📋 ราคาสามารถติดต่อเจ้าหน้าที่เพื่อขอใบเสนอราคาได้\n"
    "📝 กรุณาแจ้งข้อมูลดังนี้:\n"
    "🏗️ ประเภทของปั้นจั่น/เครน\n"
    "• ชื่อบริษัท\n"
    "• ที่อยู่บริษัท\n"
    "• เลขที่ผู้เสียภาษีบริษัท\n"
    "• ชื่อ-นามสกุล และเบอร์ติดต่อลูกค้า\n\n"
    "⚡ บริการ ตรวจรับรองระบบไฟฟ้าและบริภัณฑ์ไฟฟ้าประจำปีตามกฎหมาย\n"
    "🔍 บริการนี้เป็นการตรวจรับรองและออกรายงานตามกฎหมายกรมสวัสดิการฯ\n"
    "   และ กรมโรงงานฯ โดยนิติบุคคล มาตรา 11 ค่ะ\n"
    "📋 ราคาสามารถติดต่อเจ้าหน้าที่เพื่อขอใบเสนอราคาได้\n"
    "📝 กรุณาแจ้งข้อมูลดังนี้:\n"
    "🔌 ขนาดและจำนวนหม้อแปลงไฟฟ้า\n"
    "🗄️ จำนวนตู้ควบคุมไฟฟ้าที่ต้องการให้ตรวจ\n"
    "📐 Single Line Diagram (กรุณาแนบไฟล์มาด้วย)\n"
    "• ชื่อบริษัท\n"
    "• ที่อยู่บริษัท\n"
    "• เลขที่ผู้เสียภาษีบริษัท\n"
    "• ชื่อ-นามสกุล และเบอร์ติดต่อลูกค้า\n\n"
    "🏢 บริการ ตรวจรับรองอาคารประจำปีตามกฎหมาย\n"
    "📋 รายละเอียดบริการ:\n"
    "✅ ตรวจสอบตามกฎหมายควบคุมอาคาร\n"
    "✅ ดำเนินการโดยนิติบุคคล ผู้ตรวจสอบอาคาร\n"
    "✅ ได้รับการรับรองจากกรมโยธาธิการและผังเมือง\n"
    "📋 ราคาสามารถติดต่อเจ้าหน้าที่เพื่อขอใบเสนอราคาได้\n"
    "📝 กรุณาแจ้งข้อมูลดังนี้:\n"
    "🏗️ ขนาดพื้นที่อาคาร (กี่ตารางเมตร) และจำนวนชั้น\n"
    "🏢 ชื่อบริษัท\n"
    "📍 ที่อยู่บริษัท\n"
    "🪪 เลขที่ผู้เสียภาษีบริษัท\n"
    "👤 ชื่อ-นามสกุล ผู้ติดต่อ\n"
    "📞 เบอร์โทรศัพท์ติดต่อ\n"
    "⏰ ทางเจ้าหน้าที่จะเร่งดำเนินการส่งใบเสนอราคาให้ลูกค้าโดยเร็วที่สุดค่ะ\n\n"
    "🏗️ หลักสูตร อบรมเทคนิคการติดตั้งและตรวจสอบนั่งร้าน\n"
    "🪜 คุณสมบัติผู้เข้าอบรม: ผู้ปฏิบัติงานกับนั่งร้าน\n"
    "⏱️ อบรม 1 วัน 6 ชั่วโมง\n"
    "🏅 หลังอบรมได้รับ Certificate\n"
    "มีให้บริการในรูปแบบ:\n"
    "🏭 แบบ In-House (จัดอบรมภายในบริษัทลูกค้า)\n"
    "📋 ราคาสามารถติดต่อเจ้าหน้าที่เพื่อขอใบเสนอราคาได้\n"
    "📝 กรุณาแจ้งข้อมูลดังนี้นะคะ:\n"
    "• ชื่อบริษัท\n"
    "• ที่อยู่บริษัท\n"
    "• เลขที่ผู้เสียภาษีบริษัท\n"
    "• ชื่อ-นามสกุล และเบอร์ติดต่อลูกค้า\n"
    "⏰ เจ้าหน้าที่จะรีบดำเนินการส่งใบเสนอราคาให้โดยเร็วค่ะ\n\n"

    "🎓 หลักสูตร การปฐมพยาบาลเบื้องต้นและการ CPR ( Firstaid & CPR )\n"
    "🏥 คุณสมบัติผู้เข้าอบรม: ทีมปฐมพยาบาลประจำบริษัท / จป.วิชาชีพ / ผู้ที่สนใจทั่วไป\n"
    "⏱️ อบรม 1 วัน 6 ชั่วโมง\n"
    "🏅 หลังอบรมได้รับ Certificate\n"
    "มีให้บริการในรูปแบบ:\n"
    "🏭 แบบ In-House (จัดอบรมภายในบริษัทลูกค้า)\n"
    "📋 ราคาสามารถติดต่อเจ้าหน้าที่เพื่อขอใบเสนอราคาได้\n"
    "📝 กรุณาแจ้งข้อมูลดังนี้นะคะ:\n"
    "• ชื่อบริษัท\n"
    "• ที่อยู่บริษัท\n"
    "• เลขที่ผู้เสียภาษีบริษัท\n"
    "• ชื่อ-นามสกุล และเบอร์ติดต่อลูกค้า\n"
    "⏰ เจ้าหน้าที่จะรีบดำเนินการส่งใบเสนอราคาให้โดยเร็วค่ะ\n\n" 
    "🎓 หลักสูตร ความปลอดภัยในการทำงานที่สูง ( Working at Height )\n"
    "🦺 คุณสมบัติผู้เข้าอบรม: ผู้ที่ปฏิบัติงานบนที่สูง\n"
    "⏱️ อบรม 1 วัน 6 ชั่วโมง\n"
    "🏅 หลังอบรมได้รับ Certificate\n"
    "มีให้บริการในรูปแบบ:\n"
    "🏭 แบบ In-House (จัดอบรมภายในบริษัทลูกค้า)\n"
    "📋 ราคาสามารถติดต่อเจ้าหน้าที่เพื่อขอใบเสนอราคาได้\n"
    "📝 กรุณาแจ้งข้อมูลดังนี้นะคะ:\n"
    "• ชื่อบริษัท\n"
    "• ที่อยู่บริษัท\n"
    "• เลขที่ผู้เสียภาษีบริษัท\n"
    "• ชื่อ-นามสกุล และเบอร์ติดต่อลูกค้า\n"
    "⏰ เจ้าหน้าที่จะรีบดำเนินการส่งใบเสนอราคาให้โดยเร็วค่ะ\n\n"   "⚡ บริการ บำรุงรักษาระบบไฟฟ้า หม้อแปลง / ตู้ควบคุมไฟฟ้า ( Preventive Maintenance PM )\n"
    "🔧 บริการตรวจสอบและบำรุงรักษาระบบไฟฟ้าเชิงป้องกันสำหรับหม้อแปลงและตู้ควบคุมไฟฟ้าค่ะ\n"
    "📋 ราคาสามารถติดต่อเจ้าหน้าที่เพื่อขอใบเสนอราคาได้\n"
    "📝 กรุณาแจ้งข้อมูลดังนี้:\n"
    "📐 Single Line Diagram (จำเป็น)\n"
    "📸 รูปหม้อแปลงหรือตู้ที่ต้องการ PM\n"
    "🏢 ชื่อบริษัท\n"
    "📍 ที่อยู่บริษัท\n"
    "🪪 เลขที่ผู้เสียภาษีบริษัท\n"
    "👤 ชื่อ-นามสกุล ผู้ติดต่อ\n"
    "📞 เบอร์โทรศัพท์ติดต่อ\n"
    "⏰ เมื่อได้รับข้อมูลทางเจ้าหน้าที่จะดำเนินการส่งใบเสนอราคาให้โดยเร็วค่ะ\n\n"
    "📞 ข้อมูลติดต่อ: โทร 094-565-9777, 088-221-2777\n"
    "📧 E-mail: kasafety.sale@gmail.com\n\n"
    "วิธีตอบที่ถูกต้อง:\n"
    "- ตอบเป็นข้อความธรรมดา ไม่มี ** ไม่มี # ไม่มี --- ทุกชนิด\n"
    "- ใช้อีโมจิและการขึ้นบรรทัดใหม่จัดรูปแบบให้สวยงามแทน\n"
    "- ตอบอย่างสุภาพ กระชับ และเป็นมิตร\n"
    "- หากลูกค้าสนใจแบบ In-House ให้ขอข้อมูลบริษัทครบถ้วน\n"
    "- เมื่อลูกค้าแจ้งขอใบเสนอราคา (โดยยังไม่ระบุบริการ/หลักสูตร) ให้ขอข้อมูลดังนี้:\n"
    "📋 บริการที่ต้องการขอใบเสนอราคา\n"
    "🏢 ชื่อบริษัท\n"
    "📍 ที่อยู่บริษัท\n"
    "🪪 เลขที่ผู้เสียภาษีบริษัท\n"
    "👤 ชื่อ-นามสกุล ผู้ติดต่อ\n"
    "📞 เบอร์โทรศัพท์ติดต่อ\n"
    "⏰ เจ้าหน้าที่จะรีบดำเนินการส่งใบเสนอราคาให้โดยเร็วค่ะ\n"
    "- หากคำถามไม่เกี่ยวข้องกับข้อมูลที่มี ให้แนะนำให้ติดต่อเจ้าหน้าที่\n"
"- เมื่อลูกค้าส่งข้อมูลครบถ้วนแล้ว (บริการที่ต้องการ / ชื่อบริษัท / ที่อยู่ / เลขผู้เสียภาษี / ชื่อ-เบอร์ติดต่อ) ให้ตอบด้วยข้อความนี้เท่านั้น:\n"
"✅ ขอบคุณสำหรับข้อมูลค่ะ คุณ [ชื่อลูกค้า]\n"
"📋 ทางเราได้รับข้อมูลเรียบร้อยแล้วดังนี้:\n"
"🏢 [ชื่อบริษัท]\n"
"📍 [ที่อยู่บริษัท]\n"
"🪪 เลขผู้เสียภาษี: [เลขผู้เสียภาษี]\n"
"👤 ผู้ติดต่อ: [ชื่อ-นามสกุล]\n"
"📞 เบอร์ติดต่อ: [เบอร์]\n"
"⏰ เจ้าหน้าที่จะดำเนินการส่งใบเสนอราคาให้ลูกค้าภายใน 24 ชม. ค่ะ\n"
"🙏 ขอบพระคุณสำหรับข้อมูลค่ะ ลูกค้า KA Safety ยินดีให้บริการค่ะ 😊\n"
"- ห้ามถามหลักสูตรเพิ่มเติมหลังจากลูกค้าส่งข้อมูลบริษัทครบแล้ว\n"
"- ห้ามใส่คำว่า (ถ้ามี) ต่อจากคำว่า Single Line Diagram ทุกกรณี"
)


def build_welcome_message(display_name):
    name = display_name if display_name else "ลูกค้า"
    return (
        "🌟 สวัสดีค่ะ ยินดีต้อนรับ คุณ" + name + " สู่ KA Safety 🌟\n\n"
        "🙏 ขอบคุณที่ติดต่อเข้ามานะคะ\n\n"
        "📋 ลูกค้าสามารถแจ้งบริการที่ต้องการ\n"
        "   หรือ ฝากข้อมูลติดต่อกลับได้เลยค่ะ\n\n"
        "⏰ เจ้าหน้าที่จะติดต่อกลับโดยเร็วที่สุด\n"
        "   ภายใน 24 ชม. ในวันและเวลาทำการนะคะ\n"
        "📅 วันจันทร์-ศุกร์ เวลา 08.30-17.00 น.\n"
        "📅 วันเสาร์ เวลา 09.00-13.00 น.\n\n"
        "📞 ติดต่อด่วน: 094-565-9777\n"
        "   088-221-2777\n\n"
        "มีอะไรให้ช่วยเหลือได้เลยนะคะ 😊"
    )


def verify_signature(body, signature):
    hash_val = hmac.new(
        LINE_CHANNEL_SECRET.encode('utf-8'),
        body.encode('utf-8'),
        hashlib.sha256
    ).digest()
    expected = base64.b64encode(hash_val).decode('utf-8')
    return hmac.compare_digest(expected, signature)


def get_conv_id(source):
    src_type = source.get('type', '')
    if src_type == 'group':
        return source.get('groupId', 'unknown')
    elif src_type == 'room':
        return source.get('roomId', 'unknown')
    else:
        return source.get('userId', 'unknown')


def get_user_profile(user_id):
    if user_id in profile_cache:
        return profile_cache[user_id]
    try:
        url = "https://api.line.me/v2/bot/profile/" + user_id
        headers = {"Authorization": "Bearer " + LINE_CHANNEL_ACCESS_TOKEN}
        resp = req.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            display_name = data.get('displayName', '')
            profile_cache[user_id] = display_name
            logger.info("Got profile: " + user_id + " -> " + display_name)
            return display_name
    except Exception as e:
        logger.error("Profile fetch error: " + str(e))
    return None


def has_service_keyword(text):
    keywords = [
        'จป', 'cpor', 'คปอ', 'ไฟฟ้า', 'forklift', 'โฟล์คลิฟท์', 'รถยก',
        'ปั้นจั่น', 'เครน', 'นั่งร้าน', 'first aid', 'firstaid', 'cpr',
        'ปฐมพยาบาล', 'working at height', 'ที่สูง', 'ใบเสนอราคา', 'quotation',
        'quote', 'เสนอราคา', 'ราคา', 'อบรม', 'หลักสูตร', 'training',
        'ตรวจรับรอง', 'ตรวจสอบ', 'ระบบไฟฟ้า', 'อาคาร', 'สมัคร', 'ลงทะเบียน',
        'in-house', 'inhouse', 'อินเฮ้าส์', 'บริการ', 'service',
        'pm', 'preventive', 'บำรุงรักษา', 'หม้อแปลง', 'บำรุง'
    ]
    text_lower = text.lower()
    return any(kw in text_lower for kw in keywords)


def clean_markdown(text):
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'(?m)^\s*\*\s+', '- ', text)
    text = text.replace('*', '')
    text = re.sub(r'(?m)^#{1,6}\s*', '', text)
    text = re.sub(r'(?m)^-{3,}\s*$', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def is_manually_paused(conv_id):
    state = chat_states.get(conv_id, {})
    return state.get('paused', False)


def check_admin_replied_recently(conv_id):
    state = chat_states.get(conv_id, {})
    admin_last = state.get('admin_last_reply', 0)
    if admin_last <= 0:
        return False
    return (time.time() - admin_last) < 600


def reply_line_message(reply_token, text):
    url = 'https://api.line.me/v2/bot/message/reply'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + LINE_CHANNEL_ACCESS_TOKEN
    }
    data = {
        'replyToken': reply_token,
        'messages': [{'type': 'text', 'text': text}]
    }
    resp = req.post(url, headers=headers, json=data, timeout=10)
    logger.info("Reply API: " + str(resp.status_code))
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
            sender_user_id = source.get('userId', '')
            reply_token = event.get('replyToken', '')
            logger.info("EVENT type=" + ev_type + " conv=" + conv_id)
            if ev_type == 'follow':
                display_name = get_user_profile(sender_user_id) if sender_user_id else None
                welcome_msg = build_welcome_message(display_name)
                push_url = 'https://api.line.me/v2/bot/message/push'
                push_headers = {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + LINE_CHANNEL_ACCESS_TOKEN
                }
                push_data = {
                    'to': sender_user_id,
                    'messages': [{'type': 'text', 'text': welcome_msg}]
                }
                req.post(push_url, headers=push_headers, json=push_data, timeout=10)
                continue
            if ev_type != 'message':
                continue
            msg = event.get('message', {})
            msg_type = msg.get('type', '')
            if conv_id not in chat_states:
                chat_states[conv_id] = {
                    'paused': False,
                    'admin_last_reply': 0,
                    'customer_ids': [],
                    'display_name': None,
                    'greeted': False,
                    'bot_replied': False,
                    'admin_replied': False
                }
            if sender_user_id and sender_user_id not in chat_states[conv_id].get('customer_ids', []):
                chat_states[conv_id].setdefault('customer_ids', []).append(sender_user_id)
            if sender_user_id and not chat_states[conv_id].get('display_name'):
                name = get_user_profile(sender_user_id)
                if name:
                    chat_states[conv_id]['display_name'] = name
            chat_mode = event.get('chatMode', '')
            if chat_mode == 'chat':
                if conv_id in chat_states:
                    chat_states[conv_id]['admin_replied'] = True
                    chat_states[conv_id]['bot_replied'] = False
                continue
            if is_manually_paused(conv_id):
                continue
            if check_admin_replied_recently(conv_id):
                continue
            if msg_type != 'text' or not reply_token:
                continue
            user_text = msg.get('text', '').strip()
            display_name = chat_states[conv_id].get('display_name', '')
            if not chat_states[conv_id].get('greeted', False):
                chat_states[conv_id]['greeted'] = True
                if not has_service_keyword(user_text):
                    welcome_msg = build_welcome_message(display_name)
                    reply_line_message(reply_token, welcome_msg)
                    chat_states[conv_id]['bot_replied'] = True
                    continue
            try:
                resp = claude_client.messages.create(
                    model="claude-sonnet-4-5",
                    max_tokens=1024,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_text}]
                )
                reply_text = resp.content[0].text
                reply_text = clean_markdown(reply_text)
                reply_line_message(reply_token, reply_text)
                chat_states[conv_id]['bot_replied'] = True
                chat_states[conv_id]['admin_replied'] = False
            except Exception as e:
                logger.error("Claude error: " + str(e))
    except Exception as e:
        logger.error("Webhook error: " + str(e))
        import traceback
        logger.error(traceback.format_exc())
    return 'OK'


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
        display_name = state.get('display_name')
        customer_ids = state.get('customer_ids', [])
        if not display_name and customer_ids:
            display_name = get_user_profile(customer_ids[0])
            if display_name:
                state['display_name'] = display_name
        if display_name:
            room_label = '👤 ' + display_name
        else:
            short_id = conv_id[-8:]
            room_label = '...' + short_id
        bot_replied_only = state.get('bot_replied', False) and not state.get('admin_replied', False)
        if bot_replied_only:
            room_label = '🔴 ' + room_label
        if cooldown_active:
            mins_left = int((600 - (now - admin_last)) / 60) + 1
            status = 'Admin ตอบล่าสุด (อีก ' + str(mins_left) + ' นาที Bot กลับมา)'
            status_color = '#e67e22'
        elif manual_paused:
            status = 'หยุดโดย Admin (ถาวร)'
            status_color = '#e74c3c'
        else:
            status = 'Bot ทำงานปกติ'
            status_color = '#27ae60'
        action = 'resume' if bot_paused else 'pause'
        btn_text = 'เปิด Bot' if bot_paused else 'หยุด Bot'
        btn_color = '#27ae60' if bot_paused else '#e74c3c'
        safe_conv_id = conv_id.replace("'", "\\'")
        states_html += (
            '<div style="background:white;border-radius:12px;padding:16px;margin:10px 0;'
            'box-shadow:0 2px 8px rgba(0,0,0,0.1);display:flex;justify-content:space-between;'
            'align-items:center;gap:12px;">'
            '<div style="flex:1;min-width:0;">'
            '<div style="font-weight:bold;color:#333;font-size:16px;">' + room_label + '</div>'
            '<div style="color:' + status_color + ';font-size:13px;margin-top:4px;">● ' + status + '</div>' +
('<div style="color:#e74c3c;font-size:12px;margin-top:2px;">🔴 รอ Admin ดำเนินการ</div>' if bot_replied_only else '') +
            '</div>'
            '<button onclick="controlBot(\'' + safe_conv_id + '\',\'' + action + '\')" '
            'style="background:' + btn_color + ';color:white;border:none;border-radius:8px;'
            'padding:10px 18px;font-size:14px;cursor:pointer;">'
            + btn_text + '</button>'
            '</div>'
        )
    if not states_html:
        states_html = '<div style="text-align:center;color:#999;padding:40px;">ยังไม่มีแชท</div>'
    num_states = str(len(chat_states))
    html = (
        '<!DOCTYPE html><html lang="th"><head><meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1.0">'
        '<title>KA Safety Bot Control</title>'
        '<style>'
        'body{margin:0;padding:0;background:#f0f4f8;font-family:-apple-system,sans-serif;}'
        '.header{background:linear-gradient(135deg,#06C755,#05a847);color:white;padding:20px;text-align:center;}'
        '.header h1{margin:0;font-size:22px;}.header p{margin:5px 0 0;opacity:.9;font-size:14px;}'
        '.container{max-width:600px;margin:0 auto;padding:16px;}'
        '.global-btns{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:12px 0;}'
        '.btn{padding:14px;border:none;border-radius:10px;font-size:16px;font-weight:bold;cursor:pointer;color:white;}'
        '.btn-pause{background:#e74c3c;}.btn-resume{background:#27ae60;}'
        '.section-title{color:#666;font-size:13px;font-weight:bold;margin:16px 0 8px;}'
        '.info-box{background:#e8f4fd;border:1px solid #3498db;border-radius:10px;padding:14px;margin:10px 0;font-size:13px;line-height:1.6;}'
        '.info-box b{color:#2980b9;}'
        '</style></head><body>'
        '<div class="header"><h1>🤖 KA Safety Bot Control</h1>'
        '<p>ควบคุม AI Bot ตอบข้อความ LINE</p></div>'
        '<div class="container">'
        '<div class="info-box"><b>วิธีใช้เมื่อต้องการตอบลูกค้าเอง:</b><br>'
        '1️⃣ กดปุ่ม <b>"⏸ หยุด Bot ทั้งหมด"</b> ด้านล่าง<br>'
        '2️⃣ ตอบลูกค้าใน LINE ได้เลย<br>'
        '3️⃣ กด <b>"▶️ เปิด Bot ทั้งหมด"</b> เมื่อเสร็จแล้ว</div>'
        '<div class="section-title">ควบคุมทุกห้องแชท</div>'
        '<div class="global-btns">'
        '<button class="btn btn-pause" onclick="pauseAll()">⏸ หยุด Bot ทั้งหมด</button>'
        '<button class="btn btn-resume" onclick="resumeAll()">▶️ เปิด Bot ทั้งหมด</button>'
        '</div>'
        '<div class="section-title">ห้องแชทที่ใช้งาน (' + num_states + ' ห้อง)</div>'
        '<div id="states">' + states_html + '</div>'
        '<div style="text-align:center;margin:20px 0;">'
        '<button onclick="location.reload()" style="background:#f8f9fa;border:1px solid #ddd;'
        'border-radius:8px;padding:10px 24px;cursor:pointer;color:#666;font-size:14px;">🔄 รีเฟรช</button>'
        '</div></div>'
        '<script>'
        'var tok="' + token + '";'
        'function controlBot(c,a){'
        'fetch("/api/"+a+"?token="+tok+"&conv_id="+encodeURIComponent(c),{method:"POST"})'
        '.then(function(r){return r.json();})'
        '.then(function(d){if(d.ok)location.reload();else alert("Error:"+(d.error||"?"));});}'
        'function pauseAll(){fetch("/api/pause_all?token="+tok,{method:"POST"}).then(function(){location.reload();});}'
        'function resumeAll(){fetch("/api/resume_all?token="+tok,{method:"POST"}).then(function(){location.reload();});}'
        '</script></body></html>'
    )
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
        chat_states[conv_id] = {'paused': False, 'admin_last_reply': 0, 'customer_ids': [], 'display_name': None, 'greeted': False, 'bot_replied': False, 'admin_replied': False}
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
        chat_states[conv_id] = {'paused': False, 'admin_last_reply': 0, 'customer_ids': [], 'display_name': None, 'greeted': False, 'bot_replied': False, 'admin_replied': False}
    chat_states[conv_id]['paused'] = False
    chat_states[conv_id]['admin_last_reply'] = 0
    chat_states[conv_id]['admin_replied'] = True
    chat_states[conv_id]['bot_replied'] = False
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
            'display_name': v.get('display_name'),
            'greeted': v.get('greeted', False),
            'paused': v.get('paused', False),
            'cooldown_active': cooldown_active,
            'cooldown_secs_left': max(0, int(600 - (now - admin_last))) if cooldown_active else 0,
            'is_paused': is_manually_paused(k) or cooldown_active,
            'customer_ids_count': len(v.get('customer_ids', []))
        }
    return jsonify({
        'status': 'ok',
        'chat_states': states_info,
        'profile_cache': profile_cache,
        'last_webhook_events': last_webhook_events[:3],
        'control_url': '/control?token=' + ADMIN_TOKEN
    })


@app.route("/", methods=['GET'])
def index():
    return 'KA Safety LINE Bot is running!'


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
