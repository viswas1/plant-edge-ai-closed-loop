# Plant Edge-AI Closed Loop

Code for the paper **"we implemented"**

The system runs one closed-loop cycle: **Sense → Perceive → Understand → Decide → Act → Sense again.**

| Component | Runs on | File |
|---|---|---|
| BME280 sensing firmware (T, RH, P every 5 s over MQTT) | ESP32 | `esp32/bme280_mqtt_sensor/bme280_mqtt_sensor.ino` |
| Standalone MQTT sensor receiver (link check) | Raspberry Pi 5 | `rpi5/mqtt_sensor_receiver.py` |
| Five-minute closed-loop pipeline (YOLO26n-cls → 5-min BME280 trend → Gemini report → agent → safe MQTT action) | Raspberry Pi 5 | `rpi5/plant_pipeline_5min.py` |

Flowcharts of all three programs are in `docs/flowcharts/` (Figs. 5–7 of the paper).

## Hardware

- Raspberry Pi 5 (8 GB), 64-bit OS, Python 3.13, USB webcam
- ESP32 development board + BME280 breakout on I²C (SDA = GPIO 21, SCL = GPIO 22, address 0x76 or 0x77)

## 1. Raspberry Pi 5 set-up

```bash
sudo apt install mosquitto mosquitto-clients
sudo systemctl enable --now mosquitto
pip install -r requirements.txt
export GEMINI_API_KEY="your-key"        # never put the key in the code
```

The broker must accept connections from the ESP32 on port 1883 (for a local test network, add `listener 1883` and `allow_anonymous true` to the Mosquitto configuration).

The pipeline expects these paths (edit the constants at the top of `plant_pipeline_5min.py` if yours differ):

- trained weights: `~/AI/yolo_runs/plant_yolo26n_full20/weights/best.pt`
- camera frame: `~/AI/camera_test/plant1.jpg`
- results are written to `~/AI/pipeline_5min_results/`

## 2. ESP32 set-up

1. Install the Arduino libraries **PubSubClient** and **Adafruit BME280**.
2. Copy `secrets_example.h` to `secrets.h` in the same folder and enter your Wi-Fi name, password and the Raspberry Pi's IP address. `secrets.h` is git-ignored.
3. Upload `bme280_mqtt_sensor.ino`. The serial monitor (115200 baud) shows each published reading.

## 3. Running

```bash
# check that sensor data arrive
python3 rpi5/mqtt_sensor_receiver.py

# run one five-minute closed-loop cycle
python3 rpi5/plant_pipeline_5min.py
```

Each run saves a time-stamped JSON and text record (YOLO result, raw sensor history, trend summary, Gemini report, agent decision, published action).

## Safety note

`ACTUATOR_MODE = "SAFE_DRY_RUN"`: actions are published on `plant/agent/action` with `physical_actuation = false`. The five-minute trend is a short-horizon risk indicator, **not** a validated biological disease forecast.

## Data

Images were taken from the PlantVillage dataset (Hughes & Salathé, 2015, arXiv:1511.08060), restricted to 10 crop–condition classes as described in Section 4 of the paper.

## Citation and licence

Please cite the paper (see `CITATION.cff`). Code released under the MIT License.
