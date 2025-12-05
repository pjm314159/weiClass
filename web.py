from flask import Flask, render_template, jsonify
import ad
from getdata import getData
import asyncio
from getSocket import TeacherMateWebSocketClient
import time
import threading
import os
import logging
import requests
from typing import Optional, List, Dict, Any
import queue
import settings
# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(threadName)s] - %(message)s'
)
logger = logging.getLogger(__name__)


class Pipeline:
    """改进的管道类 - 更健壮和性能优越"""

    def __init__(self, openid: str):
        self.openid = openid
        self.success = 0
        self.result: Optional[str] = None
        self.message: Optional[str] = None
        self.is_running = False
        self.websocket_clients: List[TeacherMateWebSocketClient] = []
        self.asyncio_tasks: List[asyncio.Task] = []
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.shutdown_event = threading.Event()
        self.result_queue = queue.Queue()  # 线程安全的结果队列

    def start(self):
        """启动管道"""
        if self.is_running:
            logger.warning("管道已经在运行中")
            return

        self.is_running = True
        thread = threading.Thread(target=self._run_async, daemon=True, name="PipelineThread")
        thread.start()
        logger.info("管道启动完成")

    def _run_async(self):
        """在新线程中运行异步主函数"""
        try:
            # 创建新的事件循环
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.loop.run_until_complete(self._main_async())
        except Exception as e:
            logger.error(f"异步运行失败: {e}")
        finally:
            self.is_running = False
            if self.loop and not self.loop.is_closed():
                self.loop.close()

    async def _main_async(self):
        """异步主函数"""
        try:
            data = await self.wait_data()

            if isinstance(data, list) and data:
                await self.process_signatures(data)
            else:
                self.message = data if isinstance(data, str) else "未找到有效数据"
                logger.warning(f"数据获取失败: {self.message}")

        except Exception as e:
            logger.error(f"主函数运行失败: {e}")
            self.message = f"处理失败: {str(e)}"
        finally:
            await self.shutdown()

    async def wait_data(self) -> Any:
        """等待获取有效数据"""
        retry_count = 0

        while  not self.shutdown_event.is_set():
            try:
                data = getData(self.openid)
                logger.debug(f"获取到数据: {data}")

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
                elif isinstance(data, dict) and "message" in data:
                    return data["message"]

            except Exception as e:
                logger.error(f"获取数据失败: {e}")

            retry_count += 1
            await asyncio.sleep(1)

        return "获取数据超时或应用正在关闭"

    async def process_signatures(self, data: List[Dict[str, Any]]):
        """处理所有签到任务"""
        tasks = []
        for item in data:
            if item.get("isQR"):  # 只处理二维码签到
                try:
                    task = asyncio.create_task(
                        self.run_websocket_client(
                            sign_id=item["signId"],
                            course_id=item["courseId"]
                        )
                    )
                    self.asyncio_tasks.append(task)
                    tasks.append(task)
                    logger.info(f"创建签到任务: sign_id={item['signId']}")
                except Exception as e:
                    logger.error(f"创建签到任务失败 {item}: {e}")

        if not tasks:
            logger.info("没有需要处理的二维码签到任务")
            return

        # 等待第一个任务完成或所有任务完成
        try:
            done, pending = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_COMPLETED,
                timeout=300  # 5分钟超时
            )

            # 如果有任务完成，检查结果
            for task in done:
                if not task.cancelled() and task.exception() is None:
                    logger.info("至少有一个任务成功完成")
                    # 取消其他任务
                    for pending_task in pending:
                        pending_task.cancel()
                    break

        except asyncio.TimeoutError:
            logger.warning("处理签到任务超时")
            self.message = "处理超时，请重试"

    async def run_websocket_client(self, sign_id: int, course_id: int):
        """运行单个WebSocket客户端"""
        try:
            client_id = ad.creatClientId(sign_id, courseId=course_id)
            client = TeacherMateWebSocketClient(
                sign_id=sign_id,
                qr_callback=self.callback
            )
            client.client_id = client_id
            client.webT = True  # 获取到二维码后自动关闭

            self.websocket_clients.append(client)
            await client.start()

        except asyncio.CancelledError:
            logger.info(f"WebSocket客户端任务被取消: {sign_id}")
        except Exception as e:
            logger.error(f"WebSocket客户端运行失败 {sign_id}: {e}")

    def callback(self, url: str):
        """二维码URL回调函数 - 线程安全版本"""
        try:
            logger.info(f"获取到二维码URL: {url[:50]}...")

            # 使用队列确保线程安全
            self.result_queue.put(url)

            # 在主线程中处理结果
            if self.loop and not self.loop.is_closed():
                asyncio.run_coroutine_threadsafe(
                    self._process_callback_result(url),
                    self.loop
                )

        except Exception as e:
            logger.error(f"回调函数处理失败: {e}")

    async def _process_callback_result(self, url: str):
        """处理回调结果 - 在事件循环线程中执行"""
        try:
            # 获取重定向URL
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 NetType/WIFI MicroMessenger/7.0.20.1781(0x6700143B) WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf2541411) XWEB/16965 Flue"
            }

            # 使用异步HTTP请求（如果需要，可以使用aiohttp替代）
            def sync_request():
                resp = requests.get(url, headers=headers, timeout=10)
                return resp.url

            # 在线程池中执行同步请求
            loop = asyncio.get_event_loop()
            final_url = await loop.run_in_executor(None, sync_request)

            self.result = str(final_url)
            self.success = 1
            self.message = "成功获取二维码"
            logger.info(f"最终重定向URL: {self.result}")

        except Exception as e:
            logger.error(f"处理回调结果失败: {e}")
            self.message = f"处理二维码失败: {str(e)}"

    async def shutdown(self):
        """优雅关闭所有组件"""
        logger.info("开始关闭管道...")
        self.shutdown_event.set()

        # 关闭所有WebSocket连接
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

        # 取消所有异步任务
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

        logger.info("管道关闭完成")

    def get_status(self) -> Dict[str, Any]:
        """获取当前状态"""
        if not self.result_queue.empty():
            try:
                url = self.result_queue.get_nowait()
                # 处理队列中的URL
                if self.loop and not self.loop.is_closed():
                    asyncio.run_coroutine_threadsafe(
                        self._process_callback_result(url),
                        self.loop
                    )
            except queue.Empty:
                pass

        return {
            "success": self.success,
            "message": self.message,
            "qr_url": self.result if self.success == 1 else None
        }


# 全局变量
openid = os.getenv("OPENID")
app = Flask(__name__)
pipeline: Optional[Pipeline] = None


def create_pipeline():
    """创建并启动管道"""
    global pipeline
    if not openid:
        logger.error("未找到OPENID环境变量")
        return

    pipeline = Pipeline(openid)
    pipeline.start()
    logger.info("管道创建并启动成功")

@app.after_request
def add_header(response):
    """
    添加头部信息禁止缓存
    """
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/qr_code')
def qr_code():
    if pipeline is None:
        return jsonify({
            "success": 0,
            "message": "管道未初始化"
        })

    status = pipeline.get_status()
    return jsonify(status)


@app.route('/health')
def health():
    """健康检查端点"""
    if pipeline is None:
        return jsonify({"status": "error", "message": "管道未初始化"}), 500

    return jsonify({
        "status": "healthy",
        "pipeline_running": pipeline.is_running,
        "success": pipeline.success
    })


if __name__ == '__main__':
    # 创建并启动管道
    create_pipeline()

    app.run(
        host='0.0.0.0',
        port=5000,
        debug=False,  # 生产环境设置为False
        threaded=True
    )