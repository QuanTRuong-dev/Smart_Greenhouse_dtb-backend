import paho.mqtt.client as mqtt
import json
import psycopg2
from datetime import datetime

# ==========================================
# CẤU HÌNH
# ==========================================
DB_CONFIG = {
    "host": "localhost",
    "port": "5432",
    "dbname": "farm_database",
    "user": "farm_admin",
    "password": "supersecret_pass"
}

MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
MQTT_TOPIC_SENSORS = "greenframbku/sensors"
MQTT_TOPIC_CMD = "greenframbku/cmd"
MQTT_TOPIC_SYNC_REQUEST = "greenframbku/sync_request"   
MQTT_TOPIC_SYNC_RESPONSE = "greenframbku/sync_response" 

# ==========================================
# HÀM GỬI TRẠNG THÁI ĐỒNG BỘ CHO ESP32
# ==========================================
def send_sync_response(client):
    """
    Đọc trạng thái từ Database và gửi cho ESP32
    Format: SYNC|section_id|is_auto_pump|is_auto_light|is_auto_fan|pump_state|led_brightness
    """
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT section_id, is_auto 
            FROM thresholds 
            ORDER BY section_id
        """)
        
        cursor.execute("""
            SELECT section_id, is_auto_pump, is_auto_light, is_auto_fan
            FROM thresholds ORDER BY section_id
        """)
        thresholds = cursor.fetchall()
        
        cursor.execute("""
            SELECT ts.section_id, ts.pump_status, ts.led_pwm, ts.fan_status
            FROM telemetry_sections ts
            INNER JOIN (
                SELECT section_id, MAX(id) as max_id
                FROM telemetry_sections
                GROUP BY section_id
            ) latest ON ts.section_id = latest.section_id AND ts.id = latest.max_id
        """)
        device_states = {row[0]: {'pump': row[1], 'led': row[2], 'fan': row[3]} for row in cursor.fetchall()}
        
        for sec_id, is_auto_pump, is_auto_light, is_auto_fan in thresholds:
            st = device_states.get(sec_id, {'pump': False, 'led': 0, 'fan': False})

            
            sync_msg = f"SYNC|{sec_id}|{int(is_auto_pump)}|{int(is_auto_light)}|{int(is_auto_fan)}|{int(st['pump'])}|{st['led']}|{int(st['fan'])}"  
            
            client.publish(MQTT_TOPIC_SYNC_RESPONSE, sync_msg)
            print(f"📤 [SYNC] Sent: {sync_msg}")
        cursor.close()
        conn.close()
        print(f"✅ [SYNC] Đã gửi đồng bộ cho cả 3 khu vực")
        
    except Exception as e:
        print(f"❌ [SYNC] Lỗi gửi trạng thái: {e}")

# ==========================================
# 1. HÀM LƯU DỮ LIỆU VÀO DB
# ==========================================
def save_to_db(data):
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()

        air = data.get('air', {})
        water_lvl = data.get('water_lvl', 0)
        
        cursor.execute("""
            INSERT INTO telemetry_packets (air_temp, air_humid, water_level) 
            VALUES (%s, %s, %s) RETURNING id;
        """, (air.get('t'), air.get('h'), water_lvl))
        packet_id = cursor.fetchone()[0]

        for i in range(1, 4):
            sec_key = f's{i}'
            if sec_key in data:
                sec = data[sec_key]
                # Đã update các Key này cho trùng với snapshot payload của ESP32 hiện tại
                is_pump_on = bool(sec.get('pump_status'))
                cursor.execute("""
                    INSERT INTO telemetry_sections 
                    (packet_id, section_id, soil_percent, light_percent, pump_status, led_pwm, fan_status) 
                    VALUES (%s, %s, %s, %s, %s, %s);
                """, (packet_id, i, sec.get('soil'), sec.get('light'), bool(sec.get('pump_status')), sec.get('led_brightness'), bool(sec.get('fan_status'))))

        conn.commit()
        cursor.close()
        conn.close()
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Đã lưu DB - Packet: {packet_id}")

    except Exception as e:
        print(f"Lỗi Lưu DB: {e}")

# ==========================================
# 2. KẾT NỐI VÀ LẮNG NGHE MQTT
# ==========================================
def on_connect(client, userdata, flags, rc):
    print("✅ Đã kết nối HiveMQ Public Broker!")
    client.subscribe(MQTT_TOPIC_SENSORS)
    client.subscribe(MQTT_TOPIC_SYNC_REQUEST)  
    print(f"📡 Đang túc trực trên kênh {MQTT_TOPIC_SENSORS} và {MQTT_TOPIC_SYNC_REQUEST}...")

def on_message(client, userdata, msg):
    try:
        if msg.topic == MQTT_TOPIC_SYNC_REQUEST:
            payload = msg.payload.decode("utf-8")
            print(f"📨 [SYNC] Nhận yêu cầu: {payload}")
            if payload == "REQUEST_SYNC":
                send_sync_response(client)
            return
        
        if msg.topic == MQTT_TOPIC_SENSORS:
            payload = json.loads(msg.payload.decode("utf-8"))
            save_to_db(payload)              # Chỉ lưu sổ sách
            
    except Exception as e:
        print(f"Lỗi đọc Data: {e}")

client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message

print("🚀 Đang khởi động MQTT Subscriber...")
client.connect(MQTT_BROKER, MQTT_PORT, 60)
client.loop_forever()