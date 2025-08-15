# GPGC Greenhouse Monitoring

A fresh, high‑signal README to align backend, frontend, and device operations for Golden Plains Garden Center. This document explains how the system’s parts interact, the backend/server logic, the frontend/user interfaces, and where we’re heading for web and mobile capabilities.

---

## 1) Executive Summary
GPGC is a distributed greenhouse monitoring & control system. Edge devices (Luckfox Pico Ultras) read environmental sensors and expose controls for fans/heaters. A central server (Luckfox Omni 3576) orchestrates the fleet, stores data in Firestore, and serves as the backend for dashboards, alerts, and eventual remote control. On‑prem transport is Modbus TCP for deterministic control; MQTT is optionally used for command/telemetry overlay.

**Primary goals**
- Reliable, timestamped sensor data from each greenhouse.
- Fast, safe control paths (manual + automated rules).
- Cloud persistence + alerting without impacting local operations.
- Repeatable provisioning for new devices.
- Web and mobile interfaces for real‑time monitoring and control.

---

## 2) Backend Architecture
```
[ RS485 SHT20 Sensors ] → [ Waveshare 4‑CH RS485⇄PoE ETH (B) ] → (RTU‑over‑TCP/Modbus TCP) →
[ Luckfox Omni 3576 Backend ] → Firestore (Cloud)

[ BME688 + Display ] → [ Luckfox Pico Ultra ] → (Modbus TCP) → [ Luckfox Omni 3576 Backend ]
```
**Backend Roles**
- **RS485 Gateway**: Bridges RS485 sensors to Ethernet.
- **Backend Poller (Omni)**: Polls RS485 sensors and Pico nodes, normalizes data, writes to Firestore.
- **Automation Engine**: Executes rules for alerts and device control.
- **API Layer**: Serves REST/GraphQL endpoints for frontend consumption.
- **MQTT Bridge**: Handles optional pub/sub commands and telemetry.

---

## 3) Frontend Architecture (Current & Planned)
- **Phase 1 (Current)**: Local admin tools and cloud dashboards for monitoring.
- **Phase 2 (Planned)**: Web application served by Omni’s built‑in webserver.
  - Real‑time charts, device status, and control toggles.
  - User authentication and role‑based access.
- **Phase 3 (Future)**: Native iOS and Android apps.
  - Push notifications for alerts.
  - Offline caching for last‑known readings.
  - Mobile control of fans, heaters, and irrigation.

---

## 4) Data Flow
1. Sensors send data via Modbus RTU/TCP to Omni.
2. Omni backend ingests and processes readings.
3. Firestore stores historical data.
4. Frontend queries backend/cloud for display.
5. Control commands travel from frontend → backend → device.

---

## 5) Repository Layout
```
repo-root/
├─ backend/                # Omni apps, API server, pollers
├─ edge/                   # Pico firmware, drivers, configs
├─ frontend/               # Web UI code (future)
├─ mobile/                 # iOS/Android app code (future)
├─ cloud/                  # Firestore rules, functions
├─ tools/                  # Provisioning, diagnostics
├─ docs/                   # Documentation, diagrams
└─ .env.example
```

---

## 6) Roadmap (From Project Timeline)
- Phase 1: Sensor setup & connectivity
- Phase 2: Alert system configuration
- Phase 3: Manual control implementation
- Phase 4: Automated climate response
- Phase 5 (Planned): Web dashboard with control.
- Phase 6 (Future): iOS/Android apps.

---

## 7) Security & Access
- API authentication for web/mobile.
- SSH key auth for backend hosts.
- Cloud creds stored only on Omni.

---

## 8) License & Contact
License: Private (GPGC). Maintainer: <add your name/contact>.
