import wx
import qrcode
import threading
from io import BytesIO
from datetime import datetime
import asyncio


class QRDisplayApp(wx.Frame):
    def __init__(self, qr_url=None):
        super(QRDisplayApp, self).__init__(None, title="二维码展示器", size=(400, 500))
        self.current_url = qr_url
        self.threads = []  # 存储所有线程
        self.is_closing = False  # 关闭标志

        self.init_ui()
        self.Centre()
        self.Show()
        self.exit_callback = None  # 退出回调函数

        if self.current_url:
            self.update_qr_display()

    def set_exit_callback(self, callback):
        """设置退出回调函数"""
        self.exit_callback = callback

    def register_thread(self, thread):
        """注册线程以便管理"""
        if not self.is_closing:
            self.threads.append(thread)

    def set_qr_url(self, qr_url):
        """设置二维码URL接口 - 主更新方法"""
        if not self.is_closing:
            self.current_url = qr_url
            self.update_qr_display()

    def init_ui(self):
        """初始化用户界面"""
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # 标题
        title = wx.StaticText(panel, label="二维码展示", style=wx.ALIGN_CENTER)
        title_font = wx.Font(14, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        title.SetFont(title_font)
        main_sizer.Add(title, 0, wx.ALL | wx.EXPAND, 15)

        # 二维码显示区域
        display_sizer = wx.FlexGridSizer(2, 1, 10, 10)
        display_sizer.AddGrowableCol(0)
        display_sizer.AddGrowableRow(0)

        self.qr_panel = wx.Panel(panel, style=wx.SIMPLE_BORDER)
        self.qr_panel.SetBackgroundColour("white")
        self.qr_panel.SetMinSize((300, 300))

        self.qr_bitmap = wx.StaticBitmap(self.qr_panel)

        qr_inner_sizer = wx.BoxSizer(wx.VERTICAL)
        qr_inner_sizer.Add(self.qr_bitmap, 1, wx.ALL | wx.EXPAND, 10)
        self.qr_panel.SetSizer(qr_inner_sizer)

        display_sizer.Add(self.qr_panel, 1, wx.EXPAND)

        # 信息显示区域
        info_sizer = wx.BoxSizer(wx.VERTICAL)

        self.url_label = wx.StaticText(panel, label="当前URL: 无")
        info_sizer.Add(self.url_label, 0, wx.ALL | wx.EXPAND, 5)

        self.time_label = wx.StaticText(panel, label="更新时间: 未更新")
        info_sizer.Add(self.time_label, 0, wx.ALL | wx.EXPAND, 5)

        display_sizer.Add(info_sizer, 0, wx.EXPAND)
        main_sizer.Add(display_sizer, 1, wx.ALL | wx.EXPAND, 10)

        panel.SetSizer(main_sizer)

        # 绑定窗口事件
        self.Bind(wx.EVT_SIZE, self.on_resize)
        self.Bind(wx.EVT_SHOW, self.on_show)
        self.Bind(wx.EVT_CLOSE, self.onExit)

        # 初始布局
        wx.CallLater(100, self.fit_content)

    def on_resize(self, event):
        """窗口大小变化事件"""
        event.Skip()
        self.fit_content()

    def on_show(self, event):
        """窗口显示事件"""
        event.Skip()
        wx.CallLater(100, self.fit_content)

    def fit_content(self):
        """调整内容以适应窗口大小"""
        self.Layout()
        self.Refresh()

    def generate_qr_bitmap(self, data):
        """生成二维码位图"""
        try:
            if not data:
                return None

            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=8,
                border=4,
            )
            qr.add_data(data)
            qr.make(fit=True)

            img = qr.make_image(fill_color="black", back_color="white")

            # 转换为wx.Bitmap
            buffer = BytesIO()
            img.save(buffer, format='PNG')
            buffer.seek(0)

            image = wx.Image(buffer)
            return wx.Bitmap(image)
        except Exception as e:
            print(f"生成二维码时出错: {e}")
            return None

    def update_qr_display(self):
        """更新二维码显示"""
        if not self.current_url or self.is_closing:
            return

        def generate_worker():
            """在后台线程中生成二维码"""
            if not self.is_closing:
                bitmap = self.generate_qr_bitmap(self.current_url)
                if not self.is_closing:
                    wx.CallAfter(self._apply_qr_bitmap, bitmap)

        # 启动后台线程生成二维码
        thread = threading.Thread(target=generate_worker, daemon=True)
        self.register_thread(thread)
        thread.start()

    def _apply_qr_bitmap(self, bitmap):
        """在主线程中应用二维码位图"""
        if bitmap and not self.is_closing:
            # 获取显示区域可用大小
            qr_panel_size = self.qr_panel.GetSize()
            display_size = min(qr_panel_size.x - 20, qr_panel_size.y - 20)
            display_size = max(display_size, 200)  # 最小200像素

            # 缩放位图以适应显示区域
            image = bitmap.ConvertToImage()
            image = image.Scale(display_size, display_size, wx.IMAGE_QUALITY_HIGH)
            scaled_bitmap = wx.Bitmap(image)

            self.qr_bitmap.SetBitmap(scaled_bitmap)
            self.qr_panel.Layout()

            # 更新信息显示
            display_url = self.current_url[:50] + "..." if len(self.current_url) > 50 else self.current_url
            self.url_label.SetLabel(f"当前URL: {display_url}")

            current_time = datetime.now().strftime("%H:%M:%S")
            self.time_label.SetLabel(f"更新时间: {current_time}")

            self.fit_content()

    def stop_all_threads(self):
        """停止所有线程"""
        self.is_closing = True
        # 停止所有注册的线程
        for thread in self.threads:
            if thread.is_alive():
                # 对于守护线程，通常不需要手动停止
                pass

    def onExit(self, event):
        """关闭窗口事件"""
        # 停止所有线程
        self.stop_all_threads()

        # 调用退出回调
        if self.exit_callback:
            self.exit_callback()

        # 销毁窗口
        self.Destroy()