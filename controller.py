# controller.py
from dashscope import Application
import logging # 建议在 controller 中也加入日志记录

class Controller:
    @staticmethod
    def process_api_request(api_key, dialog_history, model_name, session_id=None): # 新增 session_id 参数
        model_app_id_map = {
            'deepseek-r1-distill-qwen-32b': '39d8f00473e14906b3fe4c32cbdb4f18',
            'deepseek-r1': '9facbc3b881943eaa6debfe508deee32',
            'qwen-plus': 'f196f5679be34d4cb2942fad915f21f3',
            'qwen-max': '79602e8ff8564665958c8392b507256a'
        }
        app_id = model_app_id_map.get(model_name)

        if not api_key:
            logging.warning("API key is missing in controller.")
            return {'text': '请先在设置中填写有效的 API 密钥。', 'session_id': None}
        if not app_id:
            logging.warning(f"Invalid model name: {model_name}")
            return {'text': '请选择有效的模型。', 'session_id': None}

        try:
            logging.info(f"Calling Application with app_id: {app_id}, messages: {dialog_history}, session_id: {session_id}")
            
            # 传入 session_id 参数
            response = Application.call(
                api_key=api_key,
                app_id=app_id,
                messages=dialog_history,
                session_id=session_id 
            )

            if response and hasattr(response, 'output') and hasattr(response.output, 'text'):
                response_text = response.output.text.strip()
                returned_session_id = response.output.session_id # 获取返回的 session_id
                logging.info(f"API response successful: {response_text[:100]}...") # Log first 100 chars
                logging.info(f"Returned session_id: {returned_session_id}")
                return {'text': response_text, 'session_id': returned_session_id}
            else:
                logging.error(f"Invalid API response structure: {response}")
                return {'text': 'API响应格式错误，请检查。', 'session_id': None}
        except Exception as e:
            logging.error(f"Error during API request: {e}", exc_info=True)
            return {'text': f'请求出错，请稍后再试。错误信息：{e}', 'session_id': None}