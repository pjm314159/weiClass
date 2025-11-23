import wx
import qrcode
import threading
import logging
import math
from io import BytesIO
from datetime import datetime
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class QRDisplayApp(wx.Frame):
    """二维码显示应用 - 修复缩放失真问题"""

    def __init__(self, qr_url: Optional[str] = None):
        # 使用更简单的父类初始化
        wx.Frame.__init__(self, None, title="二维码展示器", size=(450, 550))
        self.current_url = qr_url
        self.is_closing = False
        self.exit_callback: Optional[Callable] = None
        self.qr_generation_lock = threading.Lock()
        self.original_bitmap: Optional[wx.Bitmap] = None  # 存储原始二维码位图
        self.original_size = (300, 300)  # 原始二维码大小

        self.init_ui()
        self.Centre()
        self.Show()

        if self.current_url:
            self.update_qr_display()

        logger.info("GUI初始化完成")

    def set_exit_callback(self, callback: Callable) -> None:
        """设置退出回调函数"""
        self.exit_callback = callback

    def init_ui(self) -> None:
        """初始化用户界面"""
        panel = wx.Panel(self)

        # 使用更简单的布局
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # 标题
        title = wx.StaticText(panel, label="签到码")
        title_font = wx.Font(16, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        title.SetFont(title_font)
        main_sizer.Add(title, 0, wx.ALL | wx.ALIGN_CENTER, 15)

        # 二维码显示区域 - 使用StaticBox提供更好的视觉效果
        qr_box = wx.StaticBox(panel, label="二维码")
        qr_box_sizer = wx.StaticBoxSizer(qr_box, wx.VERTICAL)

        self.qr_panel = wx.Panel(qr_box)
        self.qr_panel.SetBackgroundColour("white")
        self.qr_panel.SetMinSize((350, 350))  # 设置最小大小

        # 创建垂直布局，使二维码居中显示
        self.qr_sizer = wx.BoxSizer(wx.VERTICAL)
        self.qr_bitmap = wx.StaticBitmap(self.qr_panel)
        self.qr_sizer.Add(self.qr_bitmap, 1, wx.ALL | wx.ALIGN_CENTER, 10)
        self.qr_panel.SetSizer(self.qr_sizer)

        qr_box_sizer.Add(self.qr_panel, 1, wx.ALL | wx.EXPAND, 10)

        # 信息显示区域
        info_box = wx.StaticBox(panel, label="信息")
        info_box_sizer = wx.StaticBoxSizer(info_box, wx.VERTICAL)

        self.url_label = wx.StaticText(info_box, label="当前URL: 无")
        self.time_label = wx.StaticText(info_box, label="更新时间: 未更新")

        info_font = wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
        self.url_label.SetFont(info_font)
        self.time_label.SetFont(info_font)

        info_box_sizer.Add(self.url_label, 0, wx.ALL | wx.EXPAND, 5)
        info_box_sizer.Add(self.time_label, 0, wx.ALL | wx.EXPAND, 5)

        # 布局
        main_sizer.Add(qr_box_sizer, 1, wx.ALL | wx.EXPAND, 10)
        main_sizer.Add(info_box_sizer, 0, wx.ALL | wx.EXPAND, 10)
        panel.SetSizer(main_sizer)

        # 绑定事件
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.Bind(wx.EVT_SIZE, self.on_resize)
        self.Bind(wx.EVT_MAXIMIZE, self.on_resize)

    def on_resize(self, event: wx.Event) -> None:
        """窗口大小变化事件"""
        event.Skip()
        # 延迟调整大小，避免频繁调整
        wx.CallLater(100, self._resize_qr_bitmap)

    def _resize_qr_bitmap(self) -> None:
        """调整二维码位图大小 - 保持比例和质量"""
        try:
            if not self.original_bitmap or not self.original_bitmap.IsOk():
                return

            # 获取显示区域可用大小
            qr_panel_size = self.qr_panel.GetClientSize()
            if qr_panel_size.width <= 0 or qr_panel_size.height <= 0:
                return

            # 计算保持比例的最大尺寸
            max_width = qr_panel_size.width - 40  # 减去边距
            max_height = qr_panel_size.height - 40

            # 计算保持原始比例的目标尺寸
            original_width, original_height = self.original_size
            width_ratio = max_width / original_width
            height_ratio = max_height / original_height

            # 使用较小的比例，确保完全显示
            scale_ratio = min(width_ratio, height_ratio, 1.5)  # 限制最大缩放比例，避免过度放大

            # 计算目标尺寸
            target_width = int(original_width * scale_ratio)
            target_height = int(original_height * scale_ratio)

            # 确保最小尺寸
            target_width = max(target_width, 200)
            target_height = max(target_height, 200)

            # 高质量缩放
            image = self.original_bitmap.ConvertToImage()
            if image.IsOk():
                # 使用高质量缩放算法
                image = image.Scale(target_width, target_height, wx.IMAGE_QUALITY_HIGH)
                scaled_bitmap = wx.Bitmap(image)

                if scaled_bitmap.IsOk():
                    self.qr_bitmap.SetBitmap(scaled_bitmap)
                    self.qr_panel.Layout()

        except Exception as e:
            logger.error(f"调整二维码大小失败: {e}")

    def set_qr_url(self, qr_url: str) -> None:
        """设置二维码URL - 主线程安全"""
        if self.is_closing:
            return

        self.current_url = qr_url
        self.update_qr_display()

    def update_qr_display(self) -> None:
        """更新二维码显示 - 使用后台线程生成"""
        if not self.current_url or self.is_closing:
            return

        # 如果已经有线程在运行，跳过新的生成
        if self.qr_generation_lock.locked():
            return

        def generate_in_thread():
            """在后台线程中生成二维码"""
            if self.is_closing:
                return

            try:
                with self.qr_generation_lock:
                    bitmap = self.generate_qr_bitmap(self.current_url)
                    if bitmap and bitmap.IsOk() and not self.is_closing:
                        # 保存原始位图
                        self.original_bitmap = bitmap
                        # 在主线程中应用
                        wx.CallAfter(self._apply_qr_bitmap, bitmap)
            except Exception as e:
                logger.error(f"二维码生成线程错误: {e}")

        thread = threading.Thread(target=generate_in_thread, daemon=True)
        thread.start()

    def generate_qr_bitmap(self, data: str) -> Optional[wx.Bitmap]:
        """生成高质量二维码位图"""
        try:
            if not data:
                return None

            # 使用更高的版本和更大的box_size生成更清晰的二维码
            qr = qrcode.QRCode(
                version=5,  # 更高的版本支持更多数据
                error_correction=qrcode.constants.ERROR_CORRECT_M,  # 中等纠错级别
                box_size=12,  # 更大的box_size提高分辨率
                border=4,  # 更大的边框
            )
            qr.add_data(data)
            qr.make(fit=True)

            # 生成高质量图像
            img = qr.make_image(
                fill_color="black",
                back_color="white",
                image_factory=None  # 使用默认图像工厂
            )

            # 转换为wx.Bitmap
            buffer = BytesIO()
            img.save(buffer, format='PNG', optimize=True)
            buffer.seek(0)

            # 使用推荐的 wx.Image 构造函数
            image = wx.Image(buffer, type=wx.BITMAP_TYPE_PNG)
            if not image.IsOk():
                return None

            # 记录原始尺寸
            self.original_size = (image.GetWidth(), image.GetHeight())

            return wx.Bitmap(image)

        except Exception as e:
            logger.error(f"生成二维码失败: {e}")
            return None

    def _apply_qr_bitmap(self, bitmap: wx.Bitmap) -> None:
        """在主线程中应用二维码位图"""
        if not bitmap or not bitmap.IsOk() or self.is_closing:
            return

        try:
            # 直接设置位图，后续通过_resize_qr_bitmap调整大小
            self.qr_bitmap.SetBitmap(bitmap)

            # 更新信息显示
            if self.current_url:
                display_url = (self.current_url[:50] + "...") if len(self.current_url) > 50 else self.current_url
                self.url_label.SetLabel(f"当前URL: {display_url}")

            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.time_label.SetLabel(f"更新时间: {current_time}")

            # 延迟调整大小，确保布局已完成
            wx.CallLater(150, self._resize_qr_bitmap)

        except Exception as e:
            logger.error(f"应用二维码位图失败: {e}")

    def on_close(self, event: wx.Event) -> None:
        """关闭窗口事件 - 修复异步调用问题"""
        logger.info("开始关闭GUI...")
        self.is_closing = True

        if self.exit_callback:
            try:
                # 现在调用的是同步方法，不需要等待
                self.exit_callback()
            except Exception as e:
                logger.error(f"退出回调执行失败: {e}")

        event.Skip()  # 允许默认的关闭行为
        logger.info("GUI关闭完成")