from flask import Flask,render_template,jsonify
import ad
from getdata import getData
import asyncio
from getSocket import TeacherMateWebSocketClient
import time
from threading import Thread
import os
import settings
import requests

class Pipline:
    def __init__(self,openid):
        self.openid = openid
        self.success = 0
        self.result = None
        self.message = None
    def main(self):
        data = self.waitData()
        if type(data) is list:
            for i in data:
                asyncio.run(self.run(i["signId"],i["courseId"]))
        else:
            self.message = data
        if self.result:
            self.success = 1
            self.message = "find data"
            # print(self.result)
        else:
            self.message = data
            print("error")

    def waitData(self):
        data = []
        result = []
        while not data:
            data = getData(self.openid)
            time.sleep(1)
        if type(data) is dict:
            return data["message"]
        elif type(data) is list:
            for i in data:
                result.append({"courseId": i["courseId"], "signId": i["signId"], "isQR": i["isQR"], "isGPS": i["isGPS"]})
        else:
            print(data)
        return result
    async def run(self,signId,courseId):
        clientId = ad.creatClientId(signId, courseId=courseId)
        client = TeacherMateWebSocketClient(
        signId,
        qr_callback =  self.callback                               )
        client.client_id = clientId
        client.webT = True
        await client.start()
    def callback(self,url):
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 NetType/WIFI MicroMessenger/7.0.20.1781(0x6700143B) WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf2541411) XWEB/16965 Flue"}
        resp = requests.get(url,headers=headers)
        self.result = resp.url


openid = os.getenv("OPENID")
app = Flask(__name__)
p = Pipline(openid)

@app.route('/')
def index():
    return render_template('index.html')
@app.route('/qr_code')
def qr_code():
    message = {"success": 0,"message":p.message}
    if p.success == 1:
        message["qr_url"] = p.result
        message["success"] = p.success
        message["message"] = p.message
    elif p.success == 0:
        message["message"] = p.message
    return jsonify(message)



if __name__ == '__main__':
    t = Thread(target=p.main)
    t.start()
    app.run()