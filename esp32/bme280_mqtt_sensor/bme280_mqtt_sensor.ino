#include <WiFi.h>
#include <PubSubClient.h>
#include <Wire.h>
#include <Adafruit_BME280.h>

// Wi-Fi credentials and broker IP are kept in secrets.h (not committed).
// Copy secrets_example.h to secrets.h and fill in your own values.
#include "secrets.h"

// ============================================================
// WIFI CONFIGURATION
// ============================================================

const char* WIFI_SSID = SECRET_WIFI_SSID;
const char* WIFI_PASSWORD = SECRET_WIFI_PASSWORD;

// ============================================================
// RASPBERRY PI 5 MQTT CONFIGURATION
// ============================================================

// IP address of the Raspberry Pi 5 running the Mosquitto broker (set in secrets.h)
const char* MQTT_SERVER = SECRET_MQTT_SERVER;

const int MQTT_PORT = 1883;

// ============================================================
// MQTT TOPIC
// ============================================================

const char* MQTT_TOPIC = "plant/sensor";

// ============================================================
// DEVICE ID
// ============================================================

const char* DEVICE_ID = "ESP32_BME280_01";

// ============================================================
// BME280
// ============================================================

Adafruit_BME280 bme;

// ============================================================
// NETWORK CLIENTS
// ============================================================

WiFiClient espClient;
PubSubClient mqttClient(espClient);

// ============================================================
// CONNECT TO WIFI
// ============================================================

void connectWiFi()
{
    Serial.println();
    Serial.println("Connecting to WiFi...");

    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    while (WiFi.status() != WL_CONNECTED)
    {
        delay(500);
        Serial.print(".");
    }

    Serial.println();
    Serial.println("WiFi connected");

    Serial.print("ESP32 IP address: ");
    Serial.println(WiFi.localIP());
}

// ============================================================
// CONNECT TO MQTT
// ============================================================

void connectMQTT()
{
    while (!mqttClient.connected())
    {
        Serial.print("Connecting to MQTT broker...");

        String clientID = "ESP32_BME280_01_";
        clientID += String((uint32_t)ESP.getEfuseMac(), HEX);

        if (mqttClient.connect(clientID.c_str()))
        {
            Serial.println("CONNECTED");
        }
        else
        {
            Serial.print("FAILED, rc=");
            Serial.print(mqttClient.state());

            Serial.println(" retrying in 3 seconds...");

            delay(3000);
        }
    }
}

// ============================================================
// SETUP
// ============================================================

void setup()
{
    Serial.begin(115200);

    delay(1000);

    Serial.println();
    Serial.println("============================================================");
    Serial.println("ESP32 + BME280 MQTT SENSOR");
    Serial.println("============================================================");

    // --------------------------------------------------------
    // I2C
    // --------------------------------------------------------

    Wire.begin(21, 22);

    // --------------------------------------------------------
    // BME280
    // --------------------------------------------------------

    bool status = bme.begin(0x76);

    if (!status)
    {
        Serial.println("BME280 not found at address 0x76");

        Serial.println("Trying address 0x77...");

        status = bme.begin(0x77);

        if (!status)
        {
            Serial.println("ERROR: BME280 not detected.");
            Serial.println("Check wiring.");

            while (1)
            {
                delay(1000);
            }
        }
    }

    Serial.println("BME280 detected successfully.");

    // --------------------------------------------------------
    // WIFI
    // --------------------------------------------------------

    connectWiFi();

    // --------------------------------------------------------
    // MQTT
    // --------------------------------------------------------

    mqttClient.setServer(MQTT_SERVER, MQTT_PORT);

    connectMQTT();
}

// ============================================================
// LOOP
// ============================================================

void loop()
{
    if (WiFi.status() != WL_CONNECTED)
    {
        connectWiFi();
    }

    if (!mqttClient.connected())
    {
        connectMQTT();
    }

    mqttClient.loop();

    // --------------------------------------------------------
    // READ SENSOR
    // --------------------------------------------------------

    float temperature = bme.readTemperature();

    float humidity = bme.readHumidity();

    float pressure = bme.readPressure() / 100.0F;

    // --------------------------------------------------------
    // CHECK SENSOR
    // --------------------------------------------------------

    if (isnan(temperature) ||
        isnan(humidity) ||
        isnan(pressure))
    {
        Serial.println("ERROR: Failed to read BME280.");

        delay(2000);

        return;
    }

    // --------------------------------------------------------
    // CREATE JSON
    // --------------------------------------------------------

    char payload[256];

    snprintf(
        payload,
        sizeof(payload),

        "{"
        "\"device\":\"%s\","
        "\"temperature\":%.2f,"
        "\"humidity\":%.2f,"
        "\"pressure\":%.2f"
        "}",

        DEVICE_ID,
        temperature,
        humidity,
        pressure
    );

    // --------------------------------------------------------
    // PRINT
    // --------------------------------------------------------

    Serial.println();
    Serial.println("------------------------------------------------------------");

    Serial.print("Temperature : ");
    Serial.print(temperature);
    Serial.println(" °C");

    Serial.print("Humidity    : ");
    Serial.print(humidity);
    Serial.println(" %");

    Serial.print("Pressure    : ");
    Serial.print(pressure);
    Serial.println(" hPa");

    Serial.print("MQTT Topic  : ");
    Serial.println(MQTT_TOPIC);

    Serial.print("Payload     : ");
    Serial.println(payload);

    // --------------------------------------------------------
    // PUBLISH
    // --------------------------------------------------------

    bool success = mqttClient.publish(
        MQTT_TOPIC,
        payload
    );

    if (success)
    {
        Serial.println("MQTT publish: SUCCESS");
    }
    else
    {
        Serial.println("MQTT publish: FAILED");
    }

    Serial.println("------------------------------------------------------------");

    // Send every 5 seconds
    delay(5000);
}