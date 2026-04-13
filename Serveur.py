import asyncio
import json
from datetime import datetime
from dronekit import connect, VehicleMode
import math
import websockets
from collections import deque
import time
import serial.tools.list_ports




# ------------------ CONFIGURATION ------------------
TCP_ADDRESS = 'tcp:127.0.0.1:5763'
WEBSOCKET_PORT = 8765
SEND_INTERVAL = 0.04  # 25 FPS max (20ms)
ports = serial.tools.list_ports.comports()
vehicle = None

for port in ports:
    try:
        print(f"Tentative sur {port.device} ({port.description})...")
        vehicle = connect(port.device, baud=57600, wait_ready=True, timeout=5)
        print(f"Connexion réussie sur {port.device} !")
        break
    except Exception:
        print(f"Impossible de se connecter sur {port.device}")

if vehicle is None:
# ------------------ CONNEXION DRONE ------------------
    print(f"Connexion au drone via {TCP_ADDRESS}...")
    vehicle = connect(TCP_ADDRESS, wait_ready=True)
    print("Drone connecté !")


time_start = datetime.now()


# ------------------ VARIABLES GLOBALES ------------------
last_velocity_z = 0.0
last_time = time.time()
last_altitude = getattr(vehicle.location.global_relative_frame, 'alt', 0) or 0


# ------------------ BUFFER DONNÉES ------------------
class DroneDataBuffer:
    def __init__(self):
        self.buffer = deque(maxlen=10)
    
    def add_data(self, data):
        self.buffer.append(data)
    
    def get_latest(self):
        if self.buffer:
            return self.buffer[-1]
        return None


data_buffer = DroneDataBuffer()


# ------------------ FONCTION DONNÉES ------------------
def get_drone_data(time_elapsed):
    global last_velocity_z, last_time, last_altitude
    try:
        # Altitude
        altitude = getattr(vehicle.location.global_relative_frame, 'alt', 0) or 0

        # Vitesse
        speed = 0
        vz = 0
        try:
            if vehicle.velocity and len(vehicle.velocity) == 3:
                vx, vy, vz = vehicle.velocity
                speed = math.sqrt(vx**2 + vy**2 + vz**2)
        except:
            speed = 0
            vz = 0

        # Orientation
        roll = pitch = yaw = 0
        try:
            att = vehicle.attitude
            if att:
                roll = math.degrees(att.roll)
                pitch = math.degrees(att.pitch)
                yaw = math.degrees(att.yaw)
        except:
            pass

        # ------------------ CALCUL ACCELERATION P
        vertical_acc = vz
        
        # Pression
        try:
            pressure = getattr(vehicle, 'barometer', None)  # tentative dronekit
            if pressure is None:
                pressure = 1013.25  # valeur par défaut en hPa
        except:
            pressure = 1013.25

        # Température
        try:
            temperature = getattr(vehicle, 'temperature', None)
            if temperature is None:
                temperature = 25.0  # valeur par défaut en °C
        except:
            temperature = 25.0

        
        

        # Création du dictionnaire
        data = {
            "time": round(time_elapsed, 2),
            "altitude": round(altitude, 2),
            "speed": round(speed, 2),
            "vertical_acc": round(vertical_acc, 2),
            "roll": round(roll, 2),
            "pitch": round(pitch, 2),
            "yaw": round(yaw, 2),
            "pressure": round(pressure, 2),
            "temperature": round(temperature, 2),
            "mode": getattr(vehicle.mode, 'name', 'UNKNOWN'),
            "armed": bool(vehicle.armed)
        }

        data_buffer.add_data(data)
        return data
        
    except Exception as e:
        print(f"Erreur données: {e}")
        return {
            "time": round(time_elapsed, 2),
            "altitude": 0, "speed": 0, "vertical_acc": 0,
            "roll": 0, "pitch": 0, "yaw": 0,
            "mode": "ERROR", "armed": False
        }


# ------------------ LOOP DRONE ------------------
async def drone_loop():
    while True:
        try:
            elapsed = (datetime.now() - time_start).total_seconds()
            get_drone_data(elapsed)
            await asyncio.sleep(0.016)  # 60Hz collecte
        except Exception as e:
            print(f"Erreur drone_loop: {e}")
            await asyncio.sleep(0.1)


# ------------------ HANDLER WEBSOCKET ------------------
async def handler(websocket):
    print("Client Flutter connecté !")
    last_send = 0
    
    try:
        while True:
            now = time.time()
            if now - last_send >= SEND_INTERVAL:
                latest_data = data_buffer.get_latest()
                if latest_data:
                    await websocket.send(json.dumps(latest_data))
                    last_send = now
            await asyncio.sleep(0.01)
    except websockets.exceptions.ConnectionClosed:
        print("Client déconnecté")
    except Exception as e:
        print(f"Erreur WS: {e}")


# ------------------ MAIN ------------------
async def main():
    async with websockets.serve(handler, "0.0.0.0", WEBSOCKET_PORT):
        drone_task = asyncio.create_task(drone_loop())
        print(" Serveur 20 FPS + Drone 60Hz OK !")
        await asyncio.Future()
        drone_task.cancel()


if __name__ == "__main__":
    try:
        print(f"Serveur WebSocket port {WEBSOCKET_PORT} (20 FPS)...")
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Arrêt serveur...")
    finally:
        vehicle.close()
        print("Drone déconnecté")
