

import network
import socket
import urequests
import time
import utime
import gc
import machine
import struct
import math
import os
from time import sleep
from struct import unpack
from machine import Pin, I2C ,UART ,Timer
from umodbus.serial import Serial
from ota import OTAUpdater


wlan = network.WLAN(network.STA_IF)
wlan.active(True)
#wlan.ifconfig(('10.42.0.3', '255.255.255.0', '10.42.0.1', '1.1.1.1'))
ssid = 'LUFTQI' 
password = '82767419'



#wifi connect
def wifi_connect(ssid,password):    
    
    wlan.connect(ssid,password)    
    wait = 60
    while wait > 0:
        if wlan.status() < 0 or wlan.status() >= 3:
            break
        wait -= 1
        print('waiting for connection..%s' %wait)
        time.sleep(1)
 
    # Handle connection error
    if wlan.status() != 3:        
        print('network connection failed')
        machine.reset()
        
    else:
        print('connected')
        ip=wlan.ifconfig()[0]
        print('IP: ', ip)

#wifi connect
time.sleep(0.5)
try:
    wifi_connect(ssid,password)
    print("coonect")   
except OSError as e: 
    print(e)
    machine.reset()    

led = Pin(25, Pin.OUT)
firmware_url = f"https://github.com/luftqi/solar_picow/refs/heads/main/"
ota_updater = OTAUpdater(firmware_url, "main.py")
ota_updater.download_and_install_update_if_available()

while True:
  led.value(1)   # LED亮
  led.value(0)

