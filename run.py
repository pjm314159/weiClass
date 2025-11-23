import asyncio
import threading
import wx
import time
import os
import signal
import sys
import logging
from typing import Optional, List, Dict, Any
from getdata import getData
from gui import QRDisplayApp
from getSocket import TeacherMateWebSocketClient
from ad import creatClientId
import settings
# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(threadName)s] - %(message)s'
)
logger = logging.getLogger(__name__)


class QRManager:
    """二维码管理器 - 修复对象销毁问题"""

    def __init__(self):
        self.app: Optional[wx.App] = None
        self.frame: Optional[QRDisplayApp] = None
        self.wx_thread: Optional[threading.Thread] = None
        self.asyncio_tasks: List[asyncio.Task] = []
        self.websocket_clients: List[TeacherMateWebSocketClient] = []  # 存储WebSocket客户端
        self.is_shutting_down = False
        self.wx_ready = threading.Event()
        self.shutdown_event = asyncio.Event()
        self._shutdown_called = False  # 防止重复关闭

    def start_wx_app(self) -> None:
        """在单独线程中启动wxPython应用"""

        def run_wx_app():
            try:
                # 禁用 wxPython 的断言对话框
                if hasattr(wx, 'DisableAsserts'):
                    wx.DisableAsserts()

                # 确保在这个线程中创建wx.App
                self.app = wx.App(False)

                self.frame = QRDisplayApp()
                # 传递同步关闭方法，而不是异步方法
                self.frame.set_exit_callback(self.request_shutdown)

                # 标记wx应用已就绪
                self.wx_ready.set()
                logger.info("wxPython应用启动完成")

                self.app.MainLoop()
                logger.info("wxPython应用主循环结束")

            except Exception as e:
                logger.error(f"wxPython应用启动失败: {e}")
                self.wx_ready.set()  # 即使失败也设置事件，避免阻塞
            finally:
                # 确保在退出时清理
                if hasattr(wx, 'EnableAsserts'):
                    wx.EnableAsserts()

        self.wx_thread = threading.Thread(
            target=run_wx_app,
            name="wxMainThread",
            daemon=True
        )
        self.wx_thread.start()

        # 等待wx应用初始化完成
        if not self.wx_ready.wait(timeout=10):
            logger.error("wxPython应用启动超时")
            raise RuntimeError("wxPython应用启动超时")

    def request_shutdown(self):
        """同步方法：请求关闭应用（从GUI线程调用）"""
        if self._shutdown_called:
            return

        self._shutdown_called = True
        logger.info("收到GUI关闭请求")

        # 设置关闭事件，让主循环知道需要关闭
        self.shutdown_event.set()

    def register_asyncio_task(self, task: asyncio.Task) -> None:
        """注册asyncio任务用于统一管理"""
        if not self.is_shutting_down:
            self.asyncio_tasks.append(task)

    def register_websocket_client(self, client: TeacherMateWebSocketClient) -> None:
        """注册WebSocket客户端用于统一管理"""
        if not self.is_shutting_down:
            self.websocket_clients.append(client)

    def update_qr_code(self, qr_url: str) -> None:
        """线程安全地更新二维码显示"""
        if self.is_shutting_down or not self.wx_ready.is_set():
            return

        def update_in_main_thread():
            # 检查frame是否仍然有效
            if (self.frame and
                    hasattr(self.frame, 'set_qr_url') and
                    not self.is_shutting_down and
                    not self.frame.is_closing):
                try:
                    self.frame.set_qr_url(qr_url)
                except Exception as e:
                    logger.error(f"更新二维码失败: {e}")

        # 使用wx线程安全的方式调用
        try:
            if wx.IsMainThread():
                update_in_main_thread()
            else:
                wx.CallAfter(update_in_main_thread)
        except Exception as e:
            logger.error(f"调用GUI更新失败: {e}")

    def show_error_message(self, title: str, message: str) -> None:
        """显示错误消息对话框 - 修复对象销毁问题"""
        if not self.wx_ready.is_set() or self.is_shutting_down:
            logger.error(f"{title}: {message}")
            return

        def show_dialog():
            try:
                # 检查frame是否仍然有效
                if not self.frame or self.frame.is_closing:
                    logger.warning(f"无法显示错误对话框，GUI已关闭: {title} - {message}")
                    return

                dlg = wx.MessageDialog(
                    self.frame,
                    message,
                    title,
                    wx.OK | wx.ICON_ERROR
                )
                dlg.ShowModal()
                dlg.Destroy()
            except Exception as e:
                # 如果frame已被销毁，只记录警告而不是错误
                if "wrapped C/C++ object of type QRDisplayApp has been deleted" in str(e):
                    logger.warning(f"GUI已关闭，无法显示错误对话框: {title} - {message}")
                else:
                    logger.error(f"显示错误对话框失败: {e}")

        if wx.IsMainThread():
            show_dialog()
        else:
            wx.CallAfter(show_dialog)

    async def shutdown(self) -> None:
        """异步方法：优雅关闭所有组件"""
        if self.is_shutting_down:
            return

        self.is_shutting_down = True
        logger.info("开始关闭应用...")

        # 首先关闭所有WebSocket连接
        if self.websocket_clients:
            logger.info(f"正在关闭 {len(self.websocket_clients)} 个WebSocket连接...")
            shutdown_tasks = []
            for client in self.websocket_clients:
                if not client.is_shutting_down:
                    shutdown_tasks.append(client.graceful_shutdown())

            if shutdown_tasks:
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*shutdown_tasks, return_exceptions=True),
                        timeout=5.0
                    )
                    logger.info("所有WebSocket连接已关闭")
                except asyncio.TimeoutError:
                    logger.warning("部分WebSocket连接关闭超时")
                except Exception as e:
                    logger.error(f"关闭WebSocket连接时出错: {e}")

        # 然后取消所有异步任务
        for task in self.asyncio_tasks:
            if not task.done():
                task.cancel()

        # 等待任务结束（带超时）
        if self.asyncio_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self.asyncio_tasks, return_exceptions=True),
                    timeout=5.0
                )
            except asyncio.TimeoutError:
                logger.warning("部分任务关闭超时，强制结束")
            except Exception as e:
                logger.error(f"关闭任务时出错: {e}")

        # 最后关闭wx应用
        if self.app and self.wx_ready.is_set():
            def close_wx_app():
                try:
                    if self.frame and not self.frame.is_closing:
                        self.frame.Close(True)
                    if self.app:
                        self.app.ExitMainLoop()
                except Exception as e:
                    logger.error(f"关闭wx应用时出错: {e}")

            try:
                if wx.IsMainThread():
                    close_wx_app()
                else:
                    wx.CallAfter(close_wx_app)
            except Exception as e:
                logger.error(f"调用wx关闭时出错: {e}")

        logger.info("应用关闭完成")

    async def wait_for_shutdown(self) -> None:
        """等待关闭信号"""
        await self.shutdown_event.wait()


async def run_websocket_client(sign_id: int, client_id: str, qr_manager: QRManager) -> None:
    """运行单个WebSocket客户端"""
    try:
        # 等待关闭信号或wx应用就绪
        while not qr_manager.wx_ready.is_set() and not qr_manager.is_shutting_down:
            await asyncio.sleep(0.1)

        if qr_manager.is_shutting_down:
            return

        logger.info(f"启动WebSocket客户端 for sign_id: {sign_id}")

        client = TeacherMateWebSocketClient(
            sign_id=sign_id,
            qr_callback=qr_manager.update_qr_code
        )
        client.client_id = client_id

        # 注册WebSocket客户端到管理器
        qr_manager.register_websocket_client(client)

        await client.start()

    except asyncio.CancelledError:
        logger.info(f"WebSocket客户端任务被取消: {sign_id}")
    except Exception as e:
        logger.error(f"WebSocket客户端运行失败 {sign_id}: {e}")


async def wait_for_data(openid: str, qr_manager: QRManager) -> Optional[List[Dict[str, Any]]]:
    """等待获取有效数据"""
    max_retries = 60  # 最多重试60次
    retry_count = 0

    while retry_count < max_retries and not qr_manager.is_shutting_down:
        try:
            data = getData(openid)
            print(data)
            logger.debug(f"获取到数据: {data}")

            # 处理返回字典的情况（错误信息）
            if isinstance(data, dict):
                error_message = data.get("message", "未知错误")
                logger.error(f"获取数据时发生错误: {error_message}")

                # 显示错误消息给用户
                qr_manager.show_error_message("获取数据失败", error_message)

                # 返回特殊标记表示错误
                return {"error": True, "message": error_message}

            # 处理返回列表的情况（正常数据）
            if data and isinstance(data, list) and len(data) > 0:
                result = []
                for item in data:
                    if all(key in item for key in ["courseId", "signId", "isQR", "isGPS"]):
                        result.append({
                            "courseId": item["courseId"],
                            "signId": item["signId"],
                            "isQR": item["isQR"],
                            "isGPS": item["isGPS"]
                        })
                if result:
                    return result

        except Exception as e:
            logger.error(f"获取数据失败: {e}")

        retry_count += 1
        await asyncio.sleep(1)

    logger.warning("获取数据超时或应用正在关闭")
    return None


async def main_async() -> None:
    """主异步函数"""
    logger.info("应用启动中...")

    # 创建全局管理器
    qr_manager = QRManager()

    try:
        # 启动wx应用
        qr_manager.start_wx_app()

        # 获取环境变量
        openid = os.getenv("OPENID")
        if not openid:
            error_msg = "未找到OPENID环境变量，请检查环境配置"
            logger.error(error_msg)
            qr_manager.show_error_message("配置错误", error_msg)
            await asyncio.sleep(2)  # 给用户时间阅读错误消息
            await qr_manager.shutdown()
            return

        # 等待数据
        data = await wait_for_data(openid, qr_manager)

        # 检查是否返回了错误信息
        if isinstance(data, dict) and data.get("error"):
            # 错误信息已经在 wait_for_data 中显示给用户
            logger.info("由于错误信息，准备关闭应用")
            await asyncio.sleep(2)  # 给用户时间阅读错误消息
            await qr_manager.shutdown()
            return

        if not data or qr_manager.is_shutting_down:
            logger.info("未找到有效数据或应用正在关闭")
            await qr_manager.shutdown()
            return

        # 为每个签到创建WebSocket客户端任务
        tasks = []
        for item in data:
            if item.get("isQR"):  # 只处理二维码签到
                try:
                    client_id = creatClientId(item["signId"], courseId=item["courseId"])
                    task = asyncio.create_task(
                        run_websocket_client(
                            sign_id=item["signId"],
                            client_id=client_id,
                            qr_manager=qr_manager
                        )
                    )
                    qr_manager.register_asyncio_task(task)
                    tasks.append(task)
                    logger.info(f"创建签到任务: sign_id={item['signId']}")
                except Exception as e:
                    logger.error(f"创建签到任务失败 {item}: {e}")

        if not tasks:
            logger.info("没有需要处理的二维码签到任务")
            await qr_manager.shutdown()
            return

        # 等待所有任务完成或关闭信号
        done, pending = await asyncio.wait(
            [asyncio.create_task(qr_manager.wait_for_shutdown())] + tasks,
            return_when=asyncio.FIRST_COMPLETED
        )

        # 如果是因为关闭信号触发的，执行关闭流程
        if qr_manager.shutdown_event.is_set():
            await qr_manager.shutdown()

    except KeyboardInterrupt:
        logger.info("用户中断操作")
        await qr_manager.shutdown()
    except Exception as e:
        logger.error(f"主函数运行失败: {e}")
        error_msg = f"应用运行出错: {str(e)}"
        qr_manager.show_error_message("运行错误", error_msg)
        await asyncio.sleep(2)  # 给用户时间阅读错误消息
        await qr_manager.shutdown()


def signal_handler(signum, frame):
    """信号处理函数"""
    logger.info(f"接收到信号 {signum}，开始关闭应用...")
    sys.exit(0)


def main() -> None:
    """主函数入口"""
    # 设置信号处理
    signal.signal(signal.SIGINT, signal_handler)
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, signal_handler)

    try:
        # 运行异步主函数
        asyncio.run(main_async())
    except KeyboardInterrupt:
        logger.info("应用被用户中断")
    except Exception as e:
        logger.error(f"应用运行失败: {e}")
    finally:
        logger.info("应用退出")


if __name__ == "__main__":
    main()