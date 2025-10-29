# controller.py
from dashscope import Application
import logging
from http import HTTPStatus # 引入 HTTPStatus
class Controller:
    @staticmethod
    def process_api_request(api_key, dialog_history, model_name, session_id=None):
        model_app_id_map = {
            'deepseek-r1-distill-qwen-32b': '39d8f00473e14906b3fe4c32cbdb4f18',
            'deepseek-r1': '9facbc3b881943eaa6debfe508deee32',
            'qwen-plus': 'f196f5679be34d4cb2942fad915f21f3',
            'qwen-max': '79602e8ff8564665958c8392b507256a'
        }
        app_id = model_app_id_map.get(model_name)
        if not api_key:
            logging.warning("API key is missing in controller.")
            # 返回一个字典，包含错误信息和表示流式结束的标记
            yield {'text': '请先在设置中填写有效的 API 密钥。', 'session_id': None, 'is_end': True}
            return
        if not app_id:
            logging.warning(f"Invalid model name: {model_name}")
            yield {'text': '请选择有效的模型。', 'session_id': None, 'is_end': True}
            return
        try:
            logging.info(f"Calling Application with app_id: {app_id}, messages: {dialog_history}, session_id: {session_id}, stream=True, incremental_output=True")
            
            # 使用流式输出和增量输出
            responses = Application.call(
                api_key=api_key,
                app_id=app_id,
                messages=dialog_history,
                session_id=session_id,
                stream=True,  # 启用流式输出
                incremental_output=True # 启用增量输出
            )
            full_response_text = ""
            returned_session_id = session_id # 初始化为传入的session_id
            for response in responses: # 遍历流式响应
                if response.status_code != HTTPStatus.OK: # 检查响应状态码
                    error_message = (
                        f'请求ID: {response.request_id}\n'
                        f'错误码: {response.status_code}\n'
                        f'错误信息: {response.message}\n'
                        f'请参考文档：https://help.aliyun.com/zh/model-studio/developer-reference/error-code'
                    )
                    logging.error(f"API流式响应错误: {error_message}")
                    # 发生错误时，发送错误信息并标记为结束
                    yield {'text': error_message, 'session_id': returned_session_id, 'is_end': True, 'error': True}
                    return # 终止生成器
                else:
                    delta_text = response.output.text # 获取增量文本
                    current_session_id = response.output.session_id # 获取当前的session_id
                    if current_session_id:
                        returned_session_id = current_session_id # 更新session_id
                    if delta_text:
                        full_response_text += delta_text
                        # 每次收到增量内容，通过 yield 返回，并标记 is_end 为 False
                        yield {'text': delta_text, 'session_id': returned_session_id, 'is_end': False}
            # 流式传输结束，发送最终结果并标记 is_end 为 True
            logging.info(f"API stream finished. Final response text length: {len(full_response_text)}, session_id: {returned_session_id}")
            yield {'text': '', 'session_id': returned_session_id, 'is_end': True} 
        except Exception as e:
            logging.error(f"Error during streaming API request: {e}", exc_info=True)
            yield {'text': f'请求出错，请稍后再试。错误信息：{e}', 'session_id': None, 'is_end': True, 'error': True}