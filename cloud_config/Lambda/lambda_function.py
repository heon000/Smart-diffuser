"""
AWS Lambda의 진입점으로서 모든 API Gateway 요청을 최초로 수신하고 각 핸들러로 라우팅함.
"""

import sys
import os
import json
import logging

sys.path.append(os.path.dirname(__file__))

from handlers.common import _normalize_weights
import api_utils

from handlers.voice_handler import handle_voice
from handlers.auth_handler import handle_auth
from handlers.settings_handler import handle_settings
from handlers.device_handler import handle_device
from handlers.feedback_handler import handle_feedback
from handlers.ambient_handler import handle_ambient
from handlers.core_mode_handler import handle_core_modes
from handlers import kakao_bot_handler

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    """
    lambda_handler 함수: 해당 역할을 수행함.
    """
    logger.info("============== [REQUEST START] ==============")

    try:
        logger.info(f"[EVENT] {json.dumps(event, ensure_ascii=False)}")
    except Exception as e:
        logger.warning(f"[EVENT_LOG_FAIL] {e}")

    raw_body = event.get("body", "")
    logger.info(f"[RAW_BODY] {raw_body}")
    parsed_preview = {}

    try:
        parsed_preview = json.loads(raw_body) if raw_body else {}
        logger.info(f"[PARSED_BODY] {json.dumps(parsed_preview, ensure_ascii=False)}")
        logger.info(f"[BODY_KEYS] {list(parsed_preview.keys())}")
        logger.info(
            f"[BODY_VALUES] action={parsed_preview.get('action')}, "
            f"mode={parsed_preview.get('mode')}, "
            f"region={parsed_preview.get('region')}, "
            f"w1={parsed_preview.get('w1')}, "
            f"w2={parsed_preview.get('w2')}, "
            f"w3={parsed_preview.get('w3')}, "
            f"w4={parsed_preview.get('w4')}, "
            f"weights={parsed_preview.get('weights')}"
        )
    except Exception as e:
        logger.warning(f"[BODY_PARSE_FAIL] {e}")

    device_id = api_utils._guess_device_id(event, parsed_preview)
    headers = event.get("headers") or {}
    content_type = api_utils._get_header(headers, "content-type")
    x_mime = api_utils._get_header(headers, "x-mime-type")
    is_audio = any(x in str(content_type).lower() for x in ["audio/", "video/webm"]) or \
               any(x in str(x_mime).lower() for x in ["audio/", "video/webm"])

    if is_audio:
        return handle_voice(event, device_id)

    raw_body = event.get("body", {})

    try:
        if isinstance(raw_body, str):
            body = json.loads(raw_body) if raw_body else {}
        elif isinstance(raw_body, dict):
            body = raw_body
        else:
            body = {}
    except Exception as e:
        logger.warning(f"[JSON_PARSE_ERROR] {e}")
        body = {}

    if "userRequest" in body:
        return kakao_bot_handler.handle_kakao_bot(body)

    device_id = api_utils._guess_device_id(event, body)
    normalized_weights = _normalize_weights(body)

    mode = body.get("mode", "weather")
    region = body.get("region") or body.get("data", "서울")
    action = body.get("action", "")
    if not (body.get("region") or body.get("data")):
        region = ""

    auth_response = handle_auth(action, body, device_id)
    if auth_response:
        return auth_response

    settings_response = handle_settings(action, body, device_id)
    if settings_response:
        return settings_response

    device_response = handle_device(action, mode, body, device_id, normalized_weights)
    if device_response:
        return device_response

    feedback_response = handle_feedback(action, mode, body, device_id)
    if feedback_response:
        return feedback_response

    ambient_response = handle_ambient(mode, body, device_id, normalized_weights)
    if ambient_response:
        return ambient_response

    if action == "AI_WEATHER":
        mode = "weather"
        logger.info(f"[AI_WEATHER_TRIGGER] Region: {region}")

    return handle_core_modes(action, mode, body, device_id, normalized_weights, region)
