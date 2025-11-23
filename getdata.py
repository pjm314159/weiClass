import requests
import json

def getData(openid):
    url  = "https://v18.teachermate.cn/wechat-api/v1/class-attendance/student/active_signs"
    headers = {
        'User-Agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
        "Openid": openid}
    response = requests.get(url, headers=headers)
    data = json.loads(response.text)
    return data
