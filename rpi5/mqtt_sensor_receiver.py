import json
import paho.mqtt.client as mqtt

# ============================================================
# MQTT CONFIGURATION
# ============================================================

MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC = "plant/sensor"


# ============================================================
# CONNECT CALLBACK
# ============================================================

def on_connect(client, userdata, flags, reason_code, properties=None):

    if reason_code == 0:

        print()
        print("=" * 60)
        print("RPI5 MQTT SENSOR RECEIVER")
        print("=" * 60)

        print("MQTT Broker :", MQTT_BROKER)
        print("MQTT Port   :", MQTT_PORT)
        print("MQTT Topic  :", MQTT_TOPIC)

        print()
        print("Connected successfully!")
        print("Waiting for ESP32 + BME280 data...")
        print("=" * 60)

        client.subscribe(MQTT_TOPIC)

    else:

        print("MQTT connection failed.")
        print("Reason code:", reason_code)


# ============================================================
# MESSAGE CALLBACK
# ============================================================

def on_message(client, userdata, msg):

    print()
    print("-" * 60)
    print("MQTT DATA RECEIVED")
    print("-" * 60)

    print("Topic:", msg.topic)

    try:

        # Convert MQTT payload to text
        payload = msg.payload.decode()

        # Convert JSON string to Python dictionary
        data = json.loads(payload)

        print()
        print("Complete JSON:")
        print(json.dumps(data, indent=4))

        # ----------------------------------------------------
        # Extract values
        # ----------------------------------------------------

        device = data.get("device")

        temperature = data.get("temperature")

        humidity = data.get("humidity")

        pressure = data.get("pressure")

        # ----------------------------------------------------
        # Display sensor values
        # ----------------------------------------------------

        print()
        print("Device      :", device)
        print("Temperature :", temperature, "°C")
        print("Humidity    :", humidity, "%")
        print("Pressure    :", pressure, "hPa")

        print("-" * 60)

    except Exception as e:

        print("ERROR processing MQTT message:")
        print(e)

        print("Raw message:")
        print(msg.payload.decode())


# ============================================================
# CREATE MQTT CLIENT
# ============================================================

client = mqtt.Client(
    mqtt.CallbackAPIVersion.VERSION2,
    client_id="RPI5_SENSOR_RECEIVER"
)

client.on_connect = on_connect
client.on_message = on_message


# ============================================================
# CONNECT TO MOSQUITTO
# ============================================================

print()
print("Connecting to MQTT broker...")

client.connect(
    MQTT_BROKER,
    MQTT_PORT,
    60
)


# ============================================================
# START MQTT LOOP
# ============================================================

client.loop_forever()
