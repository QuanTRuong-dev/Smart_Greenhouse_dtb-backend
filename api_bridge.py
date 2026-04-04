"""
api_bridge.py - REST API Bridge cho Smart Green House
======================================================
Chạy: python api_bridge.py
Phục vụ tại: http://localhost:5000/api/...

Yêu cầu: pip install flask flask-cors psycopg2-binary paho-mqtt
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import psycopg2
import psycopg2.extras
import paho.mqtt.client as mqtt
import json
import logging
from datetime import datetime

# ==========================================
# CẤU HÌNH
# ==========================================
import os

DB_CONFIG = {
    "host":     os.getenv("DB_HOST",   "localhost"),
    "port":     os.getenv("DB_PORT",   "5432"),
    "dbname":   os.getenv("DB_NAME",   "farm_database"),
    "user":     os.getenv("DB_USER",   "farm_admin"),
    "password": os.getenv("DB_PASS",   "supersecret_pass")
}

MQTT_BROKER    = os.getenv("MQTT_BROKER", "broker.hivemq.com")
MQTT_PORT      = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC_CMD = "greenframbku/cmd"

# ==========================================
# FLASK APP
# ==========================================
app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


# ==========================================
# HELPER: KẾT NỐI DATABASE
# ==========================================
def get_db():
    """Tạo kết nối PostgreSQL mới."""
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = False
    return conn


def rows_to_dict(cursor):
    """Chuyển kết quả cursor thành list dict."""
    cols = [desc[0] for desc in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def serialize(obj):
    """Serialize datetime → ISO string cho JSON."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


# ==========================================
# HELPER: GỬI MQTT
# ==========================================
def publish_mqtt(command: str):
    """Kết nối HiveMQ và publish 1 lệnh, sau đó disconnect."""
    client = mqtt.Client(client_id=f"api_bridge_{datetime.now().timestamp()}")
    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=10)
    result = client.publish(MQTT_TOPIC_CMD, command, qos=1)
    result.wait_for_publish(timeout=5)
    client.disconnect()
    log.info(f"MQTT published: {command}")


# ==========================================
# HELPER: GHI CONTROL LOG
# ==========================================
def log_control(cursor, device: str, action: str, pwm=None, source="Web Dashboard", username="admin"):
    cursor.execute(
        "INSERT INTO control_logs (username, device, action, pwm, source) VALUES (%s, %s, %s, %s, %s)",
        (username, device, action, pwm, source)
    )


# ==========================================
# PARSE COMMAND → device / action / pwm
# ==========================================
def parse_command(command: str):
    parts = command.strip().split("_")
    device_name = "Unknown"
    action_name = command
    pwm_val = None

    if parts[0] == "PUMP" and len(parts) >= 3:
        device_name = f"Máy bơm {parts[1]}"
        action_name = "BẬT" if parts[2] == "ON" else "TẮT"

    elif parts[0] == "LIGHT" and len(parts) >= 4:
        device_name = f"Đèn LED {parts[1]}"
        action_name = "CẬP NHẬT"
        try:
            pwm_val = int(parts[3])
        except ValueError:
            pass

    return device_name, action_name, pwm_val


# ==========================================
# API: DỮ LIỆU MỚI NHẤT
# ==========================================
@app.route("/api/latest", methods=["GET"])
def api_latest():
    try:
        conn = get_db()
        cur  = conn.cursor()

        cur.execute("""
            SELECT id, air_temp, air_humid, water_level, created_at
            FROM telemetry_packets
            ORDER BY created_at DESC LIMIT 1
        """)
        row = cur.fetchone()
        if not row:
            conn.close()
            return jsonify({"error": "Chưa có dữ liệu nào trong database"}), 404

        packet_id, air_temp, air_humid, water_level, created_at = row

        cur.execute("""
            SELECT section_id, soil_percent, light_percent, pump_status, led_pwm
            FROM telemetry_sections
            WHERE packet_id = %s
            ORDER BY section_id
        """, (packet_id,))

        sections = [
            {
                "section_id":    r[0],
                "soil_percent":  r[1],
                "light_percent": r[2],
                "pump_status":   bool(r[3]),
                "led_pwm":       r[4]
            }
            for r in cur.fetchall()
        ]
        conn.close()

        return jsonify({
            "id":          packet_id,
            "air_temp":    air_temp,
            "air_humid":   air_humid,
            "water_level": water_level,
            "created_at":  created_at.isoformat(),
            "sections":    sections
        })

    except Exception as e:
        log.error(f"api_latest error: {e}")
        return jsonify({"error": str(e)}), 500


# ==========================================
# API: LỊCH SỬ
# ==========================================
@app.route("/api/history", methods=["GET"])
def api_history():
    limit = request.args.get("limit", 50, type=int)
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("""
            SELECT created_at, air_temp, air_humid, water_level
            FROM telemetry_packets
            ORDER BY created_at DESC LIMIT %s
        """, (limit,))
        rows = cur.fetchall()
        conn.close()

        return jsonify([
            {
                "created_at":  r[0].isoformat(),
                "air_temp":    r[1],
                "air_humid":   r[2],
                "water_level": r[3]
            }
            for r in reversed(rows)   # cũ → mới cho biểu đồ
        ])

    except Exception as e:
        log.error(f"api_history error: {e}")
        return jsonify({"error": str(e)}), 500


# ==========================================
# API: CẢNH BÁO
# ==========================================
@app.route("/api/alerts", methods=["GET"])
def api_alerts():
    limit = request.args.get("limit", 10, type=int)
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("""
            SELECT created_at, alert_type, message
            FROM alerts
            ORDER BY created_at DESC LIMIT %s
        """, (limit,))
        rows = cur.fetchall()
        conn.close()

        # Gợi ý hành động và gán field theo loại cảnh báo
        action_map = {
            "MOISTURE_LOW": "Start Irrigation",
            "TEMP_HIGH":    "Activate Cooling",
            "WATER_LOW":    None,
        }
        field_map = {
            "MOISTURE_LOW": "Field 2",
            "TEMP_HIGH":    "All Fields",
            "WATER_LOW":    "Main System",
        }

        return jsonify([
            {
                "created_at": r[0].isoformat(),
                "alert_type": r[1],
                "message":    r[2],
                "field":      field_map.get(r[1], "System"),
                "action":     action_map.get(r[1])
            }
            for r in rows
        ])

    except Exception as e:
        log.error(f"api_alerts error: {e}")
        return jsonify({"error": str(e)}), 500


# ==========================================
# API: LỊCH SỬ ĐIỀU KHIỂN
# ==========================================
@app.route("/api/logs", methods=["GET"])
def api_logs():
    limit = request.args.get("limit", 20, type=int)
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("""
            SELECT created_at, username, device, action, pwm, source
            FROM control_logs
            ORDER BY created_at DESC LIMIT %s
        """, (limit,))
        rows = cur.fetchall()
        conn.close()

        return jsonify([
            {
                "created_at": r[0].isoformat(),
                "username":   r[1],
                "device":     r[2],
                "action":     r[3],
                "pwm":        r[4],
                "source":     r[5]
            }
            for r in rows
        ])

    except Exception as e:
        log.error(f"api_logs error: {e}")
        return jsonify({"error": str(e)}), 500


# ==========================================
# API: GỬI LỆNH MQTT + LƯU LOG
# ==========================================
@app.route("/api/command", methods=["POST"])
def api_command():
    body    = request.get_json(force=True, silent=True) or {}
    command = body.get("command", "").strip()

    if not command:
        return jsonify({"error": "Thiếu trường 'command'"}), 400

    device_name, action_name, pwm_val = parse_command(command)

    try:
        # 1. Ghi log vào database
        conn = get_db()
        cur  = conn.cursor()
        log_control(cur, device_name, action_name, pwm_val)
        conn.commit()
        conn.close()

        # 2. Publish MQTT
        publish_mqtt(command)

        return jsonify({
            "status":  "ok",
            "command": command,
            "device":  device_name,
            "action":  action_name,
            "pwm":     pwm_val
        })

    except Exception as e:
        log.error(f"api_command error: {e}")
        return jsonify({"error": str(e)}), 500


# ==========================================
# API: XEM & CẬP NHẬT NGƯỠNG (THRESHOLDS)
# ==========================================
@app.route("/api/thresholds", methods=["GET"])
def api_thresholds_get():
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("""
            SELECT section_id, temp_max, soil_min, light_min, water_min, updated_by, updated_at
            FROM thresholds
            ORDER BY section_id
        """)
        rows = cur.fetchall()
        conn.close()

        return jsonify([
            {
                "section_id": r[0],
                "temp_max":   r[1],
                "soil_min":   r[2],
                "light_min":  r[3],
                "water_min":  r[4],
                "updated_by": r[5],
                "updated_at": r[6].isoformat() if r[6] else None
            }
            for r in rows
        ])

    except Exception as e:
        log.error(f"api_thresholds_get error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/thresholds/<int:section_id>", methods=["PUT"])
def api_thresholds_put(section_id):
    body = request.get_json(force=True, silent=True) or {}
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("""
            UPDATE thresholds
            SET temp_max   = COALESCE(%s, temp_max),
                soil_min   = COALESCE(%s, soil_min),
                light_min  = COALESCE(%s, light_min),
                water_min  = COALESCE(%s, water_min),
                updated_by = 'admin',
                updated_at = NOW()
            WHERE section_id = %s
        """, (
            body.get("temp_max"),
            body.get("soil_min"),
            body.get("light_min"),
            body.get("water_min"),
            section_id
        ))
        affected = cur.rowcount
        conn.commit()
        conn.close()

        if affected == 0:
            return jsonify({"error": f"Không tìm thấy section_id={section_id}"}), 404

        return jsonify({"status": "updated", "section_id": section_id})

    except Exception as e:
        log.error(f"api_thresholds_put error: {e}")
        return jsonify({"error": str(e)}), 500


# ==========================================
# API: THỐNG KÊ TỔNG QUAN (cho dashboard)
# ==========================================
@app.route("/api/stats", methods=["GET"])
def api_stats():
    """Trả về thống kê nhanh: tổng bản ghi, alert chưa xử lý, v.v."""
    try:
        conn = get_db()
        cur  = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM telemetry_packets")
        total_packets = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM alerts WHERE created_at >= NOW() - INTERVAL '24 hours'")
        alerts_24h = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM control_logs WHERE created_at >= NOW() - INTERVAL '24 hours'")
        commands_24h = cur.fetchone()[0]

        cur.execute("""
            SELECT AVG(air_temp), AVG(air_humid), AVG(water_level)
            FROM telemetry_packets
            WHERE created_at >= NOW() - INTERVAL '1 hour'
        """)
        row = cur.fetchone()
        conn.close()

        return jsonify({
            "total_packets":  total_packets,
            "alerts_24h":     alerts_24h,
            "commands_24h":   commands_24h,
            "avg_1h": {
                "air_temp":    round(row[0], 1) if row[0] else None,
                "air_humid":   round(row[1], 1) if row[1] else None,
                "water_level": round(row[2], 1) if row[2] else None
            }
        })

    except Exception as e:
        log.error(f"api_stats error: {e}")
        return jsonify({"error": str(e)}), 500


# ==========================================
# API: HEALTH CHECK
# ==========================================
@app.route("/api/health", methods=["GET"])
def api_health():
    db_ok   = False
    mqtt_ok = False

    try:
        conn  = get_db()
        conn.close()
        db_ok = True
    except Exception:
        pass

    try:
        client = mqtt.Client(client_id="health_check")
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=5)
        client.disconnect()
        mqtt_ok = True
    except Exception:
        pass

    status = "ok" if (db_ok and mqtt_ok) else "degraded"
    return jsonify({
        "status":    status,
        "database":  "connected" if db_ok   else "error",
        "mqtt":      "connected" if mqtt_ok else "error",
        "timestamp": datetime.now().isoformat()
    }), 200 if status == "ok" else 207


# ==========================================
# KHỞI ĐỘNG
# ==========================================
if __name__ == "__main__":
    print("=" * 55)
    print("  🌱 Smart Green House - API Bridge v2.0")
    print("=" * 55)
    print(f"  📡 URL:      http://localhost:5000")
    print(f"  🗄️  Database: {DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['dbname']}")
    print(f"  📶 MQTT:     {MQTT_BROKER}:{MQTT_PORT}")
    print("=" * 55)
    print("  Endpoints:")
    print("    GET  /api/health")
    print("    GET  /api/latest")
    print("    GET  /api/history?limit=50")
    print("    GET  /api/alerts?limit=10")
    print("    GET  /api/logs?limit=20")
    print("    GET  /api/stats")
    print("    GET  /api/thresholds")
    print("    PUT  /api/thresholds/<section_id>")
    print("    POST /api/command  { command: 'PUMP_1_ON' }")
    print("=" * 55)
    app.run(host="0.0.0.0", port=5000, debug=False)
