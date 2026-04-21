from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import paho.mqtt.publish as publish
import psycopg2
from psycopg2.extras import RealDictCursor
import asyncio

# --- CẤU HÌNH MQTT ---
MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
TOPIC_CMD = "greenframbku/cmd"

# --- CẤU HÌNH POSTGRESQL ---
DB_HOST = "localhost"
DB_NAME = "farm_database" 
DB_USER = "farm_admin"          
DB_PASS = "supersecret_pass"            
DB_PORT = "5432"

app = FastAPI(title="Smart Green House API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class CommandRequest(BaseModel):
    cmd_string: str

def get_db_connection():
    """Hàm tạo kết nối đến DB"""
    return psycopg2.connect(
        host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS, port=DB_PORT
    )

# --- 1. API ĐIỀU KHIỂN ---
@app.post("/api/control")
async def send_hardware_command(req: CommandRequest):
    try:
        parts = req.cmd_string.split("_")
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
        
        column_map = {"PUMP": "is_auto_pump", "LED": "is_auto_led", "FAN": "is_auto_fan"}
        
        if device_type in column_map:
            col = column_map[device_type]
            if action == "AUTO":
                cursor.execute(f"UPDATE thresholds SET {col} = true WHERE section_id = %s", (section_id,))
            else:
                cursor.execute(f"UPDATE thresholds SET {col} = false WHERE section_id = %s", (section_id,))
        
        conn.commit()
        
        full_cmd = req.cmd_string
        publish.single(TOPIC_CMD, payload=full_cmd, hostname=MQTT_BROKER, port=MQTT_PORT)
        print(f"📡 [MQTT SEND] {full_cmd}")
        
        cursor.execute("""
            INSERT INTO control_logs (username, device, action, source)
            VALUES ('admin', %s, %s, 'WEB')
        """, (f"{device_type}_{section_id}", action))
        
        conn.commit()
        cursor.close()
        conn.close()

        return {"status": "SUCCESS", "command_send": full_cmd}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- 2. API LẤY TRẠNG THÁI TỪ DATABASE ---
@app.get("/api/status/latest")
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
                "id": sec['section_id'],
                "soil": sec['soil_percent'],
                "light": sec['light_percent'],
                "pump": 1 if sec['pump_status'] else 0, 
                "led": sec['led_pwm'],
                "fan": 1 if sec.get('fan_status') else 0 
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
            }
        }

    except Exception as e:
        print(f"❌ Lỗi Database: {e}")
        raise HTTPException(status_code=500, detail=f"Lỗi truy xuất Database: {str(e)}")
    
# --- ĐỊNH NGHĨA DATA FRONTEND GỬI LÊN ĐỂ CÀI NGƯỠNG ---
class ThresholdUpdate(BaseModel):
    section_id: int
    temp_max: float
    soil_min: int
    light_min: int
    water_min: float
    username: str = "admin" 

# --- 3. API CẬP NHẬT NGƯỠNG TỪ NGƯỜI DÙNG ---
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