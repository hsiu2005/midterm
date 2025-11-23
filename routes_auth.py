import hashlib

from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from db import getDB
from deps import session_user

router = APIRouter()


@router.post("/register")
async def register(
    request: Request,
    username: str = Form(...),  # 接收表單欄位 "username"
    password: str = Form(...),  # 接收表單欄位 "password"
    role: str = Form(...),      # 接收表單欄位 "role"
    conn=Depends(getDB),        # 派駐 `getDB` 保鑣
):
    # 伺服器端驗證：確保角色是 "client" 或 "contractor"
    if role not in ("client", "contractor"):
        return HTMLResponse("註冊失敗：角色錯誤<br><a href='/registerForm.html'>回註冊</a>", status_code=400)

    # 密碼雜湊(加密)
    pwd_hash = hashlib.sha256(password.encode()).hexdigest()

    async with conn.cursor() as cur:
        try:
            await cur.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s)",
                (username, pwd_hash, role),
            )
        except Exception as e:
            return HTMLResponse(
                f"註冊失敗：{e}<br><a href='/registerForm.html'>回註冊</a>",
                status_code=400,
            )
    return RedirectResponse(url="/loginForm.html", status_code=302)


@router.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    conn=Depends(getDB),
):
    pwd_hash = hashlib.sha256(password.encode()).hexdigest()
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT id, role, username FROM users WHERE username=%s AND password_hash=%s",
            (username, pwd_hash),
        )
        user = await cur.fetchone()

    if not user:
        return HTMLResponse(
            "帳號或密碼錯誤<br><a href='/loginForm.html'>重新登入</a>",
            status_code=401,
        )

    request.session["user_id"] = user["id"]
    request.session["role"] = user["role"]
    request.session["username"] = user["username"]
    return RedirectResponse(url="/", status_code=302)


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/loginForm.html", status_code=302)


@router.get("/me")
async def me(request: Request):
    try:
        # 呼叫 session_user 檢查登入狀態
        return session_user(request)
    except HTTPException:
        # 沒登入就導回登入頁
        return RedirectResponse(url="/loginForm.html", status_code=302)
