from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import paho.mqtt.publish as publish
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
import os

# --- CẤU HÌNH MQTT ---
MQTT_BROKER = os.getenv("MQTT_BROKER", "broker.hivemq.com")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
TOPIC_CMD = "greenframbku/cmd"

# --- CẤU HÌNH POSTGRESQL ---
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = os.getenv("DB_NAME", "farm_database")
DB_USER = os.getenv("DB_USER", "farm_admin")
DB_PASS = os.getenv("DB_PASS", "supersecret_pass")
DB_PORT = os.getenv("DB_PORT", "5432")

app = FastAPI(title="Smart Green House API - Unified")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db_connection():
    return psycopg2.connect(
        host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS, port=DB_PORT
    )

# --- MODELS ---
class CommandRequest(BaseModel):
    cmd_string: str = None
    command: str = None  # Alias hỗ trợ cho frontend cũ

class ThresholdUpdate(BaseModel):
    section_id: int
    temp_max: float
    soil_min: int
    light_min: int
    water_min: float
    username: str = "admin"

# =====================================================================
# 1. API ĐIỀU KHIỂN THIẾT BỊ (Giữ nguyên logic của bạn)
# =====================================================================
@app.post("/api/control")
@app.post("/api/command") # Giữ alias phòng khi frontend gọi /command
async def send_hardware_command(req: CommandRequest):
    try:
        # Nhận lệnh từ Frontend (cả 2 định dạng json)
        cmd = req.cmd_string if req.cmd_string else req.command
        if not cmd:
            raise HTTPException(status_code=400, detail="Missing command")

        parts = cmd.split("_")
        if len(parts) < 3:
            raise HTTPException(status_code=400, detail="Invalid command format")
        
        device_type = parts[0] 
        section_id = parts[1]  
        action = parts[2]
        
        valid_actions = {
            "PUMP": ["ON", "OFF", "AUTO"],
            "FAN":  ["ON", "OFF", "AUTO"],
            "LED":  ["ON", "OFF", "SET", "AUTO"]
        }
        if device_type not in valid_actions or action not in valid_actions[device_type]:
            raise HTTPException(status_code=400, detail="Invalid action")
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Cập nhật chế độ Auto xuống Database
        column_map = {"PUMP": "is_auto_pump", "LED": "is_auto_led", "FAN": "is_auto_fan"}
        if device_type in column_map:
            col = column_map[device_type]
            if action == "AUTO":
                cursor.execute(f"UPDATE thresholds SET {col} = true WHERE section_id = %s", (section_id,))
            else:
                cursor.execute(f"UPDATE thresholds SET {col} = false WHERE section_id = %s", (section_id,))
        
        conn.commit()
        
        # Publish MQTT cho ESP32
        publish.single(TOPIC_CMD, payload=cmd, hostname=MQTT_BROKER, port=MQTT_PORT)
        print(f"📡 [MQTT SEND] {cmd}")
        
        # Lưu vào control_logs
        cursor.execute("""
            INSERT INTO control_logs (username, device, action, source)
            VALUES ('admin', %s, %s, 'WEB')
        """, (f"{device_type}_{section_id}", action))
        
        conn.commit()
        cursor.close()
        conn.close()

        return {"status": "SUCCESS", "command_send": cmd, "device": f"{device_type}_{section_id}", "action": action}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# =====================================================================
# 2. API LẤY TRẠNG THÁI MỚI NHẤT (Giữ nguyên cấu trúc trả về của bạn)
# =====================================================================
@app.get("/api/status/latest")
@app.get("/api/latest") # Giữ alias
async def get_latest_status():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute("SELECT * FROM telemetry_packets ORDER BY created_at DESC LIMIT 1")
        latest_packet = cursor.fetchone()
        
        if not latest_packet:
            cursor.close()
            conn.close()
            return {"status": "EMPTY", "message": "Chưa có dữ liệu cảm biến nào trong DB"}

        cursor.execute(
            "SELECT * FROM telemetry_sections WHERE packet_id = %s ORDER BY section_id ASC", 
            (latest_packet['id'],)
        )
        sections_data = cursor.fetchall()
        
        cursor.close()
        conn.close()

        formatted_sections = []
        for sec in sections_data:
            formatted_sections.append({
                "section_id": sec['section_id'],
                "soil_percent": sec['soil_percent'],
                "light_percent": sec['light_percent'],
                "pump_status": bool(sec['pump_status']),
                "led_pwm": sec['led_pwm'],
                "fan_status": bool(sec.get('fan_status'))
            })

        return {
            "status": "SUCCESS",
            "data": {
                "air": {
                    "t": latest_packet['air_temp'], 
                    "h": latest_packet['air_humid']
                },
                "water_lvl": latest_packet['water_level'],
                "sections": formatted_sections
            },
            # Flat attributes được ném thêm vào để tương thích tuyệt đối với Biểu đồ bên Javascript
            "air_temp": latest_packet['air_temp'],
            "air_humid": latest_packet['air_humid'],
            "water_level": latest_packet['water_level'],
            "created_at": latest_packet['created_at'].isoformat(),
            "sections": formatted_sections
        }

    except Exception as e:
        print(f"❌ Lỗi Database: {e}")
        raise HTTPException(status_code=500, detail=f"Lỗi truy xuất Database: {str(e)}")

# =====================================================================
# 3. API ĐẶT NGƯỠNG VÀ BẮN XUỐNG ESP32 (Giữ nguyên logic cực chuẩn của bạn)
# =====================================================================
@app.post("/api/thresholds")
async def update_thresholds(req: ThresholdUpdate):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        sql = """
            UPDATE thresholds 
            SET temp_max = %s, soil_min = %s, light_min = %s, water_min = %s, updated_by = %s, updated_at = NOW()
            WHERE section_id = %s
        """
        cursor.execute(sql, (
            req.temp_max, req.soil_min, req.light_min, req.water_min, 
            req.username, req.section_id
        ))
        conn.commit()
        
        # --- BẮN LỆNH XUỐNG ESP32 ĐỂ ĐỒNG BỘ ---
        # Tự động tính ngưỡng WET (Ướt) = DRY (Khô) + 20%
        wet_calc = req.soil_min + 20 if (req.soil_min + 20) <= 100 else 100

        publish.single(TOPIC_CMD, payload=f"DRY_{req.section_id}_SET_{req.soil_min}", hostname=MQTT_BROKER, port=MQTT_PORT)
        publish.single(TOPIC_CMD, payload=f"WET_{req.section_id}_SET_{wet_calc}", hostname=MQTT_BROKER, port=MQTT_PORT)
        publish.single(TOPIC_CMD, payload=f"LIGHT_{req.section_id}_SET_{req.light_min}", hostname=MQTT_BROKER, port=MQTT_PORT)
        publish.single(TOPIC_CMD, payload=f"TEMP_{req.section_id}_SET_{req.temp_max}", hostname=MQTT_BROKER, port=MQTT_PORT)
        
        cursor.close()
        conn.close()
        return {"status": "SUCCESS"}
        
    except Exception as e:
        print(f"❌ Lỗi cập nhật Threshold: {e}")
        raise HTTPException(status_code=500, detail=f"Không thể lưu ngưỡng: {str(e)}")

# =====================================================================
# 4. TÍCH HỢP BIỂU ĐỒ & LOGS TỪ FILE (1)
# =====================================================================
@app.get("/api/history")
def api_history(limit: int = 50):
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT created_at, air_temp, air_humid, water_level 
            FROM telemetry_packets ORDER BY created_at DESC LIMIT %s
        """, (limit,))
        rows = cur.fetchall()
        conn.close()
        return rows[::-1] # Đảo ngược để vẽ biểu đồ
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/api/alerts")
def api_alerts(limit: int = 10):
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT created_at, alert_type, message FROM alerts ORDER BY created_at DESC LIMIT %s", (limit,))
        rows = cur.fetchall()
        conn.close()

        action_map = {"MOISTURE_LOW": "Start Irrigation", "TEMP_HIGH": "Activate Cooling", "WATER_LOW": None}
        field_map = {"MOISTURE_LOW": "Field 2", "TEMP_HIGH": "All Fields", "WATER_LOW": "Main System"}

        results = []
        for r in rows:
            r['field'] = field_map.get(r['alert_type'], "System")
            r['action'] = action_map.get(r['alert_type'])
            results.append(r)
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/logs")
def api_logs(limit: int = 20):
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT created_at, username, device, action, pwm, source FROM control_logs ORDER BY created_at DESC LIMIT %s", (limit,))
        rows = cur.fetchall()
        conn.close()
        return rows
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))