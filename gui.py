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
    update_chat_signal = Signal(str, str)
    # 新增信号，用于API请求完成后在主线程处理后续操作
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

        self._load_config()
        self._init_ui()
        self._load_stylesheet()
        self._connect_signals()

        self.initial_welcome_message = (
            "<b>我是一个科技金融小助手</b>，很高兴回答你的问题！<br>"
            "输入 <code>/reset</code> 可以清空对话历史并开始新的会话。<br>"
            "您可以在左侧的“历史记录”中查看和管理以往的对话。"
        )
        self.add_message_to_history("assistant", self.initial_welcome_message)
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

        self.resize(1280, 720) # 设置一个合理的默认大小，再最大化
        self.showMaximized() # 确保窗口启动后自动最大化

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
        # 连接新的信号到槽
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
        # add_message_to_history 会将消息添加到 self.dialog_history
        self.add_message_to_history("assistant", self.initial_welcome_message)

        for msg in temp_dialog_history_for_refresh:
            # 跳过已添加的欢迎信息
            if msg['role'] == 'assistant' and msg['content'] == self.initial_welcome_message:
                continue
            
            # add_message_to_history 会根据角色处理消息内容并添加到 self.dialog_history
            self.add_message_to_history(msg['role'], msg['content'])
            
        self.chat_history_view.verticalScrollBar().setValue(current_scroll_value)


    @Slot(str, str)
    def _update_chat_history_slot(self, role, message_html_content):
        self.chat_history_view.append(message_html_content)
        self.chat_history_view.verticalScrollBar().setValue(self.chat_history_view.verticalScrollBar().maximum())


    def add_message_to_history(self, role, message_content):
        user_avatar_path = get_asset_path('user.ico')
        robot_avatar_path = get_asset_path('robot.ico')

        avatar_html = ""
        message_box_class = "user-message-box" if role == 'user' else "assistant-message-box"
        message_container_style = "display: flex; align-items: flex-start; margin-bottom: 10px;"
        avatar_style = "width: 35px; height: 35px; border-radius: 100%; margin-right: 8px; vertical-align: top;"

        actual_html_content_for_display = message_content
        # message_content_for_history 变量用于存储到 self.dialog_history
        # 对于用户，存储纯文本；对于助手，存储传入的HTML（或纯文本错误信息）
        message_content_for_history = message_content

        if role == 'user':
            actual_html_content_for_display = f'<p>{message_content}</p>' # 用于显示
            # message_content_for_history 已经是纯文本
            if os.path.exists(user_avatar_path):
                avatar_html = f'<img src="file:///{user_avatar_path.replace(os.sep, "/")}" style="{avatar_style}">'
        else: # assistant
            # 助手消息，actual_html_content_for_display 和 message_content_for_history 都是传入的 content
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

        if not self.is_displaying_historical_chat:
            # 避免重复添加欢迎语到内存历史
            is_initial_welcome = (role == 'assistant' and message_content_for_history == self.initial_welcome_message)
            is_already_first_welcome = (len(self.dialog_history) > 0 and
                                      self.dialog_history[0]['role'] == 'assistant' and
                                      self.dialog_history[0]['content'] == self.initial_welcome_message)

            if not (is_initial_welcome and is_already_first_welcome):
                 self.dialog_history.append({'role': role, 'content': message_content_for_history})


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
            self.add_message_to_history('assistant', self.initial_welcome_message)
            self._load_history_list()
            return

        if not self.current_history_file and not self.dialog_history:
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            clean_timestamp = re.sub(r'[^\w\-_\. ]', '_', timestamp)
            self.current_history_file = f"chat_{clean_timestamp}.html"
            logging.info(f"新会话开始，历史文件: {self.current_history_file}")

        self.add_message_to_history('user', text)

        if not self.api_key:
            self.add_message_to_history('assistant', '请先在设置中填写有效的 API 密钥。')
            return
        if not self.selected_model:
            self.add_message_to_history('assistant', '请先选择有效的模型。')
            return

        threading.Thread(target=self._process_api_request_thread, daemon=True).start()

    def _process_api_request_thread(self):
        """在后台线程中处理API请求，完成后通过信号通知主线程。"""
        result_package = {'answer': None, 'session_id': self._session_id, 'error': None}
        try:
            # 构建发送给API的messages列表
            # self.dialog_history 在这里是只读的，是安全的
            api_messages_for_request = [
                msg for msg in self.dialog_history
                if not (msg['role'] == 'assistant' and msg['content'] == self.initial_welcome_message)
            ]
            # 确保如果只有用户输入，也能正确发送
            if not any(msg['role'] == 'user' for msg in api_messages_for_request) and api_messages_for_request:
                 # This case should ideally not happen if dialog_history is managed correctly
                 # For safety, if only assistant messages (other than welcome) are there, it's likely an invalid state to send.
                 # However, Controller.process_api_request expects a list of messages.
                 # The most crucial part is the user's latest query.
                 pass # Let it send if list is not empty


            if not api_messages_for_request:
                 logging.warning("API messages for request is empty after filtering. Cannot send request.")
                 result_package['error'] = "没有有效的消息发送给API。" # 或者更用户友好的提示
                 self.api_request_finished_signal.emit(result_package)
                 return

            response_data = Controller.process_api_request(
                self.api_key, api_messages_for_request, self.selected_model, self._session_id
            )
            
            result_package['answer'] = response_data.get('text')
            result_package['session_id'] = response_data.get('session_id') # 更新会话ID

        except Exception as e:
            logging.error(f"处理API请求时发生错误: {e}", exc_info=True)
            result_package['error'] = f"请求出错，请稍后再试。错误详情：{str(e)}"
        finally:
            # 发射信号，将结果传递给主线程处理
            self.api_request_finished_signal.emit(result_package)

    @Slot(dict)
    def _on_api_request_finished(self, result_package):
        """在主线程中处理API请求完成后的操作。"""
        answer = result_package.get('answer')
        new_session_id = result_package.get('session_id')
        error_message = result_package.get('error')

        if new_session_id: # 即使出错，也可能返回新的 session_id
            self._session_id = new_session_id

        if error_message:
            self.add_message_to_history('assistant', error_message)
        elif answer:
            self.add_message_to_history('assistant', answer)
        else:
            # 如果API没返回任何内容也没有错误（例如Controller内部处理并返回空text）
            logging.info("API请求完成，但未收到有效回复或错误信息（可能已在Controller处理）。")
            # self.add_message_to_history('assistant', "未能获取回复。") # 可选

        # 以下操作现在安全地在主线程执行
        self._save_current_history()
        self._load_history_list() # 刷新侧边栏


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
             self.add_message_to_history('assistant', 'API设置已更新，现在可以开始对话了。')

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
        for msg in history_data: # history_data 已经过滤掉了欢迎信息
            role = msg['role']
            content = msg['content'] 
            avatar_src = user_avatar_path if role == 'user' else robot_avatar_path
            message_box_class = "user-message-box" if role == 'user' else "assistant-message-box"
            
            if role == 'user':
                if not content.strip().startswith('<'): # 用户消息是纯文本
                     content = f'<p>{content}</p>'
            else: # 助手消息，如果是纯文本错误，也包装一下
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
            if self.current_history_file: # 如果之前创建了文件但没有内容，可以考虑删除
                file_path_to_check = get_history_path(self.current_history_file)
                if os.path.exists(file_path_to_check):
                    try:
                        # 尝试读取内容判断是否真的"空"（除了HTML框架）
                        # 为简单起见，如果 history_to_save 为空，就认为文件内容也无意义
                        # os.remove(file_path_to_check)
                        # logging.info(f"移除了空的或仅含欢迎语的历史文件: {file_path_to_check}")
                        pass # 决定不主动删除，避免误删用户手动创建的空文件
                    except OSError as e:
                        logging.error(f"尝试移除空历史文件 {file_path_to_check} 失败: {e}")
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
                    if os.path.getsize(full_path) > 200: # 过滤掉可能为空或过小的文件
                        history_files_with_paths.append(f_name)
                except OSError: # 文件可能在列出后被删除
                    pass
        
        history_files = sorted(history_files_with_paths, reverse=True)


        delete_icon_path = get_asset_path('delete.png')
        delete_icon = QIcon(delete_icon_path) if os.path.exists(delete_icon_path) else QIcon()

        for filename in history_files:
            try:
                match = re.match(r'chat_(\d{14})\.html', filename)
                if match:
                    timestamp_str = match.group(1)
                    # 将时间戳格式化为“2019年2月2日 12点35分21秒”
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

                self.history_list_widget.addItem(item) # addItem 应该在 setItemWidget 之前或之后都可以，但通常 item 是先 add
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
                        self.dialog_history.clear() # 清空内存中的对话历史
                        self._session_id = None # 重置会话ID
                        self.add_message_to_history("assistant", self.initial_welcome_message) # 显示欢迎

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
        if not self.is_displaying_historical_chat: # 如果本来就在当前会话 (例如 /reset)
             self._save_current_history() 

        self.dialog_history.clear()
        self._session_id = None
        self.current_history_file = None 
        self.is_displaying_historical_chat = False 
        
        self.chat_history_view.clear()
        self.add_message_to_history('assistant', self.initial_welcome_message)
        
        # 通常不需要在这里调用 _load_history_list()，除非 /reset 改变了文件列表
        # self._load_history_list() 
        logging.info("已切换到新的当前会话模式。")


    def closeEvent(self, event):
        if not self.is_displaying_historical_chat:
            self._save_current_history()
        self._save_config() 
        logging.info("应用程序关闭。")
        super().closeEvent(event)
