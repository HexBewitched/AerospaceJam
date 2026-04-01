# These two modules allow us to run a web server.
from flask import Flask, render_template
from flask_socketio import SocketIO
from bmp180 import BMP180
from mpu6050 import mpu6050
from queue import Queue
from datetime import time
# This module lets us pick random numbers, you can remove it later.
import random

# Here, we create the neccesary base app. You don't need to worry about this.
app = Flask(__name__)
socketio = SocketIO(app)

#sensor and other objects are defined here
bmp = BMP180()
mpu = mpu6050(I2C_ADDRESS_FOR_MPU)

#variables to handle button requests
queue = Queue()
barometricPressureRequest = False

#the dictionary for the data to be sent to the app
dataDictionary = { }
heightDictionary = { }
dataDictionary["accelerometer"] = ({}, {}, {}, {}, {}, {}, {})

#specific variables to handle drone position
x = 0
y = 0
z = 0
yaw = 0 #x axis
pitch = 0 #y axis
roll = 0 #z axis

#constants
START_TIME = time.time()
I2C_ADDRESS_FOR_MPU = 0x68
PRESSURE_AT_SEA_LEVEL = 1001.6 #TODO: check local airport report for this value day of

# When someone requests the root page from our web server, we return 'index.html'.
@app.route('/')
def index():
    return render_template('index.html')

# This function runs in the background to transmit data to connected clients.
def background_thread(queue):
    barometricPressureRequest = False
    while True:
        # We sleep here for a single second, but this can be increased or decreased depending on how quickly you want data to be pushed to clients.
        socketio.sleep(1)
        deltaTime = time.time() - START_TIME
        barometricPressure = bmp.get_pressure()
        accelerometerData = mpu.get_accel_data()
        gyroData = mpu.get_gyro_data()
        heightDictionary["" + deltaTime] = pressureToHeight(barometricPressure)
        
        dataDictionary["position"] = processPositionData(dataDictionary, deltaTime, accelerometerData, gyroData)

        try:
            request = queue.get(False) #false makes it not stop if the queue is empty
            match request[0]:
                case barometric:
                    barometricPressureRequest = request[1]
        except:
            pass
        #this is where we add data to the dictionary if it has been requested
        if barometricPressureRequest == True:
            print('send barometric pressure')
            dataDictionary['barometricPressure'] = heightDictionary
            barometricPressureRequest = False
        dataDictionary['randomNumber'] = random.randint(1, 100)

        # Then, we emit an event called "update_data" - but this can actually be whatever we want - with the data being a dictionary
        # where 'randomNumber' is set to a random number we choose here. You should replace the data being sent back with your sensor data
        # that you fetch from things connected to your Pi.
        socketio.emit(
            'update_data', #event name
            dataDictionary #dictionary of data to send    
        )
        # To add a your first new sensor, try giving https://docs.aerospacejam.org/getting-started/first-sensor a read!

# This function runs when someone connects to the server - and all we do is start the background thread to update the data.
@socketio.on('connect')
def handle_connect():
    print('Client connected')
    socketio.start_background_task(target=background_thread, queue=queue)

#setter functions for the requests from the app
@socketio.on('requstBarometricPressure')
def requestBarometricPressure():
    queue.put((Barometric, True)) #have this change sync across threads

def airPressureToHeight(pressure):
    return 44330 * ( 1 - math.pow((pressure / PRESSURE_AT_SEA_LEVEL), 0.1903))

def processPositionData(dataDictionary, deltaTime, accelerometerData, gyroData):
    dataDictionary["accelerometer"][0][len(dataDictionary["accelerometer"][0])] = deltaTime
    dataDictionary["accelerometer"][0][len(dataDictionary["accelerometer"][1])] = accelerometerData['x']
    dataDictionary["accelerometer"][0][len(dataDictionary["accelerometer"][2])] = accelerometerData['y']
    dataDictionary["accelerometer"][0][len(dataDictionary["accelerometer"][3])] = accelerometerData['z']
    dataDictionary["accelerometer"][0][len(dataDictionary["accelerometer"][4])] = gyroData['x']
    dataDictionary["accelerometer"][0][len(dataDictionary["accelerometer"][5])] = gyroData['y']
    dataDictionary["accelerometer"][0][len(dataDictionary["accelerometer"][6])] = gyroData['z']
    x += (1/2) * accelerometerData['x'] * deltaTime * deltaTime
    y += (1/2) * accelerometerData['y'] * deltaTime * deltaTime
    z += (1/2) * accelerometerData['z'] * deltaTime * deltaTime
    yaw += (1/2) * gyroData['x'] * deltaTime * deltaTime
    pitch += (1/2) * gyroData['y'] * deltaTime * deltaTime
    roll += (1/2) * gyroData['z'] * deltaTime * deltaTime
    return (x, y, z, yaw, pitch, roll)

# This function is called
def main():
    # These specific arguments are required to make sure the webserver is hosted in a consistent spot, so don't change them unless you know what you're doing.
    socketio.run(app, host='0.0.0.0', port=80, allow_unsafe_werkzeug=True)

if __name__ == '__main__':
    main()
