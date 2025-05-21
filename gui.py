import os
import sys
import threading
import json
import logging
from datetime import datetime # 用于生成时间戳文件名和显示
import re # 用于清理文件名中的非法字符

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextBrowser, QTextEdit, QPushButton, QLabel, QLineEdit, QComboBox,
    QDialog, QMessageBox, QSpacerItem, QSizePolicy, QListWidget, QListWidgetItem
)
from PySide6.QtGui import QFont, QPixmap, QIcon, QTextCursor
from PySide6.QtCore import Qt, Signal, Slot

# 导入 controller
from controller import Controller

# --- 辅助函数，用于资源路径 ---
def get_asset_path(asset_name):
    """获取资源文件的绝对路径，兼容打包和直接运行"""
    if getattr(sys, 'frozen', False):
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    else:
        # Not frozen, direct execution
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, 'assets', asset_name)

def get_history_path(file_name=""):
    """获取历史记录文件的绝对路径"""
    if getattr(sys, 'frozen', False):
        base_path = os.path.join(sys._MEIPASS, 'history') # 打包后历史记录放在_MEIPASS/history
    else:
        base_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'history')
    os.makedirs(base_path, exist_ok=True) # 确保目录存在
    return os.path.join(base_path, file_name)


# --- 设置窗口 ---
class SettingsDialog(QDialog):
    # 定义一个信号，当设置保存时发射
    settings_saved = Signal(str, str)

    def __init__(self, parent=None, current_api_key="", current_model=""):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setModal(True) # 模态对话框

        # 获取主窗口几何信息以居中
        if parent:
            parent_geo = parent.geometry()
            self.setGeometry(
                parent_geo.x() + (parent_geo.width() - 450) // 2,
                parent_geo.y() + (parent_geo.height() - 200) // 2,
                450, 200
            )
        else:
            self.resize(450, 200)

        layout = QVBoxLayout(self)

        # API Key
        api_layout = QHBoxLayout()
        api_label = QLabel("API密钥：")
        self.api_entry = QLineEdit()
        self.api_entry.setEchoMode(QLineEdit.Password)
        self.api_entry.setText(current_api_key)
        api_layout.addWidget(api_label)
        api_layout.addWidget(self.api_entry)
        layout.addLayout(api_layout)

        # Model Selection
        model_layout = QHBoxLayout()
        model_label = QLabel("选择模型：")
        self.model_combo = QComboBox()
        self.models = ['deepseek-r1-distill-qwen-32b', 'deepseek-r1', 'qwen-plus', 'qwen-max']
        self.model_combo.addItems(self.models)
        if current_model in self.models:
            self.model_combo.setCurrentText(current_model)
        model_layout.addWidget(model_label)
        model_layout.addWidget(self.model_combo)
        layout.addLayout(model_layout)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addSpacerItem(QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum)) # 弹簧

        self.save_button = QPushButton("保存")
        self.save_button.clicked.connect(self.save_settings)

        self.cancel_button = QPushButton("取消")
        self.cancel_button.clicked.connect(self.reject) # QDialog.reject() 会关闭对话框

        button_layout.addWidget(self.save_button)
        button_layout.addWidget(self.cancel_button)
        layout.addLayout(button_layout)

        self.setLayout(layout)

    def save_settings(self):
        api_key = self.api_entry.text().strip()
        selected_model = self.model_combo.currentText()

        if not api_key:
            QMessageBox.warning(self, "警告", "API密钥不能为空！")
            return
        if not selected_model:
            QMessageBox.warning(self, "警告", "请选择有效的模型！")
            return

        # 发射信号，并将数据传递出去
        self.settings_saved.emit(api_key, selected_model)
        self.accept() # QDialog.accept() 会关闭对话框并返回 QDialog.Accepted

    def get_settings(self):
        return self.api_entry.text().strip(), self.model_combo.currentText()

class ChatGUI(QMainWindow):
    # 自定义信号，用于在主线程更新聊天记录
    update_chat_signal = Signal(str, str) # role, message_html

    def __init__(self):
        super().__init__()
        self.api_key = ""
        self.selected_model = ""
        self.dialog_history = [] # 当前会话的对话历史 (纯文本/HTML 格式)
        self._session_id = None  # 用于存储当前会话ID
        self.is_dark_mode = False # 标记当前是否为黑夜模式
        self.current_history_file = None # 存储当前会话对应的历史文件路径，用于保存和更新
        self.is_displaying_historical_chat = False # 标记当前是否在显示历史记录，而非当前会话

        self._load_config()
        self._init_ui()
        self._load_stylesheet() # 加载样式表
        self._connect_signals()

        # 欢迎信息，直接是HTML内容
        self.initial_welcome_message = (
            "<b>我是一个科技金融小助手</b>，很高兴回答你的问题！<br>" # 使用HTML粗体和换行
            "输入 <code>/reset</code> 可以清空对话历史并开始新的会话。<br>" # 使用HTML code标签
            "您可以在左侧的“历史记录”中查看和管理以往的对话。"
        )
        # 初始显示欢迎信息
        self.add_message_to_history("assistant", self.initial_welcome_message)
        self._load_history_list() # 加载左侧历史记录列表


    def _init_ui(self):
        self.setWindowTitle("科技金融小助手")
        try:
            icon_path = get_asset_path('logo.ico')
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
            else:
                logging.warning(f"窗口图标未找到: {icon_path}")
        except Exception as e:
            logging.warning(f"无法加载窗口图标: {e}")

        self.resize(2560, 1440)
        self.showMaximized()

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        self.main_h_layout = QHBoxLayout(main_widget) # 使用QHBoxLayout作为主布局
        self.main_h_layout.setContentsMargins(10, 10, 10, 10)
        self.main_h_layout.setSpacing(10)

        # --- 左侧边栏 (历史记录列表) ---
        self.sidebar_widget = QWidget()
        self.sidebar_widget.setObjectName("sidebar_widget") # 用于QSS
        self.sidebar_widget.setFixedWidth(200) # 设置固定宽度
        self.sidebar_layout = QVBoxLayout(self.sidebar_widget)
        self.sidebar_layout.setContentsMargins(0, 0, 0, 0) # 紧凑布局
        self.sidebar_layout.setSpacing(5)

        sidebar_label = QLabel("历史记录")
        sidebar_label.setAlignment(Qt.AlignCenter)
        sidebar_label.setFont(QFont("微软雅黑", 11, QFont.Bold))
        self.sidebar_layout.addWidget(sidebar_label)

        self.history_list_widget = QListWidget()
        self.history_list_widget.setFont(QFont("微软雅黑", 10))
        self.sidebar_layout.addWidget(self.history_list_widget)

        self.main_h_layout.addWidget(self.sidebar_widget)


        # --- 右侧主内容区 (聊天历史和输入区) ---
        self.chat_area_widget = QWidget()
        self.chat_area_layout = QVBoxLayout(self.chat_area_widget)
        self.chat_area_layout.setContentsMargins(0, 0, 0, 0)
        self.chat_area_layout.setSpacing(10)

        # 聊天历史区
        self.chat_history_view = QTextBrowser()
        self.chat_history_view.setReadOnly(True)
        self.chat_history_view.setFont(QFont("微软雅黑", 12))
        self.chat_history_view.setOpenExternalLinks(True)
        self.chat_area_layout.addWidget(self.chat_history_view, 1) # 占比 1

        # 输入区域
        input_frame = QWidget()
        input_layout = QHBoxLayout(input_frame)
        input_layout.setContentsMargins(0,0,0,0)
        input_layout.setSpacing(5)

        self.user_input_edit = QTextEdit()
        self.user_input_edit.setFont(QFont("微软雅黑", 12))
        self.user_input_edit.setFixedHeight(80)
        self.user_input_edit.setPlaceholderText("在此输入消息，Ctrl+Enter 发送...")
        input_layout.addWidget(self.user_input_edit, 1)

        self.send_button = QPushButton("发送 ✉️")
        self.send_button.setFont(QFont("微软雅黑", 11, QFont.Bold))
        self.send_button.setFixedHeight(self.user_input_edit.height())
        input_layout.addWidget(self.send_button)
        self.chat_area_layout.addWidget(input_frame)

        # 底部按钮区域
        bottom_button_layout = QHBoxLayout()
        bottom_button_layout.addSpacerItem(QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

        self.dark_mode_button = QPushButton("🌙 黑夜模式")
        self.dark_mode_button.setFont(QFont("微软雅黑", 10))
        bottom_button_layout.addWidget(self.dark_mode_button)

        self.settings_button = QPushButton("⚙ 设置")
        self.settings_button.setFont(QFont("微软雅黑", 10))
        bottom_button_layout.addWidget(self.settings_button)

        self.clear_history_button = QPushButton("清空对话") # 改名为“清空对话”
        self.clear_history_button.setFont(QFont("微软雅黑", 10))
        bottom_button_layout.addWidget(self.clear_history_button)

        self.chat_area_layout.addLayout(bottom_button_layout)

        self.main_h_layout.addWidget(self.chat_area_widget, 1) # 右侧主内容区占比 1

    def _connect_signals(self):
        self.send_button.clicked.connect(self.on_send_button_clicked)
        self.user_input_edit.keyPressEvent = self.input_key_press_event # 覆盖 keyPressEvent 实现 Ctrl+Enter
        self.settings_button.clicked.connect(self.show_settings_dialog)
        self.clear_history_button.clicked.connect(lambda: self.handle_user_command("/reset"))
        self.update_chat_signal.connect(self._update_chat_history_slot)
        self.dark_mode_button.clicked.connect(self.toggle_dark_mode)
        self.history_list_widget.itemClicked.connect(self._on_history_item_clicked)


    def _load_config(self):
        try:
            config_path = get_asset_path('config.json')
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    self.api_key = config.get('api_key', '')
                    self.selected_model = config.get('selected_model', '')
                    self.is_dark_mode = config.get('is_dark_mode', False) # 加载黑夜模式状态
                    logging.info(f'成功读取配置文件，api_key: {"*"*5 if self.api_key else ""}, selected_model: {self.selected_model}, is_dark_mode: {self.is_dark_mode}')
            else:
                logging.warning('未找到配置文件 config.json，将使用默认空值。')
        except Exception as e:
            logging.error(f'读取配置文件时出错: {e}')

    def _save_config(self):
        try:
            config_path = get_asset_path('config.json')
            os.makedirs(os.path.dirname(config_path), exist_ok=True) #确保assets目录存在
            with open(config_path, 'w', encoding='utf-8') as f:
                # 配置文件保存 API Key、模型和黑夜模式状态
                json.dump({
                    'api_key': self.api_key,
                    'selected_model': self.selected_model,
                    'is_dark_mode': self.is_dark_mode, # 保存黑夜模式状态
                }, f, indent=4)
            logging.info('配置已保存！')
        except Exception as e:
            logging.error(f'保存配置文件时出错: {e}')
            QMessageBox.critical(self, "错误", f"保存配置失败: {e}")

    def _load_stylesheet(self):
        """根据当前模式加载样式表"""
        stylesheet_path = get_asset_path('dark_mode.qss') if self.is_dark_mode else get_asset_path('light_mode.qss')
        try:
            if os.path.exists(stylesheet_path):
                with open(stylesheet_path, 'r', encoding='utf-8') as f:
                    self.setStyleSheet(f.read())
                logging.info(f"成功加载样式表: {stylesheet_path}")
                # 更新模式按钮文本
                self.dark_mode_button.setText("☀️ 日间模式" if self.is_dark_mode else "🌙 黑夜模式")
            else:
                logging.warning(f"样式表文件未找到: {stylesheet_path}")
                self.setStyleSheet("") # 如果找不到样式表，可以设置一个默认的或者不设置
        except Exception as e:
            logging.error(f"加载样式表时出错: {e}")
            self.setStyleSheet("") # 避免应用崩溃

    def toggle_dark_mode(self):
        """切换黑夜模式"""
        self.is_dark_mode = not self.is_dark_mode
        self._load_stylesheet() # 重新加载样式表
        self._save_config() # 保存当前模式状态
        logging.info(f"黑夜模式状态切换为: {self.is_dark_mode}")

        # 如果当前显示的是历史记录，则重新加载历史记录以应用新的样式
        if self.is_displaying_historical_chat and self.current_history_file:
            self._on_history_item_clicked_refresh(self.current_history_file)
        else:
            # 否则，刷新当前聊天显示
            self.refresh_chat_display()

    def refresh_chat_display(self):
        """刷新聊天历史的显示，使其应用新的样式"""
        # 1. 保存当前滚动位置
        current_scroll_value = self.chat_history_view.verticalScrollBar().value()

        # 2. 清空 QTextBrowser 的内容
        self.chat_history_view.clear()

        # 3. 重新添加欢迎信息
        self.add_message_to_history("assistant", self.initial_welcome_message)

        # 4. 重新添加所有历史对话
        for msg in self.dialog_history:
            if msg['role'] == 'user':
                self.add_message_to_history(msg['role'], f'<p>{msg["content"]}</p>')
            else:
                self.add_message_to_history(msg['role'], msg['content']) # 助手消息假定是HTML格式或可直接渲染

        # 5. 恢复滚动位置
        self.chat_history_view.verticalScrollBar().setValue(current_scroll_value)


    @Slot(str, str)
    def _update_chat_history_slot(self, role, message_html_content):
        """槽函数，在主线程中更新 QTextBrowser"""
        self.chat_history_view.append(message_html_content)
        # 滚动到底部，但保留一点点缓冲，防止太紧凑
        self.chat_history_view.verticalScrollBar().setValue(self.chat_history_view.verticalScrollBar().maximum())


    def add_message_to_history(self, role, message_html_content):
        """处理消息并将其添加到聊天视图中，直接视为HTML进行渲染"""
        user_avatar_path = get_asset_path('user.ico')
        robot_avatar_path = get_asset_path('robot.ico')

        avatar_html = ""
        message_box_class = "user-message-box" if role == 'user' else "assistant-message-box"
        
        # 外层容器，用于控制整体左对齐和消息间距。这里的内联样式是QSS难以替代的布局样式
        message_container_style = "display: flex; align-items: flex-start; margin-bottom: 10px;"
        
        # 头像样式
        avatar_style = "width: 35px; height: 35px; border-radius: 100%; margin-right: 8px; vertical-align: top;"


        if role == 'user':
            if os.path.exists(user_avatar_path):
                # file:/// 协议在Windows上需要双斜杠来表示根目录或驱动器
                avatar_html = f'<img src="file:///{user_avatar_path.replace(os.sep, "/")}" style="{avatar_style}">'
            
            formatted_message = f"""
            <div class="message-container" style="{message_container_style}">
                {avatar_html}
                <div class="{message_box_class}">
                    {message_html_content}
                </div>
            </div>
            """
        else: # assistant
            if os.path.exists(robot_avatar_path):
                avatar_html = f'<img src="file:///{robot_avatar_path.replace(os.sep, "/")}" style="{avatar_style}">'
            
            formatted_message = f"""
            <div class="message-container" style="{message_container_style}">
                {avatar_html}
                <div class="{message_box_class}">
                    {message_html_content}
                </div>
            </div>
            """
        self.update_chat_signal.emit(role, formatted_message)


    def on_send_button_clicked(self):
        user_text = self.user_input_edit.toPlainText().strip()
        if not user_text:
            return

        self.user_input_edit.clear()
        self.handle_user_command(user_text)

    def input_key_press_event(self, event):
        """处理输入框的按键事件，实现 Ctrl+Enter 发送"""
        if event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
            if event.modifiers() == Qt.ControlModifier:
                self.on_send_button_clicked()
                return
        # 调用原始的 keyPressEvent 处理其他按键
        QTextEdit.keyPressEvent(self.user_input_edit, event)


    def handle_user_command(self, text):
        # 如果当前显示的是历史记录，则切换到当前会话模式
        if self.is_displaying_historical_chat:
            self._start_new_current_session()
            self.is_displaying_historical_chat = False # 标记为当前会话

        if text.lower() == '/reset':
            self._save_current_history() # 保存当前会话
            self.dialog_history.clear()
            self._session_id = None  # 清空会话ID，开始新会话
            self.current_history_file = None # 重置当前会话文件
            self.chat_history_view.clear() # 清空 QTextBrowser
            self.add_message_to_history('assistant', self.initial_welcome_message) # 重新添加欢迎信息
            self._load_history_list() # 刷新左侧历史记录列表
            return

        # 确保在第一次用户对话后，为当前会话创建一个历史文件
        if not self.dialog_history or (self.dialog_history and self.dialog_history[0]['role'] == 'assistant' and self.dialog_history[0]['content'] == self.initial_welcome_message):
            # 只有当 dialog_history 是空或者只有欢迎语时才生成新的文件名
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S") # 确保这里包含了时分秒
            self.current_history_file = f"chat_{timestamp}.html"
            logging.info(f"新会话开始，历史文件: {self.current_history_file}")


        self.add_message_to_history('user', f'<p>{text}</p>') # 将用户输入包装成HTML段落进行显示
        self.dialog_history.append({'role': 'user', 'content': text}) # API请求仍然使用纯文本

        # 检查 API key 和 model
        if not self.api_key:
            self.add_message_to_history('assistant', '<p>请先在设置中填写有效的 API 密钥。</p>') # 包装成HTML段落
            return
        if not self.selected_model:
            self.add_message_to_history('assistant', '<p>请先选择有效的模型。</p>') # 包装成HTML段落
            return

        # 在新线程中处理 API 请求
        threading.Thread(target=self._process_api_request_thread, daemon=True).start()

    def _process_api_request_thread(self):
        try:
            # 传递当前的 session_id，如果为 None 则会生成新的
            response_data = Controller.process_api_request(
                self.api_key, self.dialog_history, self.selected_model, self._session_id
            )
            
            answer = response_data.get('text')
            new_session_id = response_data.get('session_id')

            if new_session_id:
                self._session_id = new_session_id # 更新会话ID

            if answer: # 确保有答案
                self.dialog_history.append({'role': 'assistant', 'content': answer}) # 存储原始文本或HTML
                self.add_message_to_history('assistant', answer) # 直接将API返回的answer作为HTML显示

            else: # API返回空或错误信息已在controller处理
                logging.warning("API request returned empty or error message handled by controller.")

        except Exception as e:
            logging.error(f"处理API请求时发生错误: {e}", exc_info=True)
            err_msg = f"<p>请求出错，请稍后再试。错误详情：{e}</p>" # 包装成HTML段落
            self.add_message_to_history('assistant', err_msg)
            # 如果出错，移除最后一条用户消息，防止重复处理 (可选逻辑)
            if self.dialog_history and self.dialog_history[-1]['role'] == 'user':
                self.dialog_history.pop()
        finally:
            # 每次对话结束后，更新当前会话的历史文件
            self._save_current_history()
            self._load_history_list() # 刷新侧边栏以显示更新后的时间（如果标题基于最后对话时间）

    def show_settings_dialog(self):
        # 传入当前的API Key和模型
        dialog = SettingsDialog(self, self.api_key, self.selected_model)
        # 连接对话框的 settings_saved 信号到槽函数
        dialog.settings_saved.connect(self.handle_settings_saved)
        dialog.exec() # 显示为模态对话框

    @Slot(str, str)
    def handle_settings_saved(self, api_key, selected_model):
        """处理从设置对话框保存的设置"""
        self.api_key = api_key
        self.selected_model = selected_model
        self._save_config()
        QMessageBox.information(self, "成功", "设置已保存！")
        if not self.dialog_history: # 如果是首次设置，可以给个提示
             self.add_message_to_history('assistant', '<p>API设置已更新，现在可以开始对话了。</p>') # 包装成HTML段落

    def _get_html_for_history(self, history_data, current_mode):
        """
        根据对话历史数据生成一个完整的HTML页面字符串，包含内联样式。
        history_data: 列表，每个元素是 {'role': ..., 'content': ...}
        current_mode: 'light' or 'dark'，用于设置body的data-mode属性
        """
        # 获取头像路径，注意 file:/// 协议和路径分隔符
        user_avatar_path = get_asset_path('user.ico').replace(os.sep, "/")
        robot_avatar_path = get_asset_path('robot.ico').replace(os.sep, "/")

        # 基本的 HTML 结构，包含两个样式表引用和动态切换的JS
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>聊天记录</title>
            <link rel="stylesheet" href="file:///{get_asset_path('light_mode_history.css').replace(os.sep, '/')}" id="light-mode-style">
            <link rel="stylesheet" href="file:///{get_asset_path('dark_mode_history.css').replace(os.sep, '/')}" id="dark-mode-style" disabled>
            <script>
                document.addEventListener('DOMContentLoaded', function() {{
                    const body = document.body;
                    const lightStyle = document.getElementById('light-mode-style');
                    const darkStyle = document.getElementById('dark-mode-style');
                    
                    const mode = body.getAttribute('data-mode');

                    if (mode === 'dark') {{
                        lightStyle.disabled = true;
                        darkStyle.disabled = false;
                    }} else {{
                        lightStyle.disabled = false;
                        darkStyle.disabled = true;
                    }}
                }});
            </script>
        </head>
        <body data-mode="{current_mode}">
        """
        # 再次添加欢迎信息，确保历史文件也包含它
        html_content += f"""
        <div class="message-container">
            <img src="file:///{robot_avatar_path}" class="avatar">
            <div class="assistant-message-box">
                {self.initial_welcome_message}
            </div>
        </div>
        """

        for msg in history_data:
            role = msg['role']
            content = msg['content'] # 假设 content 已经是或将被包装为 HTML

            avatar_src = user_avatar_path if role == 'user' else robot_avatar_path
            message_box_class = "user-message-box" if role == 'user' else "assistant-message-box"
            
            # 如果是纯文本，确保渲染为HTML段落
            if not content.strip().startswith('<') or not content.strip().endswith('>'):
                content = f'<p>{content}</p>'

            html_content += f"""
            <div class="message-container">
                <img src="file:///{avatar_src}" class="avatar">
                <div class="{message_box_class}">
                    {content}
                </div>
            </div>
            """
        html_content += "</body></html>"
        return html_content

    def _save_current_history(self):
        """保存当前对话历史到文件"""
        if not self.dialog_history or (len(self.dialog_history) == 1 and self.dialog_history[0]['role'] == 'assistant' and self.dialog_history[0]['content'] == self.initial_welcome_message):
            # 如果没有实际对话内容（只有欢迎语），则不保存
            return

        if not self.current_history_file:
            # 如果是在没有历史文件的情况下进行保存 (例如关闭应用时)，则创建一个新的
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            self.current_history_file = f"chat_{timestamp}.html"

        file_path = get_history_path(self.current_history_file)
        
        # 确保 history 目录存在
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        # 传递当前模式给 HTML 生成函数
        html_output = self._get_html_for_history(self.dialog_history, 'dark' if self.is_dark_mode else 'light')
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(html_output)
            logging.info(f"对话历史已保存到: {file_path}")
        except Exception as e:
            logging.error(f"保存对话历史到文件失败: {file_path}, 错误: {e}")

    def _load_history_list(self):
        """加载历史记录列表并显示在左侧边栏"""
        self.history_list_widget.clear() # 清空现有列表项
        history_dir = get_history_path() # 获取历史目录路径
        
        if not os.path.exists(history_dir):
            os.makedirs(history_dir, exist_ok=True)
            return # 目录不存在，无需加载

        history_files = sorted([f for f in os.listdir(history_dir) if f.endswith('.html')], reverse=True)

        for filename in history_files:
            try:
                # 从文件名解析时间戳作为标题
                # 确保这里匹配的是 14 位的完整时间戳
                match = re.match(r'chat_(\d{14})\.html', filename) 
                if match:
                    timestamp_str = match.group(1)
                    # 格式化为可读的时间：年年年年年年年年年年年年年年 年年年年年年年年年年年年年年年年月月月月月月月月月月月月月月日日日日日日日日日日日日日日 时时时时时时分分分分分分秒秒秒秒秒秒
                    display_title = datetime.strptime(timestamp_str, "%Y%m%d%H%M%S").strftime("%Y年%m月%d日 %H:%M:%S")
                    logging.info(f"解析文件名: {filename} -> 显示标题: {display_title}") # 添加日志
                else:
                    display_title = filename # 如果文件名不符合规范，则直接显示文件名
                    logging.warning(f"文件名 {filename} 不符合 chat_YYYYMMDDHHMMSS.html 格式，将直接显示文件名。") # 添加日志

                item = QListWidgetItem(display_title)
                item.setData(Qt.UserRole, filename) # 将文件名存储在UserRole中，方便点击时获取
                self.history_list_widget.addItem(item)
            except Exception as e:
                logging.error(f"加载历史文件 {filename} 失败: {e}", exc_info=True) # 记录完整错误信息

    @Slot(QListWidgetItem)
    def _on_history_item_clicked(self, item):
        """点击历史记录项时显示其内容，并设置为历史显示模式"""
        filename = item.data(Qt.UserRole)
        self._display_historical_chat(filename)
        # 将当前模式的 QSS 注入到加载的 HTML 中（通过data-mode和JS）
        self.is_displaying_historical_chat = True # 标记为正在显示历史记录
        self.current_history_file = filename # 更新当前历史文件指针

    def _on_history_item_clicked_refresh(self, filename):
        """刷新显示当前的（或指定）历史记录，用于模式切换时重绘"""
        self._display_historical_chat(filename)

    def _display_historical_chat(self, filename):
        """核心逻辑：加载并显示指定的历史记录文件"""
        file_path = get_history_path(filename)
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    html_content = f.read()
                
                # 关键：修改加载的HTML，确保其body的data-mode属性与当前应用的模式一致
                # 这将触发JS在QTextBrowser中正确应用CSS
                body_tag_pattern = re.compile(r'<body\s*data-mode=["\'](light|dark)["\']([^>]*)>', re.IGNORECASE)
                current_mode_str = 'dark' if self.is_dark_mode else 'light'
                
                # 替换 HTML 中的 data-mode 属性以匹配当前模式
                if body_tag_pattern.search(html_content):
                    html_content = body_tag_pattern.sub(f'<body data-mode="{current_mode_str}"\\2>', html_content)
                else:
                    # 如果原始HTML没有data-mode属性（不应该发生，但为了健壮性）
                    html_content = html_content.replace('<body>', f'<body data-mode="{current_mode_str}">', 1)

                self.chat_history_view.setHtml(html_content)
                self.chat_history_view.moveCursor(QTextCursor.End) # 滚动到底部
                logging.info(f"已加载历史记录: {filename}，并应用当前模式: {current_mode_str}")
            except Exception as e:
                logging.error(f"加载历史记录文件 {file_path} 失败: {e}", exc_info=True)
                QMessageBox.warning(self, "错误", f"无法加载历史记录: {e}")
        else:
            QMessageBox.warning(self, "错误", f"历史记录文件不存在: {file_path}")

    def _start_new_current_session(self):
        """开始一个新的当前会话，清除历史记录并显示欢迎信息"""
        self._save_current_history() # 保存之前的会话
        self.dialog_history.clear()
        self._session_id = None
        self.current_history_file = None # 重置当前会话文件
        self.is_displaying_historical_chat = False # 切换回当前会话模式
        self.chat_history_view.clear()
        self.add_message_to_history('assistant', self.initial_welcome_message)
        self._load_history_list() # 刷新侧边栏

    def closeEvent(self, event):
        """应用关闭前保存当前对话历史"""
        self._save_current_history() # 确保关闭时保存当前会话
        self._save_config() # 确保关闭时保存黑夜模式状态
        logging.info("应用程序关闭。")
        super().closeEvent(event)