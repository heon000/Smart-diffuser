# 디바이스 핸들러: 디퓨저 기기 자체의 상태 조회 및 제어 요청을 담당합니다.

import json
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import db_utils
import api_utils
from .common import _to_decimal_list
logger = logging.getLogger()
# handle_device: device 기능과 관련된 클라이언트의 API 요청을 분석하고 처리합니다.
def handle_device(action, mode, body, device_id, normalized_weights):
    if action == "POLL":
        is_app_request = True if body.get("email") else False
        if not is_app_request:
            current_w = normalized_weights[0]
            current_db = int(body.get("db_level", 0))
            logger.info(f"[POLL_HARDWARE] ID:{device_id} Weights:{normalized_weights} DB:{current_db}")
            update_exp = "set weight_g = :wg, weights = :w, db_level = :db"
            exp_vals = {
                ':wg': Decimal(str(current_w)),
                ':w': _to_decimal_list(normalized_weights),
                ':db': current_db
            }
            try:
                db_utils.state_table.update_item(
                    Key={'deviceId': device_id},
                    UpdateExpression=update_exp,
                    ExpressionAttributeValues=exp_vals
                )
            except Exception as e:
                logger.error(f"무게 및 소음 DB 업데이트 실패: {e}")
        state = db_utils.get_device_state(device_id) or {}
        db_weights = state.get('weights', [Decimal("0")] * 4)
        if isinstance(db_weights, list):
            final_weights = [float(w) for w in db_weights]
        else:
            final_weights = normalized_weights
        auto_stop_str = state.get('auto_stop_time', "")
        if auto_stop_str:
            try:
                auto_stop_time = datetime.fromisoformat(auto_stop_str)
                now_kst = datetime.now(timezone(timedelta(hours=9)))
                if now_kst >= auto_stop_time:
                    db_utils.manage_mailbox(device_id, 0)
                    db_utils.state_table.update_item(Key={'deviceId': device_id}, UpdateExpression="remove auto_stop_time")
            except: pass
        # Check if there's a new command pending
        pending_cmd = int(state.get('pending_cmd', 0))
        if pending_cmd > 0:
            spray_code, target_region, duration = db_utils.manage_mailbox(device_id, is_peek=is_app_request)
        else:
            # If no new command, send -1 to avoid restarting the same spray and music every 15 seconds
            spray_code = -1
            target_region = state.get('current_region', "")
            duration = int(state.get('current_duration', 3))
            
        music_code = db_utils.get_music_track(device_id, spray_code if spray_code > 0 else int(state.get('current_spray', 0)), is_pump=True)
        if spray_code == -1:
            music_code = 0 # ESP32 ignores music=0 and cmd=-1
        intensity = int(state.get('intensity', 2)) 
        led_r = int(state.get('led_r', 255))
        led_g = int(state.get('led_g', 255))
        led_b = int(state.get('led_b', 255))
        led_br = int(state.get('led_br', 150))
        db_level = int(state.get('db_level', 0))
        volume = int(state.get('volume', 5)) 
        mapping_dict = db_utils.get_spray_mapping(device_id)
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "spray": int(spray_code),
                "music": int(music_code),
                "duration": int(duration),
                "target_region": target_region,
                "intensity": intensity,
                "volume": volume,
                "timer_enabled": bool(state.get('timer_enabled', False)),
                "timer_start": int(state.get('timer_start', 9)),
                "timer_end": int(state.get('timer_end', 22)),
                "led_r": led_r,
                "led_g": led_g,
                "led_b": led_b,
                "led_br": led_br,
                "led_bright": led_br,
                "db_level": db_level,
                "weights": final_weights,
                "mapping": mapping_dict,
                "result_text": "명령없음" if spray_code in [0, -1] else f"명령:{spray_code}"
            }, ensure_ascii=False)
        }
    elif action in ["MENU_STOP", "STOP_ALL"] or mode == "menu":
        db_utils.manage_mailbox(device_id, 90)
        try: db_utils.state_table.update_item(Key={'deviceId': device_id}, UpdateExpression="remove auto_stop_time")
        except: pass
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"spray": 0, "message": "정지 명령", "result_text": "정지"}, ensure_ascii=False)
        }
    elif action == "MANUAL":
        try:
            spray_code = int(body.get("spray", body.get("value", 1)))
            region_req = body.get("region", "")
            duration = int(body.get("duration", 3)) 
            db_utils.manage_mailbox(device_id, spray_code, region_req, duration)
            try: db_utils.state_table.update_item(Key={'deviceId': device_id}, UpdateExpression="remove auto_stop_time")
            except: pass
            music_code = spray_code
            if spray_code in [1, 2, 3, 4]:
                music_code = db_utils.get_music_track(device_id, spray_code, is_pump=True)
            result_text = f"수동 명령 저장: {spray_code}번 (DeviceId: {device_id})"
            state = db_utils.get_device_state(device_id) or {}
            intensity = int(state.get('intensity', 2))
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({
                    "result": "SUCCESS",
                    "spray": spray_code,
                    "duration": duration, 
                    "intensity": intensity,  
                    "result_text": result_text,
                    "message": result_text
                }, ensure_ascii=False)
            }
        except Exception as e:
            return {"statusCode": 500, "body": json.dumps({"result": "FAIL", "message": str(e)}, ensure_ascii=False)}
    elif action == "START":
        try:
            start_code = int(body.get("spray", 1))
            duration = int(body.get("duration", 3))
            region_req = body.get("region", "Manual")
            db_utils.manage_mailbox(device_id, start_code, region_req, duration)
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({
                    "result": "SUCCESS", 
                    "spray": start_code, 
                    "message": f"START 명령 수신 (ID: {device_id})",
                    "duration": duration
                }, ensure_ascii=False)
            }
        except Exception as e:
            return {"statusCode": 500, "body": str(e)}
    elif action == "TEST_VOICE":
        test_text = body.get("text", "")
        
        user_history_str = db_utils.get_user_history_text(device_id)
        active_kinds = db_utils._active_kinds(device_id)
        kind_descriptions = {
            1: "1번(시트러스: 상쾌/에너지/우울감 극복)",
            2: "2번(센달우드: 차분/집중/안정)",
            3: "3번(패츄리: 자연/깊은휴식/명상)",
            4: "4번(페퍼민트: 시원/피로해소/답답함 해소)",
            5: "5번(라벤더: 진정/수면/스트레스 완화)",
            6: "6번(바닐라: 포근/위로/외로움 해소)",
            7: "7번(무향)"
        }
        if active_kinds:
            active_kinds_str = "\n".join([kind_descriptions.get(int(k), f"{k}번(알 수 없는 향기)") for k in active_kinds])
        else:
            active_kinds_str = "장착된 향기가 없습니다."
            
        kind_code, duration, result_text, led_dict = api_utils.ask_gemini_voice_analysis(
            test_text, user_history_text=user_history_str, slot_info_str=active_kinds_str
        )
        mapped_pump, fb_msg = db_utils.get_smart_spray_mapping(device_id, kind_code)
        result_text += fb_msg
        return {
            "statusCode": 200,
            "body": json.dumps({
                "kind_code": kind_code,
                "spray_code": mapped_pump,
                "duration": duration,
                "result_text": result_text,
                "led_r": led_dict.get("led_r", 255) if led_dict else 255,
                "led_g": led_dict.get("led_g", 255) if led_dict else 255,
                "led_b": led_dict.get("led_b", 255) if led_dict else 255,
                "led_bright": led_dict.get("led_bright", 150) if led_dict else 150
            }, ensure_ascii=False)
        }
    return None
