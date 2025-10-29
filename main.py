# main.py
import sys
import os
import logging
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont # 可选：设置全局字体
from gui import ChatGUI, get_asset_path # 导入 get_asset_path
if __name__ == "__main__":
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout) # 输出到控制台
            # 可以添加 logging.FileHandler('app.log') 来输出到文件
        ]
    )
    logging.info("应用程序启动...")
    app = QApplication(sys.argv)
    # 可选: 设置全局字体 (如果需要统一风格)
    # default_font = QFont("微软雅黑", 10)
    # app.setFont(default_font)
    main_window = ChatGUI()
    main_window.show()
    sys.exit(app.exec())