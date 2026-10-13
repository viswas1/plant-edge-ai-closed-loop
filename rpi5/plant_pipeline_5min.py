#!/usr/bin/env python3
"""
plant_pipeline_5min.py

Research prototype:
USB Camera -> YOLO26n -> RPi5
ESP32+BME280 -> MQTT -> RPi5
YOLO + 5-minute BME280 trend -> Gemini GenAI report
GenAI report + evidence -> Agentic AI
Agent -> SAFE MQTT actuator command
-> ESP32 actuator -> Sense Again

This is a NEW file. Existing plant_pipeline.py is not modified.

Important:
- The 5-minute window is used to demonstrate environmental trend/progression.
- This is NOT a 48-hour biological forecast.
- "Progression" is a risk/trajectory estimate from the current image classification
  and short-term environmental trend.
- Physical actuation remains disabled unless ACTUATOR_MODE is changed deliberately.
"""

import os
import json
import time
import re
import statistics
from datetime import datetime, timedelta

import cv2
import paho.mqtt.client as mqtt
from ultralytics import YOLO
from google import genai


# ============================================================
# CONFIGURATION
# ============================================================

YOLO_MODEL = os.path.expanduser(
    "~/AI/yolo_runs/plant_yolo26n_full20/weights/best.pt"
)

IMAGE_PATH = os.path.expanduser(
    "~/AI/camera_test/plant1.jpg"
)

BASE_DIR = os.path.expanduser("~/AI")
RESULT_DIR = os.path.join(BASE_DIR, "pipeline_5min_results")
os.makedirs(RESULT_DIR, exist_ok=True)

MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_SENSOR_TOPIC = "plant/sensor"
MQTT_ACTION_TOPIC = "plant/agent/action"

# ESP32 publishes every 5 seconds in the current experiment.
# We collect for 5 minutes.
HISTORY_MINUTES = 5
SAMPLE_INTERVAL_SECONDS = 5
MIN_SAMPLES = 10

GEMINI_MODEL = "gemini-3.8-flash"

# IMPORTANT: keep this SAFE during research.
ACTUATOR_MODE = "SAFE_DRY_RUN"

ALLOWED_ACTIONS = {
    "MONITOR",
    "ALERT",
    "RECHECK",
    "HUMAN_REVIEW",
    "IRRIGATION_SIMULATION",
    "SPRAY_SIMULATION",
}


# ============================================================
# UTILITY
# ============================================================

def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def stamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def clean_json_text(text):
    if not text:
        return None

    text = text.strip()
    text = re.sub(r"^```json\s*", "", text, flags=re.I)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except Exception:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            return None

    return None


def gemini_call(client, prompt, attempts=3):
    """
    Uses Gemini Interactions API without response_mime_type.
    """
    for attempt in range(1, attempts + 1):
        print(f"\nGemini attempt {attempt}/{attempts}")

        try:
            interaction = client.interactions.create(
                model=GEMINI_MODEL,
                input=prompt,
            )

            text = interaction.output_text

            if text:
                print("Gemini response received successfully.")
                return text

            print("Gemini returned an empty response.")

        except Exception as e:
            print("Gemini error:")
            print(e)

            if attempt < attempts:
                wait = 2 ** attempt
                print(f"Retrying after {wait} seconds...")
                time.sleep(wait)

    return None


# ============================================================
# STEP 1 - YOLO
# ============================================================

def run_yolo():
    print("\n" + "=" * 60)
    print("STEP 1: EDGE AI - YOLO26n")
    print("=" * 60)

    print("Loading:", YOLO_MODEL)
    model = YOLO(YOLO_MODEL)

    if not os.path.exists(IMAGE_PATH):
        raise FileNotFoundError(f"Image not found: {IMAGE_PATH}")

    results = model.predict(
        source=IMAGE_PATH,
        verbose=False
    )

    result = results[0]
    probs = result.probs

    class_index = int(probs.top1)
    confidence = float(probs.top1conf)
    prediction = result.names[class_index]

    probabilities = {}
    for idx, name in result.names.items():
        probabilities[name] = float(probs.data[idx])

    crop = prediction.split("_")[0]

    edge = {
        "model": "YOLO26n-cls",
        "image": IMAGE_PATH,
        "crop": crop,
        "prediction": prediction,
        "confidence": confidence,
        "confidence_percent": confidence * 100,
        "class_index": class_index,
        "all_class_probabilities": probabilities,
    }

    print("\nYOLO RESULT")
    print("-" * 60)
    print("Crop       :", crop)
    print("Prediction :", prediction)
    print("Confidence :", f"{confidence * 100:.2f}%")

    return edge


# ============================================================
# STEP 2 - MQTT 5-MINUTE SENSOR HISTORY
# ============================================================

class SensorCollector:
    def __init__(self):
        self.samples = []
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"RPi5_5MIN_COLLECTOR_{int(time.time())}"
        )
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

    def on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            print("MQTT connected.")
            print("Subscribed to:", MQTT_SENSOR_TOPIC)
            client.subscribe(MQTT_SENSOR_TOPIC)
        else:
            print("MQTT connection failed:", reason_code)

    def on_message(self, client, userdata, msg):
        try:
            data = json.loads(msg.payload.decode())

            required = ["device", "temperature", "humidity", "pressure"]
            if not all(k in data for k in required):
                return

            sample = {
                "timestamp": now_iso(),
                "device": data["device"],
                "temperature": float(data["temperature"]),
                "humidity": float(data["humidity"]),
                "pressure": float(data["pressure"]),
            }

            self.samples.append(sample)

            print(
                f"[{len(self.samples):03d}] "
                f"T={sample['temperature']:.2f} °C | "
                f"RH={sample['humidity']:.2f} % | "
                f"P={sample['pressure']:.2f} hPa"
            )

        except Exception as e:
            print("Sensor message error:", e)

    def collect(self, minutes=5):
        print("\n" + "=" * 60)
        print(f"STEP 2: COLLECTING BME280 HISTORY - {minutes} MINUTES")
        print("=" * 60)

        self.client.connect(MQTT_BROKER, MQTT_PORT, 60)
        self.client.loop_start()

        start = time.time()
        end = start + minutes * 60

        try:
            while time.time() < end:
                time.sleep(0.5)
        finally:
            self.client.loop_stop()
            self.client.disconnect()

        return self.samples


def linear_slope(values, seconds_per_sample):
    if len(values) < 2:
        return 0.0

    n = len(values)
    x = list(range(n))
    x_mean = statistics.mean(x)
    y_mean = statistics.mean(values)

    numerator = sum(
        (xi - x_mean) * (yi - y_mean)
        for xi, yi in zip(x, values)
    )
    denominator = sum(
        (xi - x_mean) ** 2
        for xi in x
    )

    if denominator == 0:
        return 0.0

    # units per sample -> units per minute
    return (numerator / denominator) * (60 / (seconds_per_sample or 1))


def summarize_sensor_history(samples):
    if not samples:
        return {
            "sample_count": 0,
            "window_minutes": 0,
            "error": "No sensor samples received."
        }

    temps = [s["temperature"] for s in samples]
    hums = [s["humidity"] for s in samples]
    press = [s["pressure"] for s in samples]

    summary = {
        "sample_count": len(samples),
        "window_minutes": round(
            ((len(samples) - 1) * SAMPLE_INTERVAL_SECONDS) / 60,
            2
        ),
        "start": samples[0]["timestamp"],
        "end": samples[-1]["timestamp"],

        "temperature": {
            "min": round(min(temps), 2),
            "max": round(max(temps), 2),
            "mean": round(statistics.mean(temps), 2),
            "first": round(temps[0], 2),
            "last": round(temps[-1], 2),
            "trend_per_min": round(
                linear_slope(temps, SAMPLE_INTERVAL_SECONDS), 4
            ),
        },

        "humidity": {
            "min": round(min(hums), 2),
            "max": round(max(hums), 2),
            "mean": round(statistics.mean(hums), 2),
            "first": round(hums[0], 2),
            "last": round(hums[-1], 2),
            "trend_per_min": round(
                linear_slope(hums, SAMPLE_INTERVAL_SECONDS), 4
            ),
        },

        "pressure": {
            "min": round(min(press), 2),
            "max": round(max(press), 2),
            "mean": round(statistics.mean(press), 2),
            "first": round(press[0], 2),
            "last": round(press[-1], 2),
            "trend_per_min": round(
                linear_slope(press, SAMPLE_INTERVAL_SECONDS), 4
            ),
        },

        "latest": samples[-1],
    }

    return summary


# ============================================================
# STEP 3 - MULTIMODAL GENAI
# ============================================================

def create_genai_prompt(edge, sensor_summary):
    return f"""
You are the Generative AI reasoning layer of a research prototype for
plant disease monitoring.

The Edge AI model is already trained and has produced the visual result.
Do not replace the YOLO result.

You receive:
1. YOLO plant-disease classification.
2. Five minutes of ESP32+BME280 environmental observations.
3. Temperature, humidity and pressure trends calculated on the Raspberry Pi 5.

EDGE AI:
{json.dumps(edge, indent=2)}

BME280 FIVE-MINUTE SUMMARY:
{json.dumps(sensor_summary, indent=2)}

Create a structured report with these sections:

1. EDGE AI OBSERVATION
- State crop, predicted class and model confidence.
- Explicitly say model confidence is not biological certainty.

2. ENVIRONMENTAL CONDITION
- Interpret temperature.
- Interpret humidity.
- Interpret pressure.
- Explain what the short-term trend means.
- Do not claim pressure alone proves disease.

3. PLANT-ENVIRONMENT RELATIONSHIP
- Explain plausible relationships between the observed environment
  and disease development.
- Distinguish observation from hypothesis.

4. CURRENT RISK ASSESSMENT
- LOW / MODERATE / HIGH / UNKNOWN.
- Explain why.

5. FIVE-MINUTE PROGRESSION ASSESSMENT
This is NOT a 48-hour biological prediction.
Use the five-minute trend only to estimate whether the environmental
conditions are becoming more favorable, less favorable, or stable
for continued disease risk.
Describe:
- current state
- short-term trajectory
- likely monitoring priority over the next cycle

6. PREDICTIVE DISEASE-PROGRESSION MODEL
Provide a conceptual short-horizon trajectory such as:
Current -> If conditions persist -> If conditions worsen.
Do not invent a pathogen or claim a confirmed future disease state.

7. RECOMMENDED MONITORING
Specify what should be sensed again:
temperature, humidity, pressure and plant image.

8. MANAGEMENT CONSIDERATIONS
Give general non-prescriptive considerations only.
Do not prescribe pesticides, antibiotics or exact chemical doses.

9. SUMMARY_FOR_AGENT
Give a concise paragraph explaining what an Agentic AI should
consider when deciding MONITOR, ALERT, RECHECK or HUMAN_REVIEW.

IMPORTANT:
The five-minute data window demonstrates the feedback/progression
architecture. It does not establish agronomic causality.
"""

def run_genai(edge, sensor_summary):
    print("\n" + "=" * 60)
    print("STEP 3: MULTIMODAL GENERATIVE AI - GEMINI")
    print("=" * 60)

    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY is missing.")

    client = genai.Client(api_key=key)

    prompt = create_genai_prompt(edge, sensor_summary)
    report = gemini_call(client, prompt, attempts=3)

    if report is None:
        raise RuntimeError("Gemini unavailable after retries.")

    print("\nGENERATIVE AI REPORT")
    print("-" * 60)
    print(report)

    return report, client


# ============================================================
# STEP 4 - AGENTIC AI
# ============================================================

def create_agent_prompt(edge, sensor_summary, report):
    return f"""
You are the Agentic AI decision layer in a plant-health monitoring
system.

The Generative AI has already produced the agricultural report.
Your job is to reason over that report and decide the next safe action.

Do NOT independently invent a diagnosis.
Do NOT prescribe chemicals.

EDGE AI:
{json.dumps(edge, indent=2)}

BME280 FIVE-MINUTE SUMMARY:
{json.dumps(sensor_summary, indent=2)}

GENERATIVE AI REPORT:
{report}

Allowed decisions:
MONITOR
ALERT
RECHECK
HUMAN_REVIEW
IRRIGATION_SIMULATION
SPRAY_SIMULATION

Safety:
- Physical actuation is currently SAFE_DRY_RUN.
- Therefore any irrigation/spray action is simulation only.
- Use HUMAN_REVIEW if the evidence is uncertain or a chemical decision
  would be required.
- The decision must be traceable to the GenAI report and supplied data.
- The next sense cycle should include BME280 and plant image.

Return ONLY JSON:

{{
  "understand": {{
    "vision": "...",
    "environment": "...",
    "progression": "...",
    "overall_interpretation": "..."
  }},
  "decide": {{
    "decision": "MONITOR|ALERT|RECHECK|HUMAN_REVIEW|IRRIGATION_SIMULATION|SPRAY_SIMULATION",
    "risk_level": "LOW|MODERATE|HIGH|UNKNOWN",
    "reason": "..."
  }},
  "act": {{
    "action": "...",
    "target": "Researcher|ESP32_IRRIGATION|ESP32_SPRAY",
    "safe_action": true
  }},
  "sense_again": {{
    "required": true,
    "interval_minutes": 5,
    "parameters": [
      "temperature",
      "humidity",
      "pressure",
      "plant_image"
    ]
  }}
}}
"""

def run_agent(edge, sensor_summary, report, client):
    print("\n" + "=" * 60)
    print("STEP 4: AGENTIC AI - DECISION")
    print("=" * 60)

    prompt = create_agent_prompt(edge, sensor_summary, report)
    text = gemini_call(client, prompt, attempts=3)

    decision = clean_json_text(text)

    if decision is None:
        decision = {
            "understand": {
                "vision": edge.get("prediction"),
                "environment": "Unable to parse agent response.",
                "progression": "Unknown",
                "overall_interpretation": "Human review required."
            },
            "decide": {
                "decision": "HUMAN_REVIEW",
                "risk_level": "UNKNOWN",
                "reason": "Agent response was not valid JSON."
            },
            "act": {
                "action": "HUMAN_REVIEW",
                "target": "Researcher",
                "safe_action": True
            },
            "sense_again": {
                "required": True,
                "interval_minutes": 5,
                "parameters": [
                    "temperature",
                    "humidity",
                    "pressure",
                    "plant_image"
                ]
            }
        }

    action = decision.get("decide", {}).get("decision")

    if action not in ALLOWED_ACTIONS:
        decision["decide"] = {
            "decision": "HUMAN_REVIEW",
            "risk_level": "UNKNOWN",
            "reason": f"Unsafe/unknown action from agent: {action}"
        }
        decision["act"] = {
            "action": "HUMAN_REVIEW",
            "target": "Researcher",
            "safe_action": True
        }

    # Force safe state in this research version.
    decision.setdefault("act", {})["safe_action"] = True

    print("\nAGENT DECISION")
    print("-" * 60)
    print(json.dumps(decision, indent=4))

    return decision


# ============================================================
# STEP 5 - MQTT ACT
# ============================================================

def publish_action(decision):
    print("\n" + "=" * 60)
    print("STEP 5: ACT")
    print("=" * 60)

    act = decision.get("act", {})
    action = act.get("action", "HUMAN_REVIEW")
    target = act.get("target", "Researcher")

    # Research-safe mapping.
    actuator_command = {
        "MONITOR": "NONE",
        "ALERT": "ALERT",
        "RECHECK": "NONE",
        "HUMAN_REVIEW": "ALERT",
        "IRRIGATION_SIMULATION": "IRRIGATION",
        "SPRAY_SIMULATION": "SPRAY",
    }.get(action, "ALERT")

    message = {
        "timestamp": now_iso(),
        "action": action,
        "target": target,
        "actuator_command": actuator_command,
        "mode": ACTUATOR_MODE,
        "physical_actuation": False,
    }

    print("Action :", action)
    print("Target :", target)
    print("Mode   :", ACTUATOR_MODE)
    print("MQTT   :", json.dumps(message))

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"RPi5_AGENT_{int(time.time())}"
    )

    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        result = client.publish(
            MQTT_ACTION_TOPIC,
            json.dumps(message)
        )
        result.wait_for_publish()
        client.disconnect()
        print("MQTT action published.")
    except Exception as e:
        print("MQTT action publish error:", e)

    return message


# ============================================================
# SAVE
# ============================================================

def save_results(edge, samples, sensor_summary, report, decision, action):
    ts = stamp()

    record = {
        "timestamp": now_iso(),
        "architecture": [
            "Sense",
            "Perceive",
            "Understand",
            "Decide",
            "Act",
            "Sense Again"
        ],
        "window_minutes": HISTORY_MINUTES,
        "edge_ai": edge,
        "sensor_history": samples,
        "sensor_summary": sensor_summary,
        "generative_ai": {
            "model": GEMINI_MODEL,
            "report": report
        },
        "agentic_ai": decision,
        "action": action,
        "actuator_mode": ACTUATOR_MODE,
        "research_note": (
            "Five-minute environmental trend is used to demonstrate "
            "short-horizon progression/risk reasoning. It is not a "
            "validated biological disease forecast."
        )
    }

    json_path = os.path.join(
        RESULT_DIR,
        f"pipeline_5min_{ts}.json"
    )

    txt_path = os.path.join(
        RESULT_DIR,
        f"pipeline_5min_{ts}.txt"
    )

    with open(json_path, "w") as f:
        json.dump(record, f, indent=4)

    with open(txt_path, "w") as f:
        f.write("PLANT EDGE AI - 5 MINUTE CLOSED LOOP\n")
        f.write("=" * 60 + "\n\n")
        f.write("YOLO:\n")
        f.write(json.dumps(edge, indent=4))
        f.write("\n\nBME280 SUMMARY:\n")
        f.write(json.dumps(sensor_summary, indent=4))
        f.write("\n\nGENERATIVE AI REPORT:\n")
        f.write(report)
        f.write("\n\nAGENTIC AI:\n")
        f.write(json.dumps(decision, indent=4))
        f.write("\n\nACTION:\n")
        f.write(json.dumps(action, indent=4))

    print("\n" + "=" * 60)
    print("RESULTS SAVED")
    print("=" * 60)
    print(json_path)
    print(txt_path)


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 60)
    print("PLANT AI CLOSED-LOOP PIPELINE - 5 MINUTE VERSION")
    print("=" * 60)
    print()
    print("Sense -> Perceive -> Understand -> Decide -> Act -> Sense Again")
    print()
    print("YOLO26n      :", YOLO_MODEL)
    print("Image        :", IMAGE_PATH)
    print("BME280 window:", HISTORY_MINUTES, "minutes")
    print("Gemini       :", GEMINI_MODEL)
    print("Actuator     :", ACTUATOR_MODE)

    edge = run_yolo()

    collector = SensorCollector()
    samples = collector.collect(HISTORY_MINUTES)

    if len(samples) < MIN_SAMPLES:
        raise RuntimeError(
            f"Only {len(samples)} sensor samples received. "
            f"Need at least {MIN_SAMPLES}."
        )

    sensor_summary = summarize_sensor_history(samples)

    print("\nBME280 TREND SUMMARY")
    print(json.dumps(sensor_summary, indent=4))

    report, client = run_genai(edge, sensor_summary)

    decision = run_agent(
        edge,
        sensor_summary,
        report,
        client
    )

    action = publish_action(decision)

    save_results(
        edge,
        samples,
        sensor_summary,
        report,
        decision,
        action
    )

    print("\n" + "=" * 60)
    print("CLOSED-LOOP CYCLE COMPLETE")
    print("=" * 60)
    print("Sense")
    print("  ↓")
    print("Perceive - YOLO26n")
    print("  ↓")
    print("Understand - Gemini + 5-min BME280 trend")
    print("  ↓")
    print("Predict progression/risk")
    print("  ↓")
    print("Decide - Agentic AI")
    print("  ↓")
    print("Act - MQTT / SAFE DRY-RUN")
    print("  ↓")
    print("Sense Again - next 5-minute cycle")


if __name__ == "__main__":
    main()
