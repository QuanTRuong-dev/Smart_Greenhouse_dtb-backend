import streamlit as st
import pandas as pd
import psycopg2
import paho.mqtt.client as mqtt
import time

# ==========================================
# CẤU HÌNH HỆ THỐNG
# ==========================================
st.set_page_config(page_title="Smart Green House", layout="wide")
st.title("🌱 Bảng Điều Khiển Smart Green House")

DB_CONFIG = {
    "host": "localhost",
    "port": "5432",
    "dbname": "farm_database",
    "user": "farm_admin",
    "password": "supersecret_pass"
}

MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
MQTT_TOPIC_CMD = "greenframbku/cmd"

# ==========================================
# HÀM XỬ LÝ DỮ LIỆU & MQTT
# ==========================================
def send_mqtt_command(command):
    try:
        parts = command.split('_')
        pwm_val = None
        
        if parts[0] == "PUMP":
            device_name = f"Máy bơm {parts[1]}"
            action_name = "BẬT" if parts[2] == "ON" else "TẮT"
        elif parts[0] == "LIGHT":
            device_name = f"Đèn LED {parts[1]}"
            action_name = "CẬP NHẬT"
            pwm_val = int(parts[3])
        else:
            device_name = "Unknown"
            action_name = command

        # Lưu lịch sử điều khiển
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO control_logs (username, device, action, pwm, source) VALUES (%s, %s, %s, %s, %s)",
                       ('admin', device_name, action_name, pwm_val, 'Web Dashboard'))
        conn.commit()
        cursor.close()
        conn.close()

        # Gửi MQTT
        client = mqtt.Client()
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.publish(MQTT_TOPIC_CMD, command)
        client.disconnect()
        st.toast(f"Đã gửi lệnh: {command} & Lưu log thành công!", icon="✅")
    except Exception as e:
        st.error(f"Lỗi hệ thống: {e}")

def get_latest_data():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        
        # 1. Gói tin chung
        query_packet = "SELECT id, air_temp, air_humid, water_level, created_at FROM telemetry_packets ORDER BY created_at DESC LIMIT 1;"
        df_packet = pd.read_sql_query(query_packet, conn)
        
        if df_packet.empty:
            conn.close()
            return None, None, None, None
            
        packet_id = df_packet.iloc[0]['id']
        
        # 2. Chi tiết vùng
        query_sections = f"SELECT section_id, soil_percent, light_percent, pump_status, led_pwm FROM telemetry_sections WHERE packet_id = {packet_id} ORDER BY section_id;"
        df_sections = pd.read_sql_query(query_sections, conn)
        
        # 3. Lịch sử biểu đồ
        query_hist = "SELECT created_at, air_temp, air_humid, water_level FROM telemetry_packets ORDER BY created_at DESC LIMIT 50;"
        df_hist = pd.read_sql_query(query_hist, conn)

        # 4. LẤY 5 CẢNH BÁO MỚI NHẤT (Thêm phần này)
        query_alerts = "SELECT created_at, alert_type, message FROM alerts ORDER BY created_at DESC LIMIT 5;"
        df_alerts = pd.read_sql_query(query_alerts, conn)
        
        conn.close()
        return df_packet.iloc[0], df_sections, df_hist, df_alerts
    except Exception as e:
        st.error(f"Lỗi Database: {e}")
        return None, None, None, None

# ==========================================
# GIAO DIỆN CHÍNH
# ==========================================
with st.sidebar:
    st.header("⚙️ Cài đặt")
    auto_refresh = st.checkbox("Tự động làm mới (10s/lần)", value=True)
    if st.button("🔄 Làm mới ngay"):
        st.rerun()

tab_monitor, tab_control = st.tabs(["📊 Giám sát & Lịch sử", "🎛️ Bảng Điều Khiển"])

# ------------------------------------------
# TAB ĐIỀU KHIỂN
# ------------------------------------------
with tab_control:
    st.info("Bảng điều khiển hoạt động độc lập. Lệnh sẽ được gửi trực tiếp qua HiveMQ đến ESP32.")
    ctrl_cols = st.columns(3)
    
    for i in range(1, 4):
        with ctrl_cols[i-1]:
            with st.container(border=True):
                st.markdown(f"<h3 style='text-align: center; color: #FF9800;'>Khu vực {i}</h3>", unsafe_allow_html=True)
                
                p_col1, p_col2 = st.columns(2)
                if p_col1.button(f"BẬT Bơm {i}", key=f"btn_pon_{i}", use_container_width=True):
                    send_mqtt_command(f"PUMP_{i}_ON")
                if p_col2.button(f"TẮT Bơm {i}", key=f"btn_poff_{i}", use_container_width=True):
                    send_mqtt_command(f"PUMP_{i}_OFF")
                
                st.markdown("---")
                pwm_val = st.slider(f"Độ sáng Đèn {i} (0-255)", 0, 255, 0, key=f"slider_led_{i}")
                if st.button(f"Cập nhật Đèn {i}", key=f"btn_lset_{i}", use_container_width=True):
                    send_mqtt_command(f"LIGHT_{i}_SET_{pwm_val}")

# ------------------------------------------
# TAB GIÁM SÁT DỮ LIỆU
# ------------------------------------------
with tab_monitor:
    latest_packet, latest_sections, history_df, df_alerts = get_latest_data()

    if latest_packet is None:
        st.warning("Đang chờ dữ liệu cảm biến từ ESP32...")
    else:
        # --- KHUNG HIỂN THỊ CẢNH BÁO (ALERTS) ---
        if not df_alerts.empty:
            with st.expander("🚨 CẢNH BÁO HỆ THỐNG (Mới nhất)", expanded=True):
                for index, row in df_alerts.iterrows():
                    st.error(f"[{row['created_at'].strftime('%H:%M:%S')}] {row['alert_type']}: {row['message']}")

        # --- THÔNG SỐ CHUNG ---
        st.subheader(f"☁️ Môi trường chung (Cập nhật: {latest_packet['created_at'].strftime('%H:%M:%S')})")
        col1, col2, col3 = st.columns(3)
        col1.metric("Nhiệt độ KQ", f"{latest_packet['air_temp']} °C")
        col2.metric("Độ ẩm KQ", f"{latest_packet['air_humid']} %")
        col3.metric("Mực nước Bồn", f"{latest_packet['water_level']} cm")
        
        st.divider()

        # --- TRẠNG THÁI KHU VỰC ---
        st.subheader("🪴 Trạng thái Khu vực (Sections)")
        sec_cols = st.columns(3)
        
        for index, row in latest_sections.iterrows():
            sec_id = int(row['section_id'])
            with sec_cols[index]:
                with st.container(border=True):
                    st.markdown(f"<h3 style='text-align: center; color: #4CAF50;'>Khu vực {sec_id}</h3>", unsafe_allow_html=True)
                    st.metric("💧 Độ ẩm đất", f"{int(row['soil_percent'])} %")
                    st.metric("☀️ Ánh sáng", f"{int(row['light_percent'])} %")
                    
                    pump_text = "ĐANG BẬT 🟢" if row['pump_status'] else "ĐANG TẮT 🔴"
                    st.write(f"**Máy bơm:** {pump_text}")
                    st.write(f"**Đèn LED (PWM):** {int(row['led_pwm'])}")

        st.divider()

        # --- BIỂU ĐỒ LỊCH SỬ ---
        st.subheader("📈 Lịch sử biến thiên (50 lần đo gần nhất)")
        history_df = history_df.set_index('created_at')
        history_df = history_df.sort_index(ascending=True)

        chart_col1, chart_col2 = st.columns(2)
        with chart_col1:
            st.write("**Nhiệt độ & Độ ẩm không khí**")
            st.line_chart(history_df[['air_temp', 'air_humid']])
        with chart_col2:
            st.write("**Mực nước bồn (cm)**")
            st.line_chart(history_df[['water_level']])

# --- TỰ LÀM MỚI ---
if auto_refresh:
    time.sleep(10)
    st.rerun()
