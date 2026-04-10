from flask import Flask, render_template
from flask_socketio import SocketIO
from bmp180 import BMP180
from mpu6050 import mpu6050
from queue import Queue
import time
import math
from tfluna import TFLuna
from picamera2 import Picamera2
import io
import base64
import random

# Create Flask app
app = Flask(__name__)
socketio = SocketIO(app)

# Constants
START_TIME = time.time()
I2C_ADDRESS_FOR_MPU = 0x68
PRESSURE_AT_SEA_LEVEL = 1001.6
CAMERA_HERTZ_THRESHOLD = 1 / 15

# Sensor setup
bmp = BMP180()
mpu = mpu6050(I2C_ADDRESS_FOR_MPU)
tfluna = TFLuna()
camera = Picamera2()

tfluna.open()
tfluna.set_samp_rate(5)

camera_config = camera.create_preview_configuration(main={"size": (640, 480)})
camera.configure(camera_config)
camera.start()

# Queue / request state
queue = Queue()
barometricPressureRequest = False
collectMapData = False

# Data dictionaries
dataDictionary = {}
heightDictionary = {}
dataDictionary["accelerometer"] = ({}, {}, {}, {}, {}, {}, {})
dataDictionary["lidar"] = {}

# Position/orientation variables
x = 0
y = 0
z = 0
yaw = 0
pitch = 0
roll = 0


def airPressureToHeight(pressure):
    return 44330 * (1 - math.pow((pressure / PRESSURE_AT_SEA_LEVEL), 0.1903))


def toRadians(degrees):
    return degrees * (math.pi / 180)


def processLidarData(dataDictionary, deltaTime, lidarDistance, gyroData):
    theta = 0.5 * gyroData['y'] * deltaTime * deltaTime
    radius = round(lidarDistance * 100.0, 2)  # centimeters

    dataDictionary["lidar"][len(dataDictionary["lidar"])] = (
        radius * math.cos(toRadians(theta)),
        radius * math.sin(toRadians(theta))
    )


def processPositionData(dataDictionary, deltaTime, accelerometerData, gyroData):
    global x, y, z, yaw, pitch, roll

    dataDictionary["accelerometer"][0][len(dataDictionary["accelerometer"][0])] = deltaTime
    dataDictionary["accelerometer"][1][len(dataDictionary["accelerometer"][1])] = accelerometerData['x']
    dataDictionary["accelerometer"][2][len(dataDictionary["accelerometer"][2])] = accelerometerData['y']
    dataDictionary["accelerometer"][3][len(dataDictionary["accelerometer"][3])] = accelerometerData['z']
    dataDictionary["accelerometer"][4][len(dataDictionary["accelerometer"][4])] = gyroData['x']
    dataDictionary["accelerometer"][5][len(dataDictionary["accelerometer"][5])] = gyroData['y']
    dataDictionary["accelerometer"][6][len(dataDictionary["accelerometer"][6])] = gyroData['z']

    x += 0.5 * accelerometerData['x'] * deltaTime * deltaTime
    y += 0.5 * accelerometerData['y'] * deltaTime * deltaTime
    z += 0.5 * accelerometerData['z'] * deltaTime * deltaTime

    yaw += 0.5 * gyroData['x'] * deltaTime * deltaTime
    pitch += 0.5 * gyroData['y'] * deltaTime * deltaTime
    roll += 0.5 * gyroData['z'] * deltaTime * deltaTime

    return (x, y, z, yaw, pitch, roll)


def handle_image_request():
    stream = io.BytesIO()
    camera.capture_file(stream, format='jpeg')
    stream.seek(0)

    b64_image = base64.b64encode(stream.read()).decode('utf-8')
    socketio.emit('new_image', {'image_data': b64_image})


def background_thread(queue):
    global barometricPressureRequest, collectMapData

    previousTime = time.time()
    timeSinceLastFrame = 0

    while True:
        socketio.sleep(1)

        currentTime = time.time()
        deltaTime = currentTime - previousTime

        barometricPressure = bmp.get_pressure()
        accelerometerData = mpu.get_accel_data()
        gyroData = mpu.get_gyro_data()
        lidarDistance, lidarStrength, lidarTemp = tfluna.read()

        heightDictionary[deltaTime] = airPressureToHeight(barometricPressure)

        dataDictionary["position"] = processPositionData(
            dataDictionary,
            deltaTime,
            accelerometerData,
            gyroData
        )

        timeSinceLastFrame += deltaTime

        if timeSinceLastFrame >= CAMERA_HERTZ_THRESHOLD:
            timeSinceLastFrame = 0
            handle_image_request()

        try:
            request = queue.get(False)

            match request[0]:
                case "Barometric":
                    barometricPressureRequest = request[1]
                case "Lidar":
                    collectMapData = request[1]
        except:
            pass

        if barometricPressureRequest is True:
            print("send barometric pressure")
            dataDictionary["barometricPressure"] = heightDictionary
            barometricPressureRequest = False

        dataDictionary["randomNumber"] = random.randint(1, 100)

        if collectMapData:
            processLidarData(dataDictionary, deltaTime, lidarDistance, gyroData)

        socketio.emit(
            'update_data',
            dataDictionary
        )

        previousTime = currentTime


# Runs when someone connects
@socketio.on('connect')
def handle_connect():
    print('Client connected')
    socketio.start_background_task(target=background_thread, queue=queue)


@socketio.on('drawMap')
def collectMapDataEvent():
    global collectMapData
    collectMapData = not collectMapData
    queue.put(("Lidar", collectMapData))


@socketio.on('requestBarometricPressure')
def requestBarometricPressure():
    queue.put(("Barometric", True))


@app.route('/')
def index():
    return render_template('index.html')


def main():
    socketio.run(app, host='0.0.0.0', port=80, allow_unsafe_werkzeug=True)


if __name__ == '__main__':
    main()
