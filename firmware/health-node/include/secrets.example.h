#pragma once

// Copy this file to include/secrets.h, then fill in local values.
// include/secrets.h is intentionally ignored by Git.
// Provisioning uses a different ignored file: copy
// include/provisioning_secret.example.h to include/provisioning_secret.h.
#define WIFI_SSID "your-hotspot-name"
#define WIFI_PASSWORD "your-hotspot-password"

// Must match the -DeviceId value used by Initialize-Mosquitto.ps1.
#define DEVICE_ID "health-node-01"

// Use the laptop IPv4 address visible to devices on the same hotspot.
#define MQTT_HOST "192.168.1.10"
#define MQTT_PORT 1883
#define MQTT_USERNAME "health_node"
#define MQTT_PASSWORD "replace-with-a-local-password"
