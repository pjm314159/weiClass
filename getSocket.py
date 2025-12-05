import asyncio
import websockets
import json
import logging
from typing import Optional, Callable
import time
logger = logging.getLogger(__name__)


class TeacherMateWebSocketClient:

    def __init__(self, sign_id: int, qr_callback: Optional[Callable] = None):
        self.qr_callback = qr_callback
        self.sign_id = sign_id
        self.client_id = ""
        self.counter = 3
        self.done = asyncio.Event()
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.is_shutting_down = False
        self.wait_time = 1
        self.reconnect_delay = 5
        self.max_reconnect_attempts = 3
        self.reconnect_attempts = 0
        self.receive_task: Optional[asyncio.Task] = None

    async def receive_handler(self) -> None:
        """接收消息处理函数"""
        try:
            async for message in self.websocket:
                if self.is_shutting_down:
                    break

                msg_str = message.decode('utf-8') if isinstance(message, bytes) else message
                logger.debug(f"收到消息: {msg_str}")

                if "qrUrl" in msg_str:
                    await self._handle_qr_message(msg_str)

        except websockets.exceptions.ConnectionClosed:
            if not self.is_shutting_down:
                logger.info("WebSocket连接已关闭")
            self.done.set()
        except Exception as e:
            if not self.is_shutting_down:
                logger.error(f"接收消息错误: {e}")
            self.done.set()

    async def _handle_qr_message(self, message: str) -> None:
        """处理包含二维码URL的消息"""
        try:
            qr_data = json.loads(message)
            if isinstance(qr_data, list) and len(qr_data) > 0:
                qr_code_data = qr_data[0]["data"]
                if qr_code_data["type"]==1:
                    qr_code_url = qr_code_data["qrUrl"]
                    logger.info(f"获取到二维码URL: {qr_code_url[:50]}...")

                    if self.qr_callback and not self.is_shutting_down:
                        self.qr_callback(qr_code_url)
                elif qr_code_data["type"]==3:
                    logger.info("qr_url为空，前方拥挤")
                elif qr_code_data["type"]==2:
                    logger.info(f"检测到关闭信息")
                    await self.graceful_shutdown()
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {e}")
        except KeyError as e:
            logger.error(f"消息格式错误，缺少键: {e}")

    async def start(self) -> None:
        """启动WebSocket客户端，支持重连"""
        while (self.reconnect_attempts < self.max_reconnect_attempts and
               not self.is_shutting_down):

            try:
                await self._connect_and_run()
                break

            except (websockets.exceptions.ConnectionClosed,
                    ConnectionRefusedError,
                    asyncio.TimeoutError) as e:

                self.reconnect_attempts += 1
                if self.reconnect_attempts < self.max_reconnect_attempts and not self.is_shutting_down:
                    logger.warning(f"连接失败，{self.reconnect_delay}秒后重试... ({e})")
                    await asyncio.sleep(self.reconnect_delay)
                else:
                    logger.error(f"达到最大重连次数，放弃连接: {e}")

            except Exception as e:
                if not self.is_shutting_down:
                    logger.error(f"WebSocket客户端意外错误: {e}")
                break

    async def _connect_and_run(self) -> None:
        """连接并运行WebSocket客户端"""
        socket_url = "wss://www.teachermate.com.cn/faye"

        # 连接超时设置
        try:
            self.websocket = await asyncio.wait_for(
                websockets.connect(socket_url),
                timeout=10.0
            )
        except asyncio.TimeoutError:
            logger.error("WebSocket连接超时")
            raise

        logger.info("WebSocket连接建立成功")
        self.reconnect_attempts = 0  # 重置重连计数

        # 启动接收任务
        self.receive_task = asyncio.create_task(self.receive_handler())

        try:
            # 发送订阅消息
            subscribe_msg = f'[{{"channel":"/meta/subscribe","clientId":"{self.client_id}","subscription":"/sign/{self.sign_id}","id":"1"}}]'
            await self.websocket.send(subscribe_msg)
            logger.info(f"已订阅签到通道: {self.sign_id}")

            # 主循环 - 发送心跳
            while not self.done.is_set() and not self.is_shutting_down:
                try:
                    self.counter += 1
                    connect_msg = f'[{{"channel":"/meta/connect","clientId":"{self.client_id}","connectionType":"websocket","id":"{self.counter}"}}]'

                    await asyncio.wait_for(
                        self.websocket.send(connect_msg),
                        timeout=5.0
                    )

                    await asyncio.sleep(self.wait_time)

                except asyncio.TimeoutError:
                    if not self.is_shutting_down:
                        logger.warning("发送心跳超时")
                except websockets.exceptions.ConnectionClosed:
                    break
                except Exception as e:
                    if not self.is_shutting_down:
                        logger.error(f"发送消息错误: {e}")
                    break

        finally:
            # 清理任务
            await self._cleanup_tasks()

    async def _cleanup_tasks(self) -> None:
        """清理任务"""
        if self.receive_task and not self.receive_task.done():
            self.receive_task.cancel()
            try:
                await self.receive_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                if not self.is_shutting_down:
                    logger.error(f"接收任务清理错误: {e}")

        await self.close_connection()

    async def graceful_shutdown(self) -> None:
        """优雅关闭连接"""
        if self.is_shutting_down:
            return

        logger.info(f"开始优雅关闭WebSocket客户端 (sign_id: {self.sign_id})")
        self.is_shutting_down = True
        self.done.set()
        await self._cleanup_tasks()
        logger.info(f"WebSocket客户端已关闭 (sign_id: {self.sign_id})")

    async def close_connection(self) -> None:
        """关闭连接"""
        if self.websocket:
            try:
                await self.websocket.close()
            except Exception as e:
                if not self.is_shutting_down:
                    logger.debug(f"关闭连接时出现预期外错误: {e}")
            finally:
                self.websocket = None