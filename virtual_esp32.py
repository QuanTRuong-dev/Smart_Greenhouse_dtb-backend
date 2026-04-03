import paho.mqtt.client as mqtt
import time
import json
import random

# Cấu hình HiveMQ Public Broker
MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
MQTT_TOPIC_TELEMETRY = "greenframbku/sensors"

client = mqtt.Client()
client.connect(MQTT_BROKER, MQTT_PORT, 60)

print("🚀 Đã khởi động ESP32 Ảo (Đang kết nối qua HiveMQ)")

while True:
    # Cấu trúc JSON chuẩn theo spec của nhóm
    payload = {
        "air": {
            "t": round(random.uniform(28.0, 35.0), 1),
            "h": round(random.uniform(60.0, 80.0), 1)
        },
        "water_lvl": round(random.uniform(0, 3.0), 1),
        "s1": {
            "soil": random.randint(30, 70),
            "light": random.randint(40, 80),
            "pump": random.choice([0, 1]),
            "led": random.choice([0, 128, 255])
        },
        "s2": {
            "soil": random.randint(30, 70),
            "light": random.randint(40, 80),
            "pump": random.choice([0, 1]),
            "led": random.choice([0, 128, 255])
        },
        "s3": {
            "soil": random.randint(30, 70),
            "light": random.randint(40, 80),
            "pump": random.choice([0, 1]),
            "led": random.choice([0, 128, 255])
        }
    }
    
    # Bắn dữ liệu lên HiveMQ
    client.publish(MQTT_TOPIC_TELEMETRY, json.dumps(payload))
    print(f"📡 Đã gửi gói dữ liệu lên kênh {MQTT_TOPIC_TELEMETRY}")
    
    # Tần suất gửi 10 giây/lần
    time.sleep(10)