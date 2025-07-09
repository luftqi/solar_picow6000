import BlynkLib
from paho.mqtt import client as mqtt_client
import time
import datetime
import json
import sqlite3
import requests
import os
from os import system

# --- 設定 ---
iot = '6000'
blynk_token = 'vIrmXGCdWURWrX-FFEsUoDTFNXPmyiVM'
nceid = '8988228066614762251'
nceid_token = "Basic Z3JheUBzb2xhcnNkZ3MuY29tOjk2NzYyMzY0"

# --- 全域變數 ---
factor_a, factor_p = 1.0, 1.0
pizero2_on, pizero2_off = "30", "40"
message, message_check = [], []

# --- MQTT 設定 ---
broker = '127.0.0.1'
port = 1883
topic_sub = "pg_pa_pp"
topic_pub = "pizero2onoff"
topic_ack = "pico/ack"
client_id = f'pizero{iot}_0'
username = f'solarsdgs{iot}'
password = '82767419'

# --- 函數定義 ---
def locator():
    print("正在透過 1NCE API 獲取 GPS 位置...")
    url_token = "https://api.1nce.com/management-api/oauth/token"
    payload = {"grant_type": "client_credentials"}
    headers_token = {"accept": "application/json", "content-type": "application/json", "authorization": nceid_token}
    try:
        token_response = requests.post(url_token, json=payload, headers=headers_token, timeout=10)
        token_response.raise_for_status()
        access_token = token_response.json().get('access_token')
        if not access_token: return None
    except requests.exceptions.RequestException as e:
        print(f"請求 1NCE Access Token 時發生網路錯誤: {e}")
        return None

    url_location = "https://api.1nce.com/management-api/v1/locate/positions/latest?page=1&per_page=1"
    headers_location = {"accept": "application/json", "authorization": f"Bearer {access_token}"}
    try:
        gps_response = requests.get(url_location, headers=headers_location, timeout=15)
        gps_response.raise_for_status()
        data = gps_response.json()
        if data and data.get('items'):
            coordinates = data['items'][0].get('coordinates')
            if coordinates and 'latitude' in coordinates and 'longitude' in coordinates:
                location_str = f"{coordinates['latitude']},{coordinates['longitude']}"
                print(f"成功獲取 1NCE 位置: {location_str}")
                return location_str
        return None
    except (requests.exceptions.RequestException, IndexError, KeyError) as e:
        print(f"請求或解析 1NCE 位置時出錯: {e}")
        return None

# 函數定義現在只需要3個參數
def power_read_and_send(message_list, client, location):
    pggg, paaa, pppp, pgaa, pgpp = [], [], [], [], []

    for data_string in message_list:
        try:
            parts = data_string.split('/')
            time_parts = parts[0].split('_')
            timestruct = '%s-%s-%s %s:%s:%s' % tuple(time_parts)
            localtime = time.strptime(timestruct ,'%Y-%m-%d %H:%M:%S')
            time_stamp_utc = int(time.mktime(localtime))*1000
            pg_val, pa_val, pp_val = map(int, parts[1:])
            pa_calibrated = int(pa_val * factor_a)
            pp_calibrated = int(pp_val * factor_p)
            pga_efficiency = (pa_val - pg_val) / pg_val if pg_val != 0 else 0
            pgp_efficiency = (pp_val - pg_val) / pg_val if pg_val != 0 else 0
            pggg.append([time_stamp_utc, pg_val])
            paaa.append([time_stamp_utc, pa_calibrated])
            pppp.append([time_stamp_utc, pp_calibrated])
            pgaa.append([time_stamp_utc, f"{pga_efficiency:.3f}"])
            pgpp.append([time_stamp_utc, f"{pgp_efficiency:.3f}"])
        except Exception as e:
            print(f"解析數據 '{data_string}' 時發生錯誤: {e}")
            continue

    if not pggg:
        return

    if len(pggg) == 1:
        try:
            blynk.virtual_write(4, pggg[0][1])
            blynk.virtual_write(5, paaa[0][1])
            blynk.virtual_write(6, pppp[0][1])
            blynk.virtual_write(7, float(pgaa[0][1]))
            blynk.virtual_write(8, float(pgpp[0][1]))
        except Exception as e:
            print(f"Blynk 單筆上傳時發生錯誤: {e}")

    elif len(pggg) > 1:
        headers = {'Content-type': 'application/json'}
        base_url = f'https://blynk.cloud/external/api/batch/update?token={blynk_token}'
        data_to_upload = {'v4': pggg, 'v5': paaa, 'v6': pppp, 'v7': pgaa, 'v8': pgpp}
        try:
            for pin_name, data_list in data_to_upload.items():
                upload_url = f'{base_url}&pin={pin_name}'
                response = requests.post(upload_url, headers=headers, json=data_list, timeout=15)
                print(f"{pin_name} 上傳回應: {response.status_code}")
                if response.status_code != 200:
                    print(f"RESPONSE BODY for {pin_name}: {response.text}")
        except requests.exceptions.RequestException as e:
            print(f"Blynk 批次上傳時發生網路錯誤: {e}")

    if location:
        try:
            loc_parts = location.split(',')
            blynk.virtual_write(10, loc_parts[0], loc_parts[1], "Solar Tracker")
        except Exception as e:
            print(f"上傳 GPS 位置時出錯: {e}")

def connect_mqtt():
    def on_connect(client, userdata, flags, rc): print(f"連接本地 MQTT Broker {'成功' if rc == 0 else '失敗'}")
    client = mqtt_client.Client(client_id)
    client.username_pw_set(username, password)
    client.on_connect = on_connect
    client.connect(broker, port)
    return client

def subscribe(client: mqtt_client):
    def on_message(client, userdata, msg):
        global message
        message = [item for item in msg.payload.decode().strip('"').split(',') if item]
    client.subscribe(topic_sub)
    client.on_message = on_message

db_name = f"solarsdgs{iot}.db"
def create_database():
    with sqlite3.connect(db_name) as conn:
        conn.cursor().execute("""CREATE TABLE IF NOT EXISTS TatungForeverEnergy (
                     ID INTEGER PRIMARY KEY AUTOINCREMENT, TIME TEXT, LOCATION TEXT, PG INTEGER, PA INTEGER, PP INTEGER)""")
    print("資料庫確認完畢。")

def insert_database(timestring, location, pg, pa, pp):
    with sqlite3.connect(db_name) as conn:
        conn.cursor().execute("INSERT INTO TatungForeverEnergy(TIME, LOCATION, PG, PA, PP) VALUES(?, ?, ?, ?, ?)",
                      (timestring, location, pg, pa, pp))

# --- Blynk 設定 ---
try:
    blynk = BlynkLib.Blynk(blynk_token)
except Exception as e:
    print(f"Blynk 連線失敗: {e}, 10秒後重啟。"); time.sleep(10); system('reboot')

@blynk.on("V0")
def v0_write_handler(value): global factor_a; factor_a = float(value[0]); print(f'factor_a 更新為: {factor_a}')
@blynk.on("V1")
def v1_write_handler(value): global factor_p; factor_p = float(value[0]); print(f'factor_p 更新為: {factor_p}')
@blynk.on("V3")
def v3_write_handler(value): global pizero2_on; pizero2_on = str(value[0]); print(f'pizero2_on 更新為: {pizero2_on}')
@blynk.on("V9")
def v9_write_handler(value): global pizero2_off; pizero2_off = str(value[0]); print(f'pizero2_off 更新為: {pizero2_off}')

@blynk.on("connected")
def blynk_connected(): print("Blynk 已連接，同步伺服器數值..."); blynk.sync_virtual(0, 1, 3, 9)

# --- 主程式初始化 ---
create_database()
client = connect_mqtt()
default_location = "24.960938,121.247177"
location = locator()
if location is None:
    location = default_location
    print("無法從 1NCE 獲取位置，將使用預設值。")

# --- 主迴圈 ---
while True:
    client.loop_start()
    subscribe(client)
    blynk.run()

    if message and message != message_check:
        print(f"偵測到 {len(message)} 筆新數據，開始處理...")
        
        for data_string in message:
            try:
                sql_data = data_string.split('/')
                insert_database(sql_data[0], location, int(sql_data[1]), int(sql_data[2]), int(sql_data[3]))
            except (IndexError, ValueError): continue
        print("資料庫儲存完畢。")

        # [最終修正] 呼叫函數時，移除多餘的 message_check 參數
        power_read_and_send(message, client, location)
        
        message_check = list(message)

        print(f"處理完成，發送 ACK 確認訊息至主題 '{topic_ack}'")
        client.publish(topic_ack, "OK")
        
        client.publish(topic_pub, f"{pizero2_on}_{pizero2_off}")

    else:
        print("無新數據。")

    client.loop_stop()
    time.sleep(5)