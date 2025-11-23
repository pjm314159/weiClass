import asyncio
import threading
import wx
import time
import settings
import os
import signal
import sys
from getdata import getData
from gui import QRDisplayApp
from getSocket import TeacherMateWebSocketClient
from ad import creatClientId


class QRManager:
    def __init__(self):
        self.app = None
        self.frame = None
        self.wx_thread = None
        self.asyncio_tasks = []
        self.is_shutting_down = False
        self.loop = None
        self.start_wx_app()

    def start_wx_app(self):
        """启动wxPython应用"""

        def run_app():
            self.app = wx.App(False)
            self.frame = QRDisplayApp()
            # 设置退出回调
            self.frame.set_exit_callback(self.shutdown)
            self.app.MainLoop()

        self.wx_thread = threading.Thread(target=run_app, daemon=True)
        self.wx_thread.start()

    def register_asyncio_task(self, task):
        """注册asyncio任务"""
        if not self.is_shutting_down:
            self.asyncio_tasks.append(task)

    def update_qr_code(self, qr_url):
        """更新二维码显示"""
        if self.frame and hasattr(self.frame, 'set_qr_url') and not self.is_shutting_down:
            wx.CallAfter(self.frame.set_qr_url, qr_url)

    def shutdown(self):
        """关闭所有线程和任务"""
        if self.is_shutting_down:
            return

        self.is_shutting_down = True
        print("正在关闭应用...")

        # 停止所有asyncio任务
        for task in self.asyncio_tasks:
            if not task.done():
                task.cancel()

        # 停止wxPython应用
        if self.app:
            wx.CallAfter(self.app.ExitMainLoop)

        # 强制退出（如果必要）
        def force_exit():
            time.sleep(2)
            os._exit(0)

        # 设置强制退出定时器
        exit_thread = threading.Thread(target=force_exit, daemon=True)
        exit_thread.start()


async def run_websocket_client(sign_id, client_id, qr_manager):
    """运行单个WebSocket客户端"""
    # 创建WebSocket客户端并传入回调函数
    client = TeacherMateWebSocketClient(
        sign_id=sign_id,
        qr_callback=qr_manager.update_qr_code
    )
    client.client_id = client_id

    # 等待界面初始化完成
    while not qr_manager.frame and not qr_manager.is_shutting_down:
        await asyncio.sleep(0.1)

    if not qr_manager.is_shutting_down:
        await client.start()


def waitData(openid, qr_manager):
    data = []
    result = []
    while not data and not (qr_manager and qr_manager.is_shutting_down):
        data = getData(openid)
        print(data)
        time.sleep(1)

    if qr_manager and qr_manager.is_shutting_down:
        return None

    if type(data) is dict:
        return None
    for i in data:
        result.append({"courseId": i["courseId"], "signId": i["signId"], "isQR": i["isQR"], "isGPS": i["isGPS"]})
    return result


def signal_handler(signum, frame):
    """信号处理函数"""
    print("接收到关闭信号...")
    sys.exit(0)


async def main_async():
    """主异步函数"""
    # 创建全局管理器
    qr_manager = QRManager()

    try:
        openid = os.getenv("OPENID")
        data = waitData(openid, qr_manager)

        if data and not qr_manager.is_shutting_down:
            # 为每个签到创建任务
            tasks = []
            for i in data:
                clientId = creatClientId(i["signId"], courseId=i["courseId"])
                task = asyncio.create_task(
                    run_websocket_client(sign_id=i["signId"], client_id=clientId, qr_manager=qr_manager)
                )
                qr_manager.register_asyncio_task(task)
                tasks.append(task)

            # 等待所有任务完成
            await asyncio.gather(*tasks, return_exceptions=True)
        else:
            print("未找到有效数据或应用正在关闭")

    except KeyboardInterrupt:
        print("用户中断操作")
    except Exception as e:
        print(f"发生错误: {e}")
    finally:
        if qr_manager:
            qr_manager.shutdown()


def main():
    """主函数"""
    # 设置信号处理
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 运行异步主函数
    asyncio.run(main_async())


if __name__ == "__main__":
    main()