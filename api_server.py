from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import paho.mqtt.publish as publish
import psycopg2
from psycopg2.extras import RealDictCursor # Giúp lấy dữ liệu ra dưới dạng Dictionary
import asyncio

# --- CẤU HÌNH MQTT ---
MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
TOPIC_CMD = "greenframbku/cmd"

# --- CẤU HÌNH POSTGRESQL (SỬA LẠI CHO KHỚP MÁY BẠN) ---
DB_HOST = "localhost"
DB_NAME = "farm_database" # Thay tên DB của bạn
DB_USER = "farm_admin"          # Thay user của bạn
DB_PASS = "supersecret_pass"            # Thay pass của bạn
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
        # 1. Phân tích lệnh (Ví dụ: "PUMP_1_AUTO" hoặc "PUMP_1_ON")
        parts = req.cmd_string.split("_")
        device_type = parts[0] # PUMP, FAN, LIGHT
        section_id = parts[1]  # 1, 2, 3
        action = parts[2]      # ON, OFF, AUTO, SET

        # 2. Cập nhật "Trạng thái Auto" vào Database
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if action == "AUTO":
            # Bật chế độ tự động cho Backend
            cursor.execute("UPDATE thresholds SET is_auto = true WHERE section_id = %s", (section_id,))
        elif action in ["ON", "OFF", "SET"]:
            # Nếu user bấm nút điều khiển tay -> Tự động tắt chế độ Auto
            cursor.execute("UPDATE thresholds SET is_auto = false WHERE section_id = %s", (section_id,))
        
        conn.commit()

        # 3. Bắn lệnh MQTT xuống ESP32
        # Theo code C++ của bạn bạn: PUMP_1_AUTO sẽ kích hoạt mode auto dưới mạch
        publish.single(TOPIC_CMD, payload=req.cmd_string, hostname=MQTT_BROKER, port=MQTT_PORT)
        
        # 4. Ghi Log
        cursor.execute("""
            INSERT INTO control_logs (username, device, action, source)
            VALUES ('admin', %s, %s, 'WEB')
        """, (f"{device_type}_{section_id}", action))
        
        conn.commit()
        cursor.close()
        conn.close()

        return {"status": "SUCCESS", "mode_synced": action}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- 2. API LẤY TRẠNG THÁI TỪ DATABASE ---
@app.get("/api/status/latest")
async def get_latest_status():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Bước 1: Lấy gói thông tin môi trường chung MỚI NHẤT
        cursor.execute("SELECT * FROM telemetry_packets ORDER BY created_at DESC LIMIT 1")
        latest_packet = cursor.fetchone()
        
        # Nếu DB trống trơn chưa có gì
        if not latest_packet:
            cursor.close()
            conn.close()
            return {"status": "EMPTY", "message": "Chưa có dữ liệu cảm biến nào trong DB"}

        # Bước 2: Lấy thông số của 3 khu vực (sections) thuộc về gói thông tin vừa lấy
        cursor.execute(
            "SELECT * FROM telemetry_sections WHERE packet_id = %s ORDER BY section_id ASC", 
            (latest_packet['id'],)
        )
        sections_data = cursor.fetchall()
        
        cursor.close()
        conn.close()

        # Bước 3: Nhào nặn dữ liệu thành định dạng JSON chuẩn mà Web Frontend đang đợi
        formatted_sections = []
        for sec in sections_data:
            formatted_sections.append({
                "id": sec['section_id'],
                "soil": sec['soil_percent'],
                "light": sec['light_percent'],
                # Web cần số 1/0, nhưng DB bạn lưu BOOLEAN nên phải ép kiểu
                "pump": 1 if sec['pump_status'] else 0, 
                "led": sec['led_pwm'],
                # Dùng .get() để lỡ bạn chưa kịp thêm cột fan_status thì code không bị crash
                "fan": 1 if sec.get('fan_status') else 0 
            })

        # Đóng gói và trả về
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
    username: str = "admin" # Tạm thời fix cứng nếu web chưa làm chức năng Login

# --- 3. API CẬP NHẬT NGƯỠNG TỪ NGƯỜI DÙNG ---
@app.post("/api/thresholds")
async def update_thresholds(req: ThresholdUpdate):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Cập nhật các thông số ngưỡng vào Database
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
        
        # --- LƯU Ý KẾT NỐI VỚI MẠCH ESP32 ---
        # Vì đoạn code C++ của bạn bạn vẫn đang có các lệnh DRY_SET, WET_SET...
        # Nếu muốn mạch ở dưới cũng cập nhật số này ngay lập tức để đồng bộ hiển thị màn hình LCD (nếu có),
        # bạn có thể mở comment dòng dưới đây để bắn MQTT xuống mạch luôn:
        # publish.single(TOPIC_CMD, payload=f"DRY_{req.section_id}_SET_{req.soil_min}", hostname=MQTT_BROKER, port=MQTT_PORT)

        cursor.close()
        conn.close()
        
        return {"status": "SUCCESS", "message": f"Đã lưu ngưỡng cấu hình cho Khu vực {req.section_id}"}
        
    except Exception as e:
        print(f"❌ Lỗi cập nhật Threshold: {e}")
        raise HTTPException(status_code=500, detail=f"Không thể lưu ngưỡng: {str(e)}")
    
# --- HÀM TỰ ĐỘNG KIỂM TRA VÀ ĐIỀU KHIỂN ---
async def auto_control_brain():
    print("🧠 Bộ não tự động đã kích hoạt...")
    while True:
        try:
            conn = get_db_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            # 1. Lấy tất cả ngưỡng của 3 khu vực
            cursor.execute("SELECT * FROM thresholds")
            all_thresholds = cursor.fetchall()

            for ts in all_thresholds:
                sid = ts['section_id']
                
                if not ts['is_auto']:
                    continue
                
                # 2. Lấy dữ liệu cảm biến mới nhất của khu vực này
                cursor.execute("""
                    SELECT soil_percent, pump_status 
                    FROM telemetry_sections 
                    WHERE section_id = %s 
                    ORDER BY id DESC LIMIT 1
                """, (sid,))
                latest_data = cursor.fetchone()

                if latest_data:
                    current_soil = latest_data['soil_percent']
                    min_soil = ts['soil_min']
                    is_pump_on = latest_data['pump_status']

                    # 3. Logic: Nếu đất khô hơn ngưỡng và bơm đang tắt -> BẬT BƠM
                    if current_soil < min_soil and not is_pump_on:
                        cmd = f"PUMP_{sid}_ON"
                        publish.single(TOPIC_CMD, payload=cmd, hostname=MQTT_BROKER, port=MQTT_PORT)
                        
                        # Ghi log vào control_logs
                        cursor.execute("""
                            INSERT INTO control_logs (username, device, action, source)
                            VALUES ('system_auto', %s, 'ON', 'BACKEND')
                        """, (f"PUMP_{sid}",))
                        conn.commit()
                        print(f"🤖 [AUTO] Khu {sid} khô ({current_soil}% < {min_soil}%). Đã bật bơm!")

                    # 4. Logic: Nếu đất đã đủ ẩm (ví dụ +10% so với ngưỡng) -> TẮT BƠM
                    elif current_soil > (min_soil + 10) and is_pump_on:
                        cmd = f"PUMP_{sid}_OFF"
                        publish.single(TOPIC_CMD, payload=cmd, hostname=MQTT_BROKER, port=MQTT_PORT)
                        
                        cursor.execute("""
                            INSERT INTO control_logs (username, device, action, source)
                            VALUES ('system_auto', %s, 'OFF', 'BACKEND')
                        """, (f"PUMP_{sid}",))
                        conn.commit()
                        print(f"🤖 [AUTO] Khu {sid} đủ ẩm ({current_soil}%). Đã tắt bơm!")

            cursor.close()
            conn.close()

        except Exception as e:
            print(f"❌ Lỗi vòng lặp tự động: {e}")
        
        # Chờ 10 giây trước khi kiểm tra lại (để tránh spam Database)
        await asyncio.sleep(10)

# --- ĐĂNG KÝ VÒNG LẶP CHẠY KHI STARTUP ---
@app.on_event("startup")
async def startup_event():
    # Chạy vòng lặp tự động dưới dạng task ngầm
    asyncio.create_task(auto_control_brain())