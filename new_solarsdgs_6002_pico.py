# 引入所需的函式庫
import network
import socket
import urequests
import time
import utime
import ntptime
import gc
import machine
import struct
import math
import os
import ina226
import ujson
import select
from time import sleep
from struct import unpack
from machine import Pin, I2C ,UART ,Timer
from ota import OTAUpdater
from simple import MQTTClient


# --- 設備與網路設定 ---
iot = "6002"  # 設備編號
wifi_wait_time = 60  # 開機後等待 Pi Zero 2 開機並建立 WiFi 的時間

# --- 硬體引腳設定 ---
led = machine.Pin("LED", machine.Pin.OUT)
led.on()
pin_6 = Pin(6, mode=Pin.OUT) # 用於控制 Pi Zero 2 的電源
pin_7 = Pin(7, mode=Pin.OUT) # 用於控制 INA226 的 IV 切換
pin_6.on()
pin_7.off()

# --- Wi-Fi 連線設定 ---
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wlan.config(pm = 0xa11140) # 關閉 Wi-Fi 省電模式
#ssid = b'solarsdgs'+iot
#password = b'82767419'
ssid = b'LUFTQI'
password = b'82767419'


# --- I2C 與感測器設定 ---
SHUNT_OHMS = 0.1
i2c = I2C(0,scl=Pin(1), sda=Pin(0))
devices = i2c.scan()
if not devices:
  print("錯誤: 找不到任何 I2C 設備!")
else:
  print('找到 %d 個 I2C 設備: %s' % (len(devices), [hex(d) for d in devices]))

# --- 函數定義 ---
def power_read():
    """讀取三個 INA226 感測器的電壓與電流，並計算功率。"""
    try:
        ina = ina226.INA226(i2c, int(devices[0]))
        inb = ina226.INA226(i2c, int(devices[1]))
        inc = ina226.INA226(i2c, int(devices[2]))
        
        ina.set_calibration()
        inb.set_calibration()
        inc.set_calibration()
        
        utime.sleep_ms(10)
        vg = ina.bus_voltage
        utime.sleep_ms(10)
        va = inb.bus_voltage
        utime.sleep_ms(10)
        vp = inc.bus_voltage
           
        pin_7.on()
        time.sleep(1)
        
        ig = ina.shunt_voltage * 100000
        utime.sleep_ms(10)
        ia = inb.shunt_voltage * 100000
        utime.sleep_ms(10)
        ip = inc.shunt_voltage * 100000
        pin_7.off()
        
        pg = int((ig if ig > 10 else 0) * (vg if vg > 1 else 0))
        pa = int((ia if ia > 10 else 0) * (va if va > 1 else 0))
        pp = int((ip if ip > 10 else 0) * (vp if vp > 1 else 0))
        
        print(f"Pg={pg}W, Pa={pa}W, Pp={pp}W")
        return pg, pa, pp
    except Exception as e:
        print(f"讀取功率時發生錯誤: {e}")
        return 0, 0, 0

# --- 時間同步設定 ---
rtc = machine.RTC()
NTP_DELTA = 3155673600 if time.gmtime(0)[0] == 2000 else 2208988800
host = "clock.stdtime.gov.tw"

def set_time(hrs_offset=8):
    """透過 NTP 同步網路時間並設定 RTC"""
    try:
        ntptime.NTP_DELTA = NTP_DELTA
        ntptime.host = host
        ntptime.settime()
        now_time = time.localtime((time.time() + hrs_offset*3600))
        rtc.datetime((now_time[0], now_time[1], now_time[2], now_time[6], now_time[3], now_time[4], now_time[5], 0))
        print("RTC 時間設定完成:", rtc.datetime())
    except Exception as e:
        print(f"NTP 時間同步失敗: {e}")

def wifi_connect(ssid, password):
    """連接到指定的 Wi-Fi 網路"""
    if wlan.isconnected(): return
    wlan.connect(ssid, password)
    for _ in range(30):
        if wlan.status() >= 3:
            print(f'Wi-Fi 連線成功，IP: {wlan.ifconfig()[0]}')
            return
        print('等待 Wi-Fi 連線...')
        time.sleep(1)
    print('Wi-Fi 連線失敗')

# --- MQTT 設定 ---
#MQTT_SERVER = '10.42.0.1'
MQTT_SERVER = '192.168.50.200'
MQTT_USER = b"solarsdgs" + iot
MQTT_PASSWORD = b"82767419"
MQTT_CLIENT_ID = b'solarsdgs' + iot + '_1'
topic_pub = b'pg_pa_pp'
topic_sub = b'pizero2onoff'

def connect_mqtt():
    """連接到 MQTT 伺服器"""
    try:
        client = MQTTClient(client_id=MQTT_CLIENT_ID, server=MQTT_SERVER, user=MQTT_USER, password=MQTT_PASSWORD, keepalive=7200)
        client.connect()
        print('成功連接到 MQTT Broker')
        return client
    except Exception as e:
        print('連接 MQTT 失敗:', e); time.sleep(5); machine.reset()

def my_callback(topic, message):
    """處理從 Pi Zero 傳來的開關機時間設定"""
    global pizero2_on, pizero2_off
    msg_str = message.decode()
    print(f'收到主題 {topic.decode()}: {msg_str}')
    try:
        on_time, off_time = map(int, msg_str.split('_'))
        if on_time < off_time:
            pizero2_on, pizero2_off = on_time, off_time
            print(f"更新開關機時間為: {pizero2_on}-{pizero2_off} 分")
            with open("pizero2on.txt", "w") as f1: f1.write(str(pizero2_on))
            with open("pizero2off.txt", "w") as f2: f2.write(str(pizero2_off))
    except (ValueError, IndexError):
        print(f"解析訊息 '{msg_str}' 失敗")

# --- 主程式初始化 ---
try:
    with open("pizero2on.txt", "r") as f1: pizero2_on = int(f1.read())
    with open("pizero2off.txt", "r") as f2: pizero2_off = int(f2.read())
except (OSError, ValueError):
    pizero2_on, pizero2_off = 30, 40

reset_hour, reset_minute = 12, 10
timer = Timer()
timer.init(freq=1, mode=Timer.PERIODIC, callback=lambda t: led.toggle())


# --- [修改] 將啟動等待期的採集頻率改為 15 秒 ---
intervals = wifi_wait_time // 15
print(f"開始 {wifi_wait_time} 秒的啟動等待期，期間將每 15 秒收集一次數據...")

for i in range(intervals):
    print("-" * 20)
    remaining_time = wifi_wait_time - (i * 15)
    print(f"Pi Zero 2 開機中，剩餘約 {remaining_time} 秒...")

    # 1. 讀取功率數據
    pg, pa, pp = power_read()
    
    # 2. 獲取當前時間並組合數據字串
    current_time = time.localtime()
    nowtimestamp = f"{current_time[0]}_{current_time[1]}_{current_time[2]}_{current_time[3]}_{current_time[4]}_{current_time[5]}"
    new_data_entry = f"{nowtimestamp}/{pg}/{pa}/{pp},"
    
    # 3. 將數據附加到暫存檔
    with open('data.txt', 'a') as f:
        f.write(new_data_entry)
    print(f"啟動期數據 '{new_data_entry}' 已暫存")
    
    # 4. 等待 15 秒
    print("...等待 15 秒...")
    time.sleep(15)

print("-" * 20)
print("啟動等待期結束，現在嘗試連接 Wi-Fi...")
# --- 修改結束 ---

wifi_connect(ssid, password)
if not wlan.isconnected(): 
    print("Wi-Fi 連線失敗，重啟中...")
    machine.reset()

set_time()
client = connect_mqtt()
client.set_callback(my_callback)
client.subscribe(topic_sub)

# --- 主迴圈 ---
while True:
    # [修改] 精準控制迴圈時間為 15 秒
    loop_start_time = time.time()

    gc.collect()
    current_time = time.localtime()
    current_minute = current_time[4]
    
    print("="*40)
    print(f"時間: {current_time[3]:02d}:{current_minute:02d}, PiZero工作時段: {pizero2_on:02d}-{pizero2_off:02d}分")

    # 讀取功率數據
    pg, pa, pp = power_read()
    nowtimestamp = f"{current_time[0]}_{current_time[1]}_{current_time[2]}_{current_time[3]}_{current_time[4]}_{current_time[5]}"
    # 組成乾淨的、以逗號結尾的資料格式
    new_data_entry = f"{nowtimestamp}/{pg}/{pa}/{pp},"
    
    # 無論如何都先將新數據附加到暫存檔
    with open('data.txt', 'a') as f:
        f.write(new_data_entry)
    print(f"數據 '{new_data_entry}' 已暫存")

    # 檢查是否在 Pi Zero 2 的工作時段內
    if pizero2_on <= current_minute < pizero2_off:
        print("狀態: 進入工作時段，準備上傳")
        pin_6.on()
        timer.init(freq=5, mode=Timer.PERIODIC, callback=lambda t: led.toggle()) # 加快閃爍

        if not wlan.isconnected():
            print("Wi-Fi 中斷，嘗試重連...")
            wifi_connect(ssid, password)
        
        # 只有在網路連線正常時才嘗試發送
        if wlan.isconnected():
            all_data_to_send = ""
            try:
                with open('data.txt', 'r') as f:
                    all_data_to_send = f.read()
            except OSError:
                pass 

            if all_data_to_send:
                payload = f'"{all_data_to_send}"'
                print(f"準備發送所有暫存數據...")
                try:
                    client.publish(topic_pub, payload)
                    print("MQTT 訊息發布成功!")
                    with open('data.txt', 'w') as f: f.write('')
                    print("暫存檔 data.txt 已清空。")
                except Exception as e:
                    print(f"MQTT 發布失敗: {e}。數據將保留。")
            else:
                print("無暫存數據可發送。")
        
        try:
            client.check_msg()
        except Exception as e:
            print(f"檢查MQTT訊息時出錯: {e}")

    else:
        print("狀態: 非工作時段，僅儲存數據")
        pin_6.off()
        timer.init(freq=1, mode=Timer.PERIODIC, callback=lambda t: led.toggle()) # 恢復慢速閃爍

    if current_time[3] == reset_hour and current_minute == reset_minute:
        print("執行每日定時重啟..."); time.sleep(5); machine.reset()

    # --- [修改] 精準控制迴圈時間為 15 秒 ---
    work_duration = time.time() - loop_start_time
    sleep_for = 15 - work_duration
    
    if sleep_for > 0:
        print(f"任務耗時 {work_duration:.2f} 秒，休眠 {sleep_for:.2f} 秒...")
        time.sleep(sleep_for)
    else:
        print(f"警告：單次迴圈任務耗時超過 15 秒 ({work_duration:.2f} 秒)，立即進入下一輪。")
