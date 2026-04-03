🌱 Smart Green House - Backend & Web Dashboard
📌 Project Overview
This repository contains the Backend and Web Dashboard for the Smart Green House IoT project. It is designed to communicate with ESP32 hardware via the MQTT (HiveMQ) protocol, store real-time environmental data in PostgreSQL, handle automated threshold logic, and provide a user-friendly interface via Streamlit.

⚙️ Prerequisites
Before running the system, ensure you have the following installed:
- Python 3.9+
- Docker & Docker Compose (Required for automated Database & MQTT Broker setup).

📁 Project Structure:
- docker-compose.yml: Orchestrates PostgreSQL, pgAdmin, and the Mosquitto Broker.
- init.sql: Automatically creates the 6 database tables and injects default threshold settings upon first launch.
- mqtt_subscriber.py: The "Brain" of the backend. It listens for MQTT data, saves it to the DB, and processes Auto-Threshold logic.
- dashboard.py: A Streamlit-based Web interface for real-time monitoring and manual hardware control.
- virtual_esp32.py: A simulation script to test the system without physical hardware.

🚀 Setup & Installation
Step 1: Spin up Database & MQTT Broker

Open your terminal in the project folder and run: pip install -r requirements.txt
Compose docker: docker-compose up -d

Step 2: Access Database Management (pgAdmin)
To view raw data and logs, open your browser and go to:
- URL: http://localhost:5050
- Login Email: admin@farm.com
- pgAdmin Password: adminpass

How to connect to the Database inside pgAdmin:
1. Right-click Servers -> Register -> Server...
2. General Tab: Name it anything (e.g., SmartFarm).
3. Connection Tab:
- Host name: db
- Port: 5432
- Username: farm_admin
- Password: supersecret_pass
4. Click Save. You can find your tables under: Databases -> farm_database -> Schemas -> public -> Tables.

Step 3: Install Python Dependencies & Launch
1. Install required libraries: pip install streamlit pandas psycopg2-binary paho-mqtt
2. Start the Backend (Terminal 1): python mqtt_subscriber.py
3. Start the Web Dashboard (Terminal 2): streamlit run dashboard.py
