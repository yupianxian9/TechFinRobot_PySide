import os
import sys
import threading
import json
import logging
from datetime import datetime
import re

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextBrowser, QTextEdit, QPushButton, QLabel, QLineEdit, QComboBox,
    QDialog, QMessageBox, QSpacerItem, QSizePolicy, QListWidget, QListWidgetItem
)
from PySide6.QtGui import QFont, QPixmap, QIcon, QTextCursor
from PySide6.QtCore import Qt, Signal, Slot, QSize

# 导入 controller
from controller import Controller

# --- 辅助函数，用于资源路径 ---
def get_asset_path(asset_name):
    """获取资源文件的绝对路径，兼容打包和直接运行"""
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, 'assets', asset_name)

def get_history_path(file_name=""):
    """获取历史记录文件的绝对路径"""
    if getattr(sys, 'frozen', False):
        base_path = os.path.join(sys._MEIPASS, 'history')
    else:
        base_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'history')
    os.makedirs(base_path, exist_ok=True)
    return os.path.join(base_path, file_name)


# --- 设置窗口 ---
class SettingsDialog(QDialog):
    settings_saved = Signal(str, str)

    def __init__(self, parent=None, current_api_key="", current_model=""):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setModal(True)

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

        api_layout = QHBoxLayout()
        api_label = QLabel("API密钥：")
        self.api_entry = QLineEdit()
        self.api_entry.setEchoMode(QLineEdit.Password)
        self.api_entry.setText(current_api_key)
        api_layout.addWidget(api_label)
        api_layout.addWidget(self.api_entry)
        layout.addLayout(api_layout)

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

        button_layout = QHBoxLayout()
        button_layout.addSpacerItem(QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))

        self.save_button = QPushButton("保存")
        self.save_button.setObjectName("save_button")
        self.save_button.clicked.connect(self.save_settings)

        self.cancel_button = QPushButton("取消")
        self.cancel_button.setObjectName("cancel_button")
        self.cancel_button.clicked.connect(self.reject)

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

        self.settings_saved.emit(api_key, selected_model)
        self.accept()

    def get_settings(self):
        return self.api_entry.text().strip(), self.model_combo.currentText()

class ChatGUI(QMainWindow):
    update_chat_signal = Signal(str, str) # 用于更新聊天历史显示
    # 新增信号，用于实时更新助手的流式输出
    stream_new_text_signal = Signal(str, str) # role, text_delta
    # 新增信号，用于API请求完成后在主线程处理后续操作（包括流式结束）
    api_request_finished_signal = Signal(dict)

    def __init__(self):
        super().__init__()
        self.api_key = ""
        self.selected_model = ""
        self.dialog_history = []
        self._session_id = None
        self.is_dark_mode = False
        self.current_history_file = None
        self.is_displaying_historical_chat = False
        self.current_assistant_response_text = "" # 用于累积流式输出的文本

        self._load_config()
        self._init_ui()
        self._load_stylesheet()
        self._connect_signals()

        self.initial_welcome_message = (
            "<b>我是一个科技金融小助手</b>，很高兴回答你的问题！<br>"
            "输入 <code>/reset</code> 可以清空对话历史并开始新的会话。<br>"
            "您可以在左侧的“历史记录”中查看和管理以往的对话。"
        )
        self.add_message_to_history("assistant", self.initial_welcome_message, is_stream=False) # 初始欢迎消息非流式
        self._load_history_list()


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

        self.resize(1280, 720)
        self.showMaximized()

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        self.main_h_layout = QHBoxLayout(main_widget)
        self.main_h_layout.setContentsMargins(10, 10, 10, 10)
        self.main_h_layout.setSpacing(10)

        self.sidebar_widget = QWidget()
        self.sidebar_widget.setObjectName("sidebar_widget")
        self.sidebar_widget.setFixedWidth(280)
        self.sidebar_layout = QVBoxLayout(self.sidebar_widget)
        self.sidebar_layout.setContentsMargins(0, 0, 0, 0)
        self.sidebar_layout.setSpacing(5)

        sidebar_label = QLabel("历史记录")
        sidebar_label.setObjectName("sidebar_label")
        sidebar_label.setAlignment(Qt.AlignCenter)
        sidebar_label.setFont(QFont("微软雅黑", 11, QFont.Bold))
        self.sidebar_layout.addWidget(sidebar_label)

        self.history_list_widget = QListWidget()
        self.history_list_widget.setFont(QFont("微软雅黑", 10))
        self.sidebar_layout.addWidget(self.history_list_widget)
        self.main_h_layout.addWidget(self.sidebar_widget)

        self.chat_area_widget = QWidget()
        self.chat_area_layout = QVBoxLayout(self.chat_area_widget)
        self.chat_area_layout.setContentsMargins(0, 0, 0, 0)
        self.chat_area_layout.setSpacing(10)

        self.chat_history_view = QTextBrowser()
        self.chat_history_view.setReadOnly(True)
        self.chat_history_view.setFont(QFont("微软雅黑", 12))
        self.chat_history_view.setOpenExternalLinks(True)
        self.chat_area_layout.addWidget(self.chat_history_view, 1)

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
        self.send_button.setObjectName("send_button")
        self.send_button.setFont(QFont("微软雅黑", 11, QFont.Bold))
        self.send_button.setFixedHeight(self.user_input_edit.height())
        input_layout.addWidget(self.send_button)
        self.chat_area_layout.addWidget(input_frame)

        bottom_button_layout = QHBoxLayout()
        bottom_button_layout.addSpacerItem(QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))

        self.dark_mode_button = QPushButton("🌙 黑夜模式")
        self.dark_mode_button.setObjectName("dark_mode_button")
        self.dark_mode_button.setFont(QFont("微软雅黑", 10))
        bottom_button_layout.addWidget(self.dark_mode_button)

        self.settings_button = QPushButton("⚙ 设置")
        self.settings_button.setObjectName("settings_button")
        self.settings_button.setFont(QFont("微软雅黑", 10))
        bottom_button_layout.addWidget(self.settings_button)

        self.clear_history_button = QPushButton("清空对话")
        self.clear_history_button.setObjectName("clear_history_button")
        self.clear_history_button.setFont(QFont("微软雅黑", 10))
        bottom_button_layout.addWidget(self.clear_history_button)

        self.chat_area_layout.addLayout(bottom_button_layout)
        self.main_h_layout.addWidget(self.chat_area_widget, 1)

    def _connect_signals(self):
        self.send_button.clicked.connect(self.on_send_button_clicked)
        self.user_input_edit.keyPressEvent = self.input_key_press_event
        self.settings_button.clicked.connect(self.show_settings_dialog)
        self.clear_history_button.clicked.connect(lambda: self.handle_user_command("/reset"))
        self.update_chat_signal.connect(self._update_chat_history_slot)
        self.dark_mode_button.clicked.connect(self.toggle_dark_mode)
        self.history_list_widget.itemClicked.connect(self._on_history_item_clicked)
        # 连接流式输出的信号
        self.stream_new_text_signal.connect(self._append_stream_text_slot)
        # 连接API请求完成的信号到槽
        self.api_request_finished_signal.connect(self._on_api_request_finished)


    def _load_config(self):
        try:
            config_path = get_asset_path('config.json')
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    self.api_key = config.get('api_key', '')
                    self.selected_model = config.get('selected_model', '')
                    self.is_dark_mode = config.get('is_dark_mode', False)
                    logging.info(f'成功读取配置文件，api_key: {"*"*5 if self.api_key else ""}, selected_model: {self.selected_model}, is_dark_mode: {self.is_dark_mode}')
            else:
                logging.warning('未找到配置文件 config.json，将使用默认空值。')
        except Exception as e:
            logging.error(f'读取配置文件时出错: {e}')

    def _save_config(self):
        try:
            config_path = get_asset_path('config.json')
            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump({
                    'api_key': self.api_key,
                    'selected_model': self.selected_model,
                    'is_dark_mode': self.is_dark_mode,
                }, f, indent=4)
            logging.info('配置已保存！')
        except Exception as e:
            logging.error(f'保存配置文件时出错: {e}')
            QMessageBox.critical(self, "错误", f"保存配置失败: {e}")

    def _load_stylesheet(self):
        stylesheet_name = 'dark_mode.qss' if self.is_dark_mode else 'light_mode.qss'
        stylesheet_path = get_asset_path(stylesheet_name)
        try:
            if os.path.exists(stylesheet_path):
                with open(stylesheet_path, 'r', encoding='utf-8') as f:
                    self.setStyleSheet(f.read())
                logging.info(f"成功加载样式表: {stylesheet_path}")
                self.dark_mode_button.setText("☀️ 日间模式" if self.is_dark_mode else "🌙 黑夜模式")
            else:
                logging.warning(f"样式表文件未找到: {stylesheet_path}")
                self.setStyleSheet("")
        except Exception as e:
            logging.error(f"加载样式表时出错: {e}")
            self.setStyleSheet("")

    def toggle_dark_mode(self):
        self.is_dark_mode = not self.is_dark_mode
        self._load_stylesheet()
        self._save_config()
        logging.info(f"黑夜模式状态切换为: {self.is_dark_mode}")

        if self.is_displaying_historical_chat and self.current_history_file:
            self._display_historical_chat(self.current_history_file)
        else:
            self.refresh_chat_display()

    def refresh_chat_display(self):
        current_scroll_value = self.chat_history_view.verticalScrollBar().value()
        self.chat_history_view.clear()
        
        # 复制一份当前的对话历史用于重建显示
        temp_dialog_history_for_refresh = self.dialog_history[:]
        self.dialog_history.clear() # 清空内存中的对话历史，将通过add_message_to_history重新填充

        # 重新添加欢迎信息 (如果不是在显示历史记录模式)
        self.add_message_to_history("assistant", self.initial_welcome_message, is_stream=False)

        for msg in temp_dialog_history_for_refresh:
            # 跳过已添加的欢迎信息
            if msg['role'] == 'assistant' and msg['content'] == self.initial_welcome_message:
                continue
            
            # add_message_to_history 会根据角色处理消息内容并添加到 self.dialog_history
            self.add_message_to_history(msg['role'], msg['content'], is_stream=False) # 刷新时按非流式处理
            
        self.chat_history_view.verticalScrollBar().setValue(current_scroll_value)


    @Slot(str, str)
    def _update_chat_history_slot(self, role, message_html_content):
        # 此槽用于添加完整消息（例如用户消息、欢迎消息或完整的历史消息）
        self.chat_history_view.append(message_html_content)
        self.chat_history_view.verticalScrollBar().setValue(self.chat_history_view.verticalScrollBar().maximum())

    @Slot(str, str)
    def _append_stream_text_slot(self, role, text_delta):
        # 此槽用于处理流式输出的增量文本
        # 移动光标到文档末尾，以便在正确位置插入文本
        cursor = self.chat_history_view.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.chat_history_view.setTextCursor(cursor)
        
        # 插入新的文本（Plain text, not HTML yet）
        self.chat_history_view.insertPlainText(text_delta)
        
        # 实时滚动到最底部
        self.chat_history_view.verticalScrollBar().setValue(self.chat_history_view.verticalScrollBar().maximum())


    def add_message_to_history(self, role, message_content, is_stream=False):
        user_avatar_path = get_asset_path('user.ico')
        robot_avatar_path = get_asset_path('robot.ico')

        avatar_html = ""
        message_box_class = "user-message-box" if role == 'user' else "assistant-message-box"
        message_container_style = "display: flex; align-items: flex-start; margin-bottom: 10px;"
        avatar_style = "width: 35px; height: 35px; border-radius: 100%; margin-right: 8px; vertical-align: top;"

        if role == 'user':
            actual_html_content_for_display = f'<p>{message_content}</p>' # 用于显示
            if os.path.exists(user_avatar_path):
                avatar_html = f'<img src="file:///{user_avatar_path.replace(os.sep, "/")}" style="{avatar_style}">'
            
            # 用户消息直接添加到内存历史
            if not self.is_displaying_historical_chat:
                self.dialog_history.append({'role': role, 'content': message_content})

            formatted_message = f"""
            <div class="message-container" style="{message_container_style}">
                {avatar_html}
                <div class="{message_box_class}">
                    {actual_html_content_for_display}
                </div>
            </div>
            """
            self.update_chat_signal.emit(role, formatted_message)
            self.current_assistant_response_text = "" # 重置助手当前累积的文本

        else: # assistant
            if is_stream:
                # 对于流式助手的第一个消息，先显示框架和头像
                if not self.current_assistant_response_text: # 首次接收流式内容时
                    # 在文本浏览器中插入一个特殊标记，后续增量文本将插入到这个标记之前
                    # 更好的方法是，第一次发送消息时，创建消息框并插入占位符
                    formatted_message_start = f"""
                    <div id="assistant_stream_message" class="message-container" style="{message_container_style}">
                        {f'<img src="file:///{robot_avatar_path.replace(os.sep, "/")}" style="{avatar_style}">' if os.path.exists(robot_avatar_path) else ''}
                        <div class="{message_box_class}">
                            <p id="stream_content"></p>
                        </div>
                    </div>
                    """
                    self.update_chat_signal.emit(role, formatted_message_start)
                    # 移动光标到 <p id="stream_content"></p> 标签内部
                    cursor = self.chat_history_view.textCursor()
                    cursor.movePosition(QTextCursor.End)
                    # 找到插入点 (QTextBrowser直接用HTML append会创建一个新的块，所以需要巧妙地插入文本)
                    # 最直接的方法是，先添加一个空的div，然后每次更新这个div的内容
                    # 也可以用 document().findBlockByLineNumber() 等方法，但这里为了简单，
                    # 每次接收到流式文本时直接appendPlaintext，并更新内存中的 full_response_text
                    
                    # 另一种策略: 第一次 append 完整的消息容器，内容为空
                    # 之后每次更新，是直接修改 QTextBrowser 最后一个 assistant message box 的内容
                    # 这需要更精细的 QTextDocument 操作
                    # 简单的流式显示是每次append delta，但那样就无法在一个气泡内显示
                    
                    # 更简单的处理：在_append_stream_text_slot里直接追加文本
                    # 缺点：无法很好地在一个“气泡”中显示，每段增量文本都可能另起一行
                    # 为保持在一个气泡内，我们需要更复杂地操作 QTextDocument
                    # 鉴于 PySide6 的 QTextBrowser 限制，直接追加纯文本是最简单的流式展示方式
                    # 考虑到“气泡”布局，我们需要在收到第一块文本时生成一个气泡，然后在这个气泡内追加文本

                    # 更好的流式显示处理 (在 add_message_to_history):
                    # 1. 收到第一块文本时，生成一个消息容器，内容为空，并标记为正在流式输出
                    # 2. 后续收到文本时，找到这个容器，追加文本到其内容中
                    # 3. 流结束时，把最终内容保存到 dialog_history

                    # 这种复杂性超出了简单的 add_message_to_history 职能
                    # 为了简化，我们暂时接受每段增量文本都可能独立追加的显示效果，
                    # 或者我们只在_on_api_request_finished一次性更新dialog_history并重新渲染
                    # 但那样就不是“流式”了

                    # **简化流式输出显示策略**:
                    # 首次收到助手流式响应时，在 chat_history_view 添加一个“助手正在输入...”的占位符或空消息框。
                    # 后续每次收到增量文本，就更新这个消息框的文本内容。
                    # 这需要 Q_PROPERTY 或者自定义的 QObject 来追踪并更新特定消息块。
                    # 鉴于当前架构，最简单的流式显示是在一个新的“气泡”中持续追加文本。
                    # 为了统一到一个气泡内，需要更高级的 QTextDocument 操作。

                    # 暂时保持每次更新都通过 _append_stream_text_slot 实现，
                    # 但这意味着每个delta会像新行一样追加，而不是在一个消息块里连续。
                    # 修正：为了实现单个气泡内的流式，我们需要在收到第一块文本时“打印”出气泡框架，
                    # 并在内部预留一个 <span id="assistant_streaming_content"></span>
                    # 然后通过 JS 注入或更复杂的 QTextDocument 操作来更新这个 span 的 innerHTML。
                    # 这对于 PySide6 的 QTextBrowser 来说是比较复杂的。

                    # **备选方案（最接近“流式”且相对简单）**:
                    # 不再使用 formatted_message HTML，而是直接追加纯文本到 QTextBrowser。
                    # 当流式开始时，先打印头像和气泡的起始 HTML，然后通过 appendPlainText 逐个追加文本，
                    # 最后在流结束时，添加气泡的结束 HTML。但这会打断 HTML 结构。
                    
                    # **折衷方案（当前实现）**:
                    # 在 add_message_to_history 收到 'assistant' 且 is_stream=True 且 `self.current_assistant_response_text` 为空时，
                    # 打印一个新的消息容器，并将其 `id` 设置为 `streaming_assistant_message`。
                    # 之后的 `stream_new_text_signal` 就不再 append HTML，而是直接修改这个 `id` 元素的文本内容。
                    # 这需要 `QTextBrowser.document().findBlock()` 和 `QTextCursor` 的配合。

                    # 考虑到当前 _update_chat_history_slot 只做 append，我们重构流式显示逻辑。
                    # 当接收到助手的第一个流式响应时，我们显示一个初始的助手消息框。
                    # 随后的流式增量文本会通过 `_append_stream_text_slot` 更新这个已有的消息框。
                    
                    # 第一次收到流式响应时，创建一个消息容器
                    # 这里先用一个占位符，后续会由 _append_stream_text_slot 更新
                    # 为了能够更新同一个文本块，我们需要更复杂一点的逻辑
                    # 简单起见，我们让 _update_chat_history_slot 负责生成 HTML 容器
                    # 然后 _append_stream_text_slot 负责在 QTextBrowser 中追加文本
                    # 这意味着每段流式文本会像独立的消息一样显示，而非在一个气泡内连续显示。
                    # 这与常见的聊天应用有所不同，但实现起来简单。

                    # 重新考虑：如果 `add_message_to_history` 不直接修改 `chat_history_view`，而是通过信号
                    # 那么 `_update_chat_history_slot` 和 `_append_stream_text_slot` 应该如何协同？
                    # 
                    # 方案：
                    # 1. 用户发送消息后，立即显示用户消息。
                    # 2. 启动助手API请求线程。
                    # 3. 助手API请求线程开始流式返回时：
                    #    - 第一次返回：`_process_api_request_thread` 发出信号 `stream_new_text_signal`，包含完整的助手消息起始HTML（包括头像和空内容区）。
                    #      `_append_stream_text_slot` 接收并添加到 `chat_history_view`。
                    #    - 后续返回：`_process_api_request_thread` 继续发出信号 `stream_new_text_signal`，只包含增量文本。
                    #      `_append_stream_text_slot` 接收增量文本，并追加到 `chat_history_view` 中的最后一个助手消息块。
                    #      这需要找到最后一个助手消息块并修改其内容。
                    # 
                    # 这有点复杂。最简单的流式展示是：
                    # 当收到流式消息时，`_update_chat_history_slot` 打印一个包含“助手正在生成”的占位符。
                    # `_append_stream_text_slot` 每次收到新文本，就将它追加到这个占位符后面，并且替换掉占位符。
                    # 当流结束时，将最终的 `full_response_text` 添加到 `dialog_history`。

                # 重构 add_message_to_history 以适应流式输出
                # 当是助手消息且是流式时，我们只在 _on_api_request_finished 最终将完整内容添加到 dialog_history
                # 在流式过程中，我们只更新显示
                self.stream_new_text_signal.emit(role, message_content) # 这里的 message_content 是 delta_text

            else: # 非流式助手消息（如欢迎语、错误信息或历史记录加载）
                # 助手消息，actual_html_content_for_display 和 message_content 都是传入的 content
                actual_html_content_for_display = message_content
                if not message_content.strip().startswith('<'): # 如果助手消息不是HTML（例如纯文本错误）
                     actual_html_content_for_display = f'<p>{message_content}</p>'
                if os.path.exists(robot_avatar_path):
                    avatar_html = f'<img src="file:///{robot_avatar_path.replace(os.sep, "/")}" style="{avatar_style}">'
                
                formatted_message = f"""
                <div class="message-container" style="{message_container_style}">
                    {avatar_html}
                    <div class="{message_box_class}">
                        {actual_html_content_for_display}
                    </div>
                </div>
                """
                self.update_chat_signal.emit(role, formatted_message)

                # 避免重复添加欢迎语到内存历史
                is_initial_welcome = (role == 'assistant' and message_content == self.initial_welcome_message)
                is_already_first_welcome = (len(self.dialog_history) > 0 and
                                          self.dialog_history[0]['role'] == 'assistant' and
                                          self.dialog_history[0]['content'] == self.initial_welcome_message)

                if not (is_initial_welcome and is_already_first_welcome) and not self.is_displaying_historical_chat:
                    self.dialog_history.append({'role': role, 'content': message_content})


    def on_send_button_clicked(self):
        user_text = self.user_input_edit.toPlainText().strip()
        if not user_text:
            return
        self.user_input_edit.clear()
        self.handle_user_command(user_text)

    def input_key_press_event(self, event):
        if event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
            if event.modifiers() == Qt.ControlModifier:
                self.on_send_button_clicked()
                return
        QTextEdit.keyPressEvent(self.user_input_edit, event)


    def handle_user_command(self, text):
        if self.is_displaying_historical_chat:
            self._start_new_current_session()

        if text.lower() == '/reset':
            self._save_current_history()
            self.dialog_history.clear()
            self._session_id = None
            self.current_history_file = None
            self.chat_history_view.clear()
            self.add_message_to_history('assistant', self.initial_welcome_message, is_stream=False)
            self._load_history_list()
            return

        if not self.current_history_file and not self.dialog_history:
            # 如果是新会话，且当前没有历史记录，创建一个新的历史文件
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            clean_timestamp = re.sub(r'[^\w\-_\. ]', '_', timestamp)
            self.current_history_file = f"chat_{clean_timestamp}.html"
            logging.info(f"新会话开始，历史文件: {self.current_history_file}")

        # 用户消息立即显示并加入到 dialog_history
        self.add_message_to_history('user', text, is_stream=False)

        if not self.api_key:
            self.add_message_to_history('assistant', '请先在设置中填写有效的 API 密钥。', is_stream=False)
            return
        if not self.selected_model:
            self.add_message_to_history('assistant', '请先选择有效的模型。', is_stream=False)
            return
        
        # 助手回复的“容器”需要在流式开始前创建
        self.current_assistant_response_text = "" # 重置累积文本
        # 显示一个空的助手消息容器作为流式输出的起点
        robot_avatar_path = get_asset_path('robot.ico')
        avatar_html = f'<img src="file:///{robot_avatar_path.replace(os.sep, "/")}" style="width: 35px; height: 35px; border-radius: 100%; margin-right: 8px; vertical-align: top;">' if os.path.exists(robot_avatar_path) else ''
        initial_assistant_html = f"""
        <div class="message-container" style="display: flex; align-items: flex-start; margin-bottom: 10px;">
            {avatar_html}
            <div class="assistant-message-box">
                <p style="margin:0; padding:0; display:inline;" id="streaming_output_placeholder"></p>
            </div>
        </div>
        """
        self.update_chat_signal.emit("assistant", initial_assistant_html) # 发送 HTML 容器

        threading.Thread(target=self._process_api_request_thread, daemon=True).start()

    def _process_api_request_thread(self):
        """在后台线程中处理API请求，完成后通过信号通知主线程。"""
        # 构建发送给API的messages列表
        # self.dialog_history 在这里是只读的，是安全的
        api_messages_for_request = [
            msg for msg in self.dialog_history
            if not (msg['role'] == 'assistant' and msg['content'] == self.initial_welcome_message)
        ]

        if not api_messages_for_request:
            logging.warning("API messages for request is empty after filtering. Cannot send request.")
            self.api_request_finished_signal.emit({'error': "没有有效的消息发送给API。", 'session_id': None, 'final_answer': ''})
            return

        try:
            # Controller.process_api_request 现在是一个生成器
            for response_data in Controller.process_api_request(
                self.api_key, api_messages_for_request, self.selected_model, self._session_id
            ):
                text_delta = response_data.get('text', '')
                new_session_id = response_data.get('session_id')
                is_end = response_data.get('is_end', False)
                error_occurred = response_data.get('error', False)

                if new_session_id:
                    self._session_id = new_session_id

                if error_occurred:
                    self.api_request_finished_signal.emit({'error': text_delta, 'session_id': self._session_id, 'final_answer': ''})
                    return # 发生错误，终止流并返回
                
                # 更新累积文本
                self.current_assistant_response_text += text_delta

                # 发射信号更新UI，如果不是结束标志，并且有增量文本
                if not is_end and text_delta:
                    self.stream_new_text_signal.emit("assistant", text_delta)
                elif is_end:
                    # 流式结束，发送最终信号，包含完整的答案
                    self.api_request_finished_signal.emit({
                        'answer': self.current_assistant_response_text, 
                        'session_id': self._session_id, 
                        'is_end': True
                    })
                    break # 结束循环

        except Exception as e:
            logging.error(f"处理API请求流时发生错误: {e}", exc_info=True)
            self.api_request_finished_signal.emit({'error': f"请求出错，请稍后再试。错误详情：{str(e)}", 'session_id': self._session_id, 'final_answer': ''})


    @Slot(dict)
    def _on_api_request_finished(self, result_package):
        """在主线程中处理API请求完成后的操作（包括流式结束时）。"""
        answer = result_package.get('answer')
        new_session_id = result_package.get('session_id')
        error_message = result_package.get('error')
        
        if new_session_id:
            self._session_id = new_session_id

        # 找到最近添加的助手消息块并更新其内容
        # 这是为了确保流式输出最终以完整的HTML格式存储，并保持在同一个“气泡”中
        cursor = self.chat_history_view.textCursor()
        cursor.movePosition(QTextCursor.End)
        # 向上移动到最近的助手消息块的开始
        # 这段逻辑需要更精确的文本文档操作，直接修改HTML内容非常复杂
        # 更简单的方法是，在流结束时，将完整的文本作为新的消息添加到历史记录，
        # 并刷新显示，但这会清除流式效果。
        #
        # 鉴于 QTextBrowser 对 HTML 的操作能力，最简单且保留流式效果的方案是：
        # 1. 流式开始时，插入一个空的HTML结构作为助手回复的容器。
        # 2. 每次收到增量文本，使用 JavaScript (如果可能) 或更复杂的方法在现有 HTML 结构中更新文本。
        #    但 QTextBrowser 不支持 JS。所以只能在 QTextBrowser 文本内容上操作。
        # 
        # 最直接的流式显示方案 (每次增量追加纯文本) 的缺点是无法保持在同一个“气泡”中。
        #
        # **最终采取的折衷方案：**
        # 1. `handle_user_command` 发出用户消息后，立即显示用户消息。
        # 2. 然后立即显示一个带有“助手”头像和空内容的助手消息框（id为 `streaming_output_placeholder`）。
        # 3. `_append_stream_text_slot` 负责找到这个 `streaming_output_placeholder` 并追加文本。
        # 4. `_on_api_request_finished` 时，将 `self.current_assistant_response_text` 
        #    作为一个完整的消息添加到 `self.dialog_history`。
        #    然后刷新 `chat_history_view` 以便将流式内容固化为完整HTML结构。

        if error_message:
            # 如果有错误，直接显示错误信息
            self.add_message_to_history('assistant', error_message, is_stream=False)
            self.current_assistant_response_text = "" # 清空累积文本
        elif answer:
            # 流式结束，将最终的完整答案添加到dialog_history
            if self.current_assistant_response_text: # 确保有累积的文本
                # 在添加之前，先尝试清除流式占位符（如果仍然可见）
                # 理论上，QTextBrowser 的 setHtml 会完全替换内容
                # 但为了确保正确保存到历史，我们需要最终的完整文本
                
                # 如果没有错误，并且有累积的完整答案
                # 将累积的完整答案作为一条完整的消息添加到历史记录
                self.dialog_history.append({'role': 'assistant', 'content': self.current_assistant_response_text})
                logging.info(f"完整的助手回复已添加到历史：{self.current_assistant_response_text[:50]}...")
            self.current_assistant_response_text = "" # 清空累积文本
        else:
            logging.info("API请求完成，但未收到有效回复或错误信息。")
            self.current_assistant_response_text = "" # 清空累积文本

        # 每次API请求（无论流式还是非流式）结束后，保存当前会话并刷新历史列表
        self._save_current_history()
        self._load_history_list() # 刷新侧边栏

        # 最重要的部分：当流式输出结束后，需要将 QtextBrowser 显示的内容“固化”为最终的 HTML 结构。
        # 之前我们使用了 `_append_stream_text_slot` 直接追加纯文本，这可能不是在一个统一的“气泡”里。
        # 为了美观和正确保存，我们在这里重新加载并渲染当前会话。
        # 但是，这会清除流式展示的过程。

        # 更好的方法是在 `_append_stream_text_slot` 中直接操作 QTextBrowser 的 DOM 元素。
        # 但这需要更高级的 QTextDocument / QWebElement 操作，而 QTextBrowser 对此支持有限。
        #
        # 简化策略：
        # `_append_stream_text_slot` 直接追加文本。
        # `_on_api_request_finished` 结束时，将最终的 `self.current_assistant_response_text` 添加到 `self.dialog_history`。
        # **为了确保显示是正确的最终格式，我们在流式结束时重新渲染聊天区域。**
        # 这会丢失流式过程，但确保最终显示和保存的一致性。
        self.refresh_chat_display() # 重新刷新聊天显示，将累积的流式文本固化为HTML格式

    def show_settings_dialog(self):
        dialog = SettingsDialog(self, self.api_key, self.selected_model)
        dialog.settings_saved.connect(self.handle_settings_saved)
        dialog.exec()

    @Slot(str, str)
    def handle_settings_saved(self, api_key, selected_model):
        self.api_key = api_key
        self.selected_model = selected_model
        self._save_config()
        QMessageBox.information(self, "成功", "设置已保存！")
        # 检查 dialog_history 是否为空或仅包含初始欢迎消息
        is_initial_state = not self.dialog_history or \
                           (len(self.dialog_history) == 1 and
                            self.dialog_history[0]['role'] == 'assistant' and
                            self.dialog_history[0]['content'] == self.initial_welcome_message)
        if is_initial_state:
             self.add_message_to_history('assistant', '设置已更新，现在可以开始对话了。', is_stream=False)

    def _get_html_for_history(self, history_data, current_mode):
        user_avatar_path = get_asset_path('user.ico').replace(os.sep, "/")
        robot_avatar_path = get_asset_path('robot.ico').replace(os.sep, "/")

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
            content = msg['content']
            avatar_src = user_avatar_path if role == 'user' else robot_avatar_path
            message_box_class = "user-message-box" if role == 'user' else "assistant-message-box"
            
            if role == 'user':
                if not content.strip().startswith('<'):
                     content = f'<p>{content}</p>'
            else:
                if not content.strip().startswith('<'):
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
        # 从 self.dialog_history 中排除初始欢迎信息
        history_to_save = [
            msg for msg in self.dialog_history
            if not (msg['role'] == 'assistant' and msg['content'] == self.initial_welcome_message)
        ]

        if not history_to_save:
            logging.info("当前会话为空或只有欢迎语，不保存历史记录。")
            if self.current_history_file:
                file_path_to_check = get_history_path(self.current_history_file)
                if os.path.exists(file_path_to_check):
                    pass # 决定不主动删除，避免误删用户手动创建的空文件
            return

        if not self.current_history_file:
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            clean_timestamp = re.sub(r'[^\w\-_\. ]', '_', timestamp)
            self.current_history_file = f"chat_{clean_timestamp}.html"
            logging.info(f"为当前活动会话创建历史文件: {self.current_history_file}")


        file_path = get_history_path(self.current_history_file)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        html_output = self._get_html_for_history(history_to_save, 'dark' if self.is_dark_mode else 'light')
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(html_output)
            logging.info(f"对话历史已保存到: {file_path}")
        except Exception as e:
            logging.error(f"保存对话历史到文件失败: {file_path}, 错误: {e}")

    def _load_history_list(self):
        self.history_list_widget.clear()
        history_dir = get_history_path()
        
        if not os.path.exists(history_dir):
            os.makedirs(history_dir, exist_ok=True)
            return

        history_files_with_paths = []
        for f_name in os.listdir(history_dir):
            if f_name.endswith('.html'):
                full_path = get_history_path(f_name)
                try:
                    if os.path.getsize(full_path) > 200:
                        history_files_with_paths.append(f_name)
                except OSError:
                    pass
        
        history_files = sorted(history_files_with_paths, reverse=True)


        delete_icon_path = get_asset_path('delete.png')
        delete_icon = QIcon(delete_icon_path) if os.path.exists(delete_icon_path) else QIcon()

        for filename in history_files:
            try:
                match = re.match(r'chat_(\d{14})\.html', filename)
                if match:
                    timestamp_str = match.group(1)
                    display_title = datetime.strptime(timestamp_str, "%Y%m%d%H%M%S").strftime("%Y年%m月%d日%H点%M分%S秒")
                else:
                    display_title = filename.replace(".html", "")

                item = QListWidgetItem(self.history_list_widget)
                item.setData(Qt.UserRole, filename)

                item_widget = QWidget()
                item_layout = QHBoxLayout(item_widget)
                item_layout.setContentsMargins(5, 2, 5, 2)
                item_layout.setSpacing(5)

                title_label = QLabel(display_title)
                title_label.setFont(QFont("微软雅黑", 9))
                title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
                title_label.setWordWrap(True)

                delete_button = QPushButton()
                if delete_icon.isNull():
                    delete_button.setText("删")
                    delete_button.setFixedSize(20,20)
                else:
                    delete_button.setIcon(delete_icon)
                    delete_button.setIconSize(QSize(16, 16))
                    delete_button.setFixedSize(24, 24)

                delete_button.setFlat(True)
                delete_button.setToolTip(f"删除历史记录: {filename}")
                delete_button.setObjectName("history_delete_button")
                delete_button.clicked.connect(lambda checked=False, fn=filename: self._on_delete_history_item_clicked(fn))
                
                item_layout.addWidget(title_label)
                item_layout.addStretch()
                item_layout.addWidget(delete_button)
                
                item_widget.setLayout(item_layout)
                item.setSizeHint(item_widget.sizeHint())

                self.history_list_widget.addItem(item)
                self.history_list_widget.setItemWidget(item, item_widget)

            except Exception as e:
                logging.warning(f"加载历史文件项 {filename} 失败: {e}", exc_info=True)
    
    def _on_delete_history_item_clicked(self, filename_to_delete):
        reply = QMessageBox.question(self, "确认删除", 
                                     f"您确定要删除历史记录 '{filename_to_delete}' 吗？\n此操作无法撤销。",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, 
                                     QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.Yes:
            file_path = get_history_path(filename_to_delete)
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logging.info(f"成功删除历史文件: {file_path}")

                    if self.is_displaying_historical_chat and self.current_history_file == filename_to_delete:
                        self.chat_history_view.clear()
                        self.is_displaying_historical_chat = False
                        self.current_history_file = None
                        self.dialog_history.clear()
                        self._session_id = None
                        self.add_message_to_history("assistant", self.initial_welcome_message, is_stream=False)

                    elif not self.is_displaying_historical_chat and self.current_history_file == filename_to_delete:
                        self.current_history_file = None 
                    self._load_history_list()
                else:
                    QMessageBox.warning(self, "错误", f"文件 '{filename_to_delete}' 未找到。")
                    self._load_history_list()
            except Exception as e:
                logging.error(f"删除历史文件 {file_path} 失败: {e}", exc_info=True)
                QMessageBox.critical(self, "删除失败", f"无法删除历史记录: {e}")


    @Slot(QListWidgetItem)
    def _on_history_item_clicked(self, item):
        if not item: return
        filename = item.data(Qt.UserRole)
        if filename:
            if not self.is_displaying_historical_chat and self.dialog_history and \
               not (len(self.dialog_history) == 1 and self.dialog_history[0]['content'] == self.initial_welcome_message):
                self._save_current_history()

            self._display_historical_chat(filename)
            self.is_displaying_historical_chat = True
            self.current_history_file = filename
        else:
            logging.warning("_on_history_item_clicked: item has no filename data.")


    def _display_historical_chat(self, filename):
        file_path = get_history_path(filename)
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    html_content = f.read()
                
                body_tag_pattern = re.compile(r'<body\s*data-mode=["\'](light|dark)["\']([^>]*)>', re.IGNORECASE)
                current_mode_str = 'dark' if self.is_dark_mode else 'light'
                
                if body_tag_pattern.search(html_content):
                    html_content = body_tag_pattern.sub(f'<body data-mode="{current_mode_str}"\\2>', html_content)
                else:
                    html_content = html_content.replace('<body>', f'<body data-mode="{current_mode_str}">', 1)

                self.chat_history_view.setHtml(html_content)
                self.chat_history_view.moveCursor(QTextCursor.End)
                logging.info(f"已加载历史记录: {filename}，并应用当前模式: {current_mode_str}")
            except Exception as e:
                logging.error(f"加载历史记录文件 {file_path} 失败: {e}", exc_info=True)
                QMessageBox.warning(self, "错误", f"无法加载历史记录: {e}")
        else:
            QMessageBox.warning(self, "错误", f"历史记录文件不存在: {file_path}")
            self._load_history_list()

    def _start_new_current_session(self):
        if not self.is_displaying_historical_chat:
             self._save_current_history()

        self.dialog_history.clear()
        self._session_id = None
        self.current_history_file = None
        self.is_displaying_historical_chat = False
        
        self.chat_history_view.clear()
        self.add_message_to_history('assistant', self.initial_welcome_message, is_stream=False)
        
        logging.info("已切换到新的当前会话模式。")


    def closeEvent(self, event):
        if not self.is_displaying_historical_chat:
            self._save_current_history()
        self._save_config()
        logging.info("应用程序关闭。")
        super().closeEvent(event)
