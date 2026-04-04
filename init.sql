CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    password VARCHAR(100) NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'admin',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE telemetry_packets (
    id BIGSERIAL PRIMARY KEY,
    air_temp DOUBLE PRECISION,
    air_humid DOUBLE PRECISION,
    water_level DOUBLE PRECISION,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE telemetry_sections (
    id BIGSERIAL PRIMARY KEY,
    packet_id BIGINT NOT NULL REFERENCES telemetry_packets(id) ON DELETE CASCADE,
    section_id INT NOT NULL,
    soil_percent INT,
    light_percent INT,
    pump_status INT,
    led_pwm INT
);

CREATE INDEX idx_packets_time
ON telemetry_packets(created_at DESC);

CREATE INDEX idx_sections_packet
ON telemetry_sections(packet_id, section_id);

CREATE TABLE thresholds (
    section_id INT PRIMARY KEY,
    temp_max DOUBLE PRECISION,
    soil_min INT,
    light_min INT,
    water_min DOUBLE PRECISION,
    updated_by VARCHAR(50),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE control_logs (
    id BIGSERIAL PRIMARY KEY,
    username VARCHAR(50),
    device VARCHAR(20) NOT NULL,
    action VARCHAR(20) NOT NULL,
    pwm INT,
    source VARCHAR(20) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE alerts (
    id BIGSERIAL PRIMARY KEY,
    alert_type VARCHAR(50) NOT NULL,
    message TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

INSERT INTO users (username, password, role)
VALUES ('admin', 'admin123', 'admin');

INSERT INTO thresholds (section_id, temp_max, soil_min, light_min, water_min, updated_by)
VALUES
(1, 30.0, 40, 35, 2.0, 'admin'),
(2, 30.0, 40, 35, 2.0, 'admin'),
(3, 30.0, 40, 35, 2.0, 'admin');
