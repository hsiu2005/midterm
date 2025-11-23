from typing import Dict

from fastapi import Depends, HTTPException, Request


def session_user(request: Request) -> Dict:
    uid = request.session.get("user_id")
    role = request.session.get("role")
    username = request.session.get("username")
    # 如果 `uid` 是 None (表示沒登入)：
    if not uid:
        raise HTTPException(status_code=401, detail="Not authenticated")
    # 如果有登入，就把使用者資料(字典)回傳。
    return {"user_id": uid, "role": role, "username": username}


def require_role(expected_role: str):
    # `expected_role` (例如 "client") 是你從 API 傳入的。
    # `dep` 函式是真正會被 `Depends()` 呼叫的「保鑣本人」。
    def dep(user=Depends(session_user)):
        # 先確保有登入，然後檢查角色
        if user["role"] != expected_role:
            # 丟出 403 錯誤 (禁止存取)。
            raise HTTPException(status_code=403, detail="Forbidden")
        # 角色正確就回傳 user
        return user
    return dep
