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

# ==========================================
# 1. HÀM LƯU DỮ LIỆU
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
                #is_pump_on = bool(sec.get('pump'))
                cursor.execute("""
                    INSERT INTO telemetry_sections 
                    (packet_id, section_id, soil_percent, light_percent, pump_status, led_pwm) 
                    VALUES (%s, %s, %s, %s, %s, %s);
                """, (packet_id, i, sec.get('soil'), sec.get('light'), sec.get('pump'), sec.get('led')))

        conn.commit()
        cursor.close()
        conn.close()
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Đã lưu DB - Packet: {packet_id}")

    except Exception as e:
        print(f"Lỗi Lưu DB: {e}")

# ==========================================
# 2. HÀM TỰ ĐỘNG HÓA (THRESHOLD CHECK)
# ==========================================
def check_and_control(client, data):
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        # Kéo ngưỡng cấu hình từ Database lên
        cursor.execute("SELECT section_id, soil_min, light_min, water_min, temp_max FROM thresholds;")
        thresholds = {row[0]: {'soil_min': row[1], 'light_min': row[2], 'water_min': row[3], 'temp_max': row[4]} for row in cursor.fetchall()}
        
        water_lvl = data.get('water_lvl', 0)
        air_temp = data.get('air', {}).get('t', 0)
        
        # Cảnh báo Nhiệt độ cao (Lấy temp_max từ section 1 làm chuẩn chung)
        if 1 in thresholds and air_temp > thresholds[1]['temp_max']:
            cursor.execute("INSERT INTO alerts (alert_type, message) VALUES (%s, %s)", 
                           ("TEMP_HIGH", f"CẢNH BÁO NÓNG: Nhiệt độ hiện tại ({air_temp}°C) vượt ngưỡng an toàn!"))
            print(f"🔥 AUTO: Đã ghi nhận cảnh báo Nhiệt độ cao ({air_temp}°C)")
        
        for i in range(1, 4):
            sec_key = f's{i}'
            if sec_key in data and i in thresholds:
                sec = data[sec_key]
                thresh = thresholds[i]
                
                # --- LOGIC MÁY BƠM ---
                if water_lvl < thresh['water_min']:
                    # Cạn nước: Ghi cảnh báo, cấm bơm
                    cursor.execute("INSERT INTO alerts (alert_type, message) VALUES (%s, %s)", 
                                   ("WATER_LOW", f"Bồn cạn ({water_lvl}cm). Không thể tưới Khu {i}!"))
                    
                    if sec.get('pump') == 1: # Nếu bơm đang chạy thì phải ép tắt ngay
                        client.publish(MQTT_TOPIC_CMD, f"PUMP_{i}_OFF")
                else:
                    # Đủ nước: Kiểm tra đất
                    if sec.get('soil') < thresh['soil_min'] and sec.get('pump') == 0:
                        client.publish(MQTT_TOPIC_CMD, f"PUMP_{i}_ON")
                        cursor.execute("INSERT INTO control_logs (username, device, action, source) VALUES (%s, %s, %s, %s)",
                                       ('system', f'Máy bơm {i}', 'BẬT', 'Auto Threshold'))
                        print(f"🤖 AUTO: Đã BẬT Bơm {i} (Đất khô: {sec.get('soil')}%)")

                    # Thêm độ trễ để tránh bơm tắt chớp nhoáng (Đất ẩm hơn ngưỡng 15% thì mới dừng)
                    elif sec.get('soil') >= (thresh['soil_min'] + 15) and sec.get('pump') == 1:
                        client.publish(MQTT_TOPIC_CMD, f"PUMP_{i}_OFF")
                        cursor.execute("INSERT INTO control_logs (username, device, action, source) VALUES (%s, %s, %s, %s)",
                                       ('system', f'Máy bơm {i}', 'TẮT', 'Auto Threshold'))
                        print(f"🤖 AUTO: Đã TẮT Bơm {i} (Đất đã đủ ẩm: {sec.get('soil')}%)")

                # --- LOGIC ĐÈN LED ---
                if sec.get('light') < thresh['light_min'] and sec.get('led') == 0:
                    client.publish(MQTT_TOPIC_CMD, f"LIGHT_{i}_SET_255")
                    cursor.execute("INSERT INTO control_logs (username, device, action, pwm, source) VALUES (%s, %s, %s, %s, %s)",
                                   ('system', f'Đèn LED {i}', 'CẬP NHẬT', 255, 'Auto Threshold'))
                    print(f"🤖 AUTO: Đã BẬT Đèn {i} sáng 100% (Trời tối: {sec.get('light')}%)")
                    
                elif sec.get('light') >= (thresh['light_min'] + 20) and sec.get('led') > 0:
                    client.publish(MQTT_TOPIC_CMD, f"LIGHT_{i}_SET_0")
                    cursor.execute("INSERT INTO control_logs (username, device, action, pwm, source) VALUES (%s, %s, %s, %s, %s)",
                                   ('system', f'Đèn LED {i}', 'TẮT', 0, 'Auto Threshold'))
                    print(f"🤖 AUTO: Đã TẮT Đèn {i} (Trời đã sáng)")

        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Lỗi Auto Threshold: {e}")

# ==========================================
# 3. KẾT NỐI VÀ LẮNG NGHE MQTT
# ==========================================
def on_connect(client, userdata, flags, rc):
    print("✅ Đã kết nối HiveMQ Public Broker!")
    client.subscribe(MQTT_TOPIC_SENSORS)
    print(f"📡 Đang túc trực trên kênh {MQTT_TOPIC_SENSORS}...")

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
        save_to_db(payload)              # Bước 1: Lưu sổ sách
        check_and_control(client, payload) # Bước 2: Máy tự ra quyết định
    except Exception as e:
        print(f"Lỗi đọc Data: {e}")

client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message

client.connect(MQTT_BROKER, MQTT_PORT, 60)
client.loop_forever()