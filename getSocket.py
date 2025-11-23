import asyncio
import websockets
import json
import signal
import sys
# from getdata import getData
import requests


class deal:
    def __init__(self, url):
        self.url = url
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 NetType/WIFI MicroMessenger/7.0.20.1781(0x6700143B) WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf2541411) XWEB/16965 Flue"}

    def main(self):
        s = requests.Session()
        response = s.get(self.url, headers=self.headers, verify=False)
        print(response.url)


class TeacherMateWebSocketClient:
    def __init__(self, sign_id, qr_callback=None):
        self.qr_callback = qr_callback
        self.sign_id = sign_id
        self.client_id = ""
        self.counter = 3
        self.done = asyncio.Event()
        self.websocket = None
        self.webT = False
        self.is_shutting_down = False
        self.wait_time = 1
    async def receive_handler(self):
        """接收消息处理函数"""
        try:
            async for message in self.websocket:
                if self.is_shutting_down:
                    break

                msg_str = message.decode('utf-8') if isinstance(message, bytes) else message
                # 检测包含qrUrl的消息
                if "qrUrl" in msg_str:
                    try:
                        qr_data = json.loads(msg_str)
                        if isinstance(qr_data, list) and len(qr_data) > 0:
                            qr_code_url = qr_data[0]["data"]["qrUrl"]
                            # 通过回调函数传输URL
                            if self.qr_callback and not self.is_shutting_down:
                                self.qr_callback(qr_code_url)

                            if self.webT:
                                await self.graceful_shutdown()

                    except json.JSONDecodeError:
                        pass

        except websockets.exceptions.ConnectionClosed:
            self.done.set()
        except Exception as e:
            if not self.is_shutting_down:
                print(f"接收消息错误: {e}")

    async def start(self):
        """启动WebSocket客户端"""
        if self.is_shutting_down:
            return

        socket_url = "wss://www.teachermate.com.cn/faye"

        try:
            # 建立WebSocket连接
            self.websocket = await websockets.connect(socket_url)

            # 启动接收消息的协程
            receive_task = asyncio.create_task(self.receive_handler())

            # 主循环，发送连接消息
            while not self.done.is_set() and not self.is_shutting_down:
                try:
                    self.counter += 1
                    connect_string = f'[{{"channel":"/meta/connect","clientId":"{self.client_id}","connectionType":"websocket","id":"{self.counter}"}}]'

                    await self.websocket.send(connect_string)

                    # 等待5秒后发送下一次连接消息
                    await asyncio.sleep(self.wait_time)

                except websockets.exceptions.ConnectionClosed:
                    break
                except Exception as e:
                    if not self.is_shutting_down:
                        print(f"发送消息错误: {e}")
                    break

            # 等待接收任务完成
            if not receive_task.done():
                receive_task.cancel()
            try:
                await receive_task
            except asyncio.CancelledError:
                pass

        except Exception as e:
            if not self.is_shutting_down:
                print(f"WebSocket连接错误: {e}")
        finally:
            await self.close_connection()

    async def graceful_shutdown(self):
        """优雅关闭连接"""
        print("graceful shutdown")
        self.is_shutting_down = True
        self.done.set()
        await self.close_connection()

    async def close_connection(self):
        """关闭连接"""
        if self.websocket:
            await self.websocket.close()
            self.websocket = None


def signal_handler(signum, frame):
    """信号处理函数"""
    sys.exit(0)


async def main(sign_id, client_id):
    """主函数"""
    # 设置信号处理
    signal.signal(signal.SIGINT, signal_handler)

    client = TeacherMateWebSocketClient(sign_id)
    client.client_id = client_id
    await client.start()


if __name__ == "__main__":
    try:
        sign_id = 3814670
        import ad

        clientId = ad.creatClientId(sign_id, 1447611)
        asyncio.run(main(sign_id=sign_id, client_id=clientId))
        pass
    except KeyboardInterrupt:
        pass