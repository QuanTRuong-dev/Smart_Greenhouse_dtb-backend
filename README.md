🌱 Smart Green House - Backend & Web Dashboard
📌 Project Overview

This repository contains the Backend and Web Dashboard for the Smart Green House IoT project. It is designed to communicate with ESP32 hardware via the MQTT (HiveMQ) protocol, store real-time environmental data in PostgreSQL, handle automated threshold logic, and provide a user-friendly interface via Streamlit.

⚙️ Prerequisites

Before running the system, ensure you have the following installed:
- Python 3.9+
- Docker & Docker Compose (Required for automated Database & MQTT Broker setup).
- platformio extendtion (Required for IOT setup)

📁 Project Structure:

+ Smart_Greenhouse_dtb-backend: include all the file to run frontend, backend, database
  - docker-compose.yml: Orchestrates PostgreSQL, pgAdmin, and the Mosquitto Broker.
  - init.sql: Automatically creates the 6 database tables and injects default threshold settings upon first launch.
  - mqtt_subscriber.py: The "Brain" of the backend. It listens for MQTT data, saves it to the DB, and processes Auto-Threshold logic.
  - dashboard.py: A Streamlit-based Web interface for real-time monitoring and manual hardware control.
  - virtual_esp32.py: A simulation script to test the system without physical hardware.
  - index.html: The frontend of the website to view the information and control the IOT through API
  - api_server.py: The backend that have API to connect the frontend, database and IOT together
  - requirements.txt: all the requirements for python to be able to run

+ Smart_Green_House: include all the file to run the IOT
  - platformio.ini: A script to run the IOT

🚀 Setup & Installation

Step 1: Create and activate virtual env

- Open your terminal in the project folder and run: C:\Users\ADMIN\AppData\Local\Programs\Python\Python313\python.exe -m venv venv
- Then activate venv: .\venv\Scripts\activate
- Install requirements: pip install -r requirements.txt

Step 2: Spin up Database & MQTT Broker

- Close all previous docker image: docker compose down -v
- Open your terminal in the project folder and run: docker compose up -d

Step 3: Access Database Management (pgAdmin)

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

Step 4: Install Python Dependencies & Launch

1. Start the Backend (Terminal 1): python mqtt_subscriber.py
2. Start the Web Dashboard (Terminal 2): streamlit run dashboard.py (Optional)
3.1. For a mock test (Terminal 3): python virtual_esp32.py (Simulate the data sent from the IOT)
3.2. To connect it to the IOT (Terminal 3), open the "Smart_Green_House" folder, click the "serial monitor" or press "Ctrl+Alt+S" to execute the platformio.ini

Step 5: Run web and API

1. Open a new terminal, run the website to port 7000: python -m http.server 7000
2. Open another terminal, run the api_server on port 8000: uvicorn api_server:app --reload --port 8000
3. Open: https://localhost:7000 to run the website
