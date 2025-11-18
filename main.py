#可以把它想像成一個「智慧型總機系統」，它負責接收所有來自網頁的請求（電話），然後根據來電者是誰（Session）、他們要做什麼（API 路徑）以及他們有沒有權限（Dependencies），去資料庫（檔案室）調閱或修改資料。
#from pathlib import Path是Python 裝好就有的工具。是 Python 3 之後用來處理「檔案路徑」的最好工具。用它來定義 uploads_dir = Path("uploads")，比用傳統的 os.path.join("uploads") 更現代、更直覺。
#Imports: 匯入了所有需要的工具。
#FastAPI: 網站伺服器框架。
#Depends, Form, UploadFile: FastAPI 用來處理「依賴注入」、「網頁表單」和「檔案上傳」的工具。
#getDB: 從 db.py 匯入你寫的「連線池」功能。

from pathlib import Path
#hashlib: 用來幫密碼「加密」(雜湊) 的工具。
import hashlib
#os, shutil: 用來處理檔案（例如刪除退件的檔案）。
import os
import shutil
#uuid:匯入通用唯一辨識碼 (Universally Unique Identifier)產生器。絕對不會重複的亂數產生器，可以確保每個檔案在硬碟上都有一個獨一無二的名稱。
import uuid
#from typing import Dict, Optional，是給「程式碼編輯器」看的註解，告訴它這個變數「應該」是什麼型別。
from typing import Dict, Optional
#專門用來處理「年、月、日」的工具。
from datetime import date


# 從 FastAPI 框架匯入最核心的工具：
# - FastAPI: 你的「總機系統」主體，`app = FastAPI()` 會用到。
# - Depends: 你的「保鑣派駐系統」。`Depends(getDB)` 靠它。它告訴 API：「在執行我之前，必須先去執行 `getDB`，並把結果交給我。」
# - Form: 告訴 FastAPI：「這個參數 (例如 `username: str = Form(...)`) 不是來自 JSON，而是來自網頁的 `<form>` 表單。」
# - Request: 一個物件，裝著「這次請求的所有資訊」。你用它來存取 Session 短期記憶，例如 `request.session.get("user_id")`。
# - HTTPException: 一個標準的「丟出錯誤」的方法。`raise HTTPException(status_code=403, ...)` 會立刻停止執行並回傳錯誤。
# - UploadFile, File: `UploadFile` 和 `File` 告訴 FastAPI：「這個欄位 `report_file: UploadFile = File(...)` 不是文字，而是一個上傳的檔案。」
from fastapi import FastAPI, Depends, Form, Request, HTTPException, UploadFile, File
# 匯入 FastAPI 能回傳的「回應類型」：
# - HTMLResponse: 當你登入失敗時，用 `return HTMLResponse("帳號或密碼錯誤...")`，能直接回傳 HTML 文字給瀏覽器。
# - RedirectResponse: 重導向。`return RedirectResponse(url="/", ...)` 告訴瀏覽器：「你登入成功了，請立刻跳轉到 / 這個網址。」
# - Response: 一個通用的回應物件。你用在中介層 `add_no_cache_header` 來修改 `response.headers` (加上「禁止快取」的標頭)。
from fastapi.responses import HTMLResponse, RedirectResponse, Response
# 讓 FastAPI 可以直接提供「靜態檔案」 (如 HTML, CSS, JS, 圖片)：
# FastAPI 本身只懂 API。你必須用 `StaticFiles` 告訴它：「如果有人要 `/clientJobs.html`，你就去 `www` 資料夾直接把這個檔案傳給他。」
# 你用在哪？：在 `app.mount("/", StaticFiles(directory=str(static_dir)), ...)`，這就是你掛載 `www` 資料夾的方式。
from fastapi.staticfiles import StaticFiles
# 匯入「Session 中介層」：
# 這就是 `app.add_middleware(SessionMiddleware, ...)` 用的工具，也就是你的「短期記憶」功能本體。
# (FastAPI 底層是 `starlette` 框架，所以 Session 功能是來自 `starlette`)
from starlette.middleware.sessions import SessionMiddleware

# 從 `db.py` 檔案，匯入 `getDB` 這個你親手寫的函式：
# 這是 `main.py` 唯一需要知道的「資料庫介面」。
# `main.py` 不需要知道 `AsyncConnectionPool` 或資料庫密碼是什麼。
# 它只需要 `getDB` 這個「幫我拿一個可用連線」的工人。這讓你的程式碼很乾淨，職責分離。
from db import getDB 
# 建立你的「總機系統」 (FastAPI 應用程式) 本體。
# 之後所有的 `@app.get`, `@app.post` 都是在這個「總機系統」上註冊「分機號碼」。
app = FastAPI()

# ========== 全域防快取 ==========
# 這是「中介層」(Middleware)，它像一個警衛室。
# ＠app.middleware("http") 告訴 FastAPI：「每一個 HTTP 請求(電話)進來，都要先經過這個函式。」
@app.middleware("http")
async def add_no_cache_header(request: Request, call_next):
    # `call_next` 是「下一個動作」(也就是真正的 API 函式)。
    # `await call_next(request)`：先讓 API 函式執行，然後取得它準備要回傳的 `response`。
    response: Response = await call_next(request)
    
    # 檢查這個請求是不是在要「靜態檔案」 (static) 或「上傳的檔案」 (uploads)。
    # 這些檔案我們 *希望* 瀏覽器快取，所以就跳過。
    if not request.url.path.startswith(("/static", "/uploads", "/favicon.ico")):
        # 如果是 API 請求 (例如 /me, /client/jobs) 或 HTML 頁面：
        # 就在 response 的「標頭」(headers) 裡加上這些指令，
        # 強制告訴瀏覽器：「不要快取(cache)這個頁面！」
        # 這能確保使用者每次都能看到最新的資料（例如新的報價、新的狀態）。
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    # 把修改完的 response 回傳給使用者。
    return response

# ========== Session ==========
# 再次使用 `add_middleware` 來加上「Session 功能」。
# 這就是網站的「短期記憶」系統。
# 用來跨頁面「記住」使用者登入狀態的必要工具。
app.add_middleware(
    SessionMiddleware,
    secret_key="mysecretkey",  # 測試用，一個用來加密 Session Cookie 的密鑰，正式上線時應換成隨機長字串。
    same_site="lax",  #Cookie 安全策略，"lax" 是最常用且平衡的設定。
    https_only=False,  #測試時設為 False，允許 HTTP。正式上線(用 HTTPS)時應設為 True。
)

# ========== 共用：登入/權限 ==========
# 這區定義了 API 的「保鑣」(Dependencies - 依賴)。
# 這是一個「依賴函式」，用來檢查「是否登入」。
def session_user(request: Request) -> Dict:
    # 從 `request.session` (短期記憶) 中試著拿出 user_id, role, username。
    uid = request.session.get("user_id")
    role = request.session.get("role")
    username = request.session.get("username")
    # 如果 `uid` 是 None (表示沒登入)：
    if not uid:
        # 立刻丟出 401 錯誤 (未授權)。
        # FastAPI 會攔截這個錯誤，並回傳 401 給瀏覽器。
        # 前端的 fetchJSON 函式看到 401 就會自動跳轉到登入頁。
        raise HTTPException(status_code=401, detail="Not authenticated")
        
    # 如果有登入，就把使用者資料(字典)回傳。
    return {"user_id": uid, "role": role, "username": username}

# 這是一個「依賴工廠」(Factory)，用來「製造」檢查角色的保鑣。
def require_role(expected_role: str):
    # `expected_role` (例如 "client") 是你從 API 傳入的。
    # `dep` 函式是真正會被 `Depends()` 呼叫的「保鑣本人」。
    def dep(user=Depends(session_user)):
        # 1. (自動)：`Depends(session_user)` 會先執行，確保使用者「有登入」。
        #    如果沒登入，`session_user` 會先丟出 401，根本走不到下面這行。
        # 2. (檢查角色)：如果 `user["role"]` (例如 "contractor")
        #    不等於 `expected_role` (例如 "client")：
        if user["role"] != expected_role:
            # 丟出 403 錯誤 (禁止存取)。
            raise HTTPException(status_code=403, detail="Forbidden")
        # 3. (通過)：如果角色正確，回傳使用者資料。
        return user
    # `require_role` 函式最後會回傳 `dep` 這個保鑣函式。
    return dep

# ========== 認證：註冊 / 登入 / 登出 / 我是誰 ==========
# 處理使用者「大門」的 API。
# 註冊 API：綁定到 /register 網址，只接受 POST 表單請求。
@app.post("/register")
async def register(
    request: Request,
    username: str = Form(...),# 接收表單欄位 "username"
    password: str = Form(...),# 接收表單欄位 "password"
    role: str = Form(...),# 接收表單欄位 "role"
    conn=Depends(getDB),# 派駐 `getDB` 保鑣：給我一個資料庫連線，並命名為 `conn`
):
    # 方便測試：不做長度限制；只檢查角色值
    # 伺服器端驗證：確保角色是 "client" 或 "contractor"
    if role not in ("client", "contractor"):
        return HTMLResponse("註冊失敗：角色錯誤<br><a href='/registerForm.html'>回註冊</a>", status_code=400)

    # 密碼雜湊(加密)：使用 sha256 演算法
    pwd_hash = hashlib.sha256(password.encode()).hexdigest()
    
    # `async with conn.cursor() as cur:`：從 `conn` (連線) 取得一個「游標」(cur)。
    # 「游標」是實際執行 SQL 指令的工具。`async with` 確保它用完會自動關閉。
    async with conn.cursor() as cur:
        try:
            # `await cur.execute(...)`：非同步執行 SQL "INSERT" 指令。
            await cur.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s)",
                (username, pwd_hash, role),
            )
        except Exception as e:
            # 如果 `INSERT` 失敗 (例如 `username` 重複)，資料庫會報錯。
            # `try...except` 會捕捉這個錯誤 `e`，並回傳 400 錯誤訊息。
            return HTMLResponse(
                
                f"註冊失敗：{e}<br><a href='/registerForm.html'>回註冊</a>",
                status_code=400,
            )
    # 註冊成功，重導向到登入頁面。
    return RedirectResponse(url="/loginForm.html", status_code=302)

# 登入 API：綁定到 /login 網址，只接受 POST 表單請求。
@app.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    conn=Depends(getDB),
):
    # 方便測試：不做長度限制，只做雜湊比對
    # 用「完全一樣」的演算法雜湊一次使用者輸入的密碼。
    pwd_hash = hashlib.sha256(password.encode()).hexdigest()
    async with conn.cursor() as cur:
        # `SELECT` (查詢) 資料庫，看有沒有「帳號」和「雜湊後的密碼」都相符的紀錄。
        await cur.execute(
            "SELECT id, role, username FROM users WHERE username=%s AND password_hash=%s",
            (username, pwd_hash),
        )
        # `await cur.fetchone()`：抓取「第一筆」符合的資料。
        user = await cur.fetchone()
    # `if not user`：如果 `user` 是 `None` (表示沒抓到資料)：
    if not user:
        # 回傳 401 錯誤 (帳號或密碼錯誤)。
        return HTMLResponse(
            "帳號或密碼錯誤<br><a href='/loginForm.html'>重新登入</a>",
            status_code=401,
        )
    # --- 登入成功的核心 ---
    # `user` 是一個字典 (因為 `db.py` 設定了 `dict_row`)。
    # 把 `user['id']` 和 `user['role']` 存進 `request.session` (短期記憶)。
    request.session["user_id"] = user["id"]
    request.session["role"] = user["role"]
    request.session["username"] = user["username"]
    # 存完 Session 後，重導向到首頁。
    return RedirectResponse(url="/", status_code=302)
# 登出 API：綁定到 /logout 網址。
@app.get("/logout")
async def logout(request: Request):
    # `request.session.clear()`：清除這個使用者的所有 Session (短期記憶)。
    request.session.clear()
    # 重導向到登入頁。
    return RedirectResponse(url="/loginForm.html", status_code=302)

# 取得個人資訊 API：綁定到 /me 網址。
@app.get("/me")
async def me(request: Request):
    try:
        # 這裡不直接寫邏輯，而是呼叫 `session_user` 函式。
        # 1. `session_user` 會檢查登入狀態。
        # 2. 如果沒登入，`session_user` 會丟出 401 錯誤。
        # 3. `try...except` 會捕捉到這個 401 錯誤。
        return session_user(request)
    except HTTPException:
        # 4. 如果捕捉到錯誤 (表示沒登入)，就重導向到登入頁。
        return RedirectResponse(url="/loginForm.html", status_code=302)

# ========== 首頁導向 ==========
# 綁定到網站根目錄 `/`
@app.get("/")
async def index(request: Request):
    # 檢查 Session (短期記憶)
    uid = request.session.get("user_id")
    role = request.session.get("role")
    # 如果沒登入，導向登入頁
    if not uid:
        return RedirectResponse(url="/loginForm.html", status_code=302)
    # 如果有登入，根據 `role` 導向各自的首頁。
    return RedirectResponse(url="/clientJobs.html" if role == "client" else "/contractorMyJobs.html", status_code=302)

# ========== 委託人（client） ==========
# [新增 API] 取得承包人列表 (for 邀請)
# 綁定到 /contractors/list 網址
@app.get("/contractors/list")
async def get_contractors_list(
    # 派駐「角色保鑣」：必須是 "client" 才能呼叫。
    user=Depends(require_role("client")), 
    conn=Depends(getDB)# 派駐「資料庫保鑣」
):
    async with conn.cursor() as cur:
        # `SELECT` (查詢) `users` 表中所有 `role` 是 'contractor' 的人。
        await cur.execute(
            "SELECT id, username FROM users WHERE role = 'contractor' ORDER BY username"
        )
        # `await cur.fetchall()`：抓取「所有」符合的資料。
        rows = await cur.fetchall()
    # 把查詢結果 `rows` (一個字典的列表) 包成 JSON 回傳。
    return {"items": rows}
    
# 取得委託人自己的案件列表
@app.get("/client/jobs")
async def client_jobs(user=Depends(require_role("client")), conn=Depends(getDB)):
    # `user` 變數是 `require_role` 保鑣回傳的 (包含 user_id, role)。
    uid = user["user_id"]
    # 執行 SQL 查詢
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT j.id, j.title, j.status, j.created_at,
                   COALESCE((SELECT COUNT(*) FROM bids b WHERE b.job_id = j.id), 0) AS bid_count,
                   u_con.username AS contractor_name
            FROM jobs j
            LEFT JOIN users u_con ON j.contractor_id = u_con.id
            WHERE j.client_id = %s
            ORDER BY j.id DESC
            """,
            (uid,),
        )
        rows = await cur.fetchall()
    return {"owner": uid, "count": len(rows), "items": rows}

# [修改 API] 建立案件
@app.post("/job/new")
async def job_new(
    request: Request,
    title: str = Form(...),
    content: str = Form(...),
    budget_str: Optional[str] = Form(None),# `Optional[str]` 代表這是選填。
    due_date_str: Optional[str] = Form(None),# `Optional[str]` 代表這是選填。
    invited_contractor_id_str: Optional[str] = Form(None), # [新欄位]
    user=Depends(require_role("client")),
    conn=Depends(getDB),
):
    client_id = user["user_id"]
    client_username = user["username"]

    # --- 伺服器端驗證 (Validation) ---
    # 檢查標題和內容長度
    # 基本驗證（方便測試：範圍寬鬆）
    if not (1 <= len(title) <= 100) or not (1 <= len(content) <= 5000):
        return HTMLResponse("建立失敗：標題或內容長度不符", status_code=400)

    # 處理 `budget` (預算)
    budget: Optional[int] = None
    if budget_str and budget_str.strip():# .strip() 去除前後空白
        try:
            budget = int(budget_str)# 轉成整數
            if budget < 0 or budget > 999_999_999:
                raise ValueError()
        except:
            return HTMLResponse("建立失敗：預算需為 0~999,999,999", status_code=400)

    # 處理 `due_date` (截止日)
    due_date: Optional[date] = None
    if due_date_str and due_date_str.strip():
        try:
            # `date.fromisoformat` 把 "YYYY-MM-DD" 字串轉成 `date` 物件
            due_date = date.fromisoformat(due_date_str)
        except:
            return HTMLResponse("建立失敗：截止日格式須為 YYYY-MM-DD", status_code=400)

    # [新邏輯] 處理邀請
    invited_contractor_id: Optional[int] = None
    if invited_contractor_id_str and invited_contractor_id_str.strip():
        try:
            invited_contractor_id = int(invited_contractor_id_str)
            if invited_contractor_id == client_id:
                raise ValueError("不能邀請自己")
        except:
            return HTMLResponse("建立失敗：邀請的承包人 ID 錯誤", status_code=400)

    try:
        # `async with conn.transaction():`
        # *** 啟動「資料庫事務 (Transaction)」 ***
        # 這會把底下的 SQL 操作包成一個「交易包」。
        # 裡面的指令 (INSERT jobs, INSERT job_events) 必須「全部成功」或「全部失敗」。
        # 如果 `INSERT job_events` 失敗，`INSERT jobs` 會自動「復原 (Rollback)」，
        # 確保資料庫不會有「建立了案件卻沒有日誌」的髒資料。
        async with conn.transaction():
            async with conn.cursor() as cur:
                
                # 預設為「公開」案件
                job_status = 'pending'
                contractor_id_to_insert = None
                event_type = 'JOB_CREATED'
                event_msg = f"案件「{title}」"
                event_desc = f"委託人 {client_username} 建立了新案件「{title}」"

                # 如果「有」指定邀請人：
                if invited_contractor_id:
                    # 驗證受邀者是否存在且為承包人
                    await cur.execute("SELECT username FROM users WHERE id = %s AND role = 'contractor'", (invited_contractor_id,))
                    invited_user = await cur.fetchone()
                    if not invited_user:
                        return HTMLResponse("建立失敗：邀請的承包人不存在", status_code=400)
                    
                    # 覆蓋預設值，改為「邀請」案件
                    job_status = 'invited'
                    contractor_id_to_insert = invited_contractor_id
                    event_type = 'JOB_INVITED'
                    event_msg = f"邀請 {invited_user['username']}"
                    event_desc = f"委託人 {client_username} 邀請 {invited_user['username']} 承接案件「{title}」"

                # 執行第一個 SQL：INSERT 案件
                await cur.execute(
                    """
                    INSERT INTO jobs (title, content, client_id, status, budget, due_date, contractor_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (title, content, client_id, job_status, budget, due_date, contractor_id_to_insert),
                )
                row = await cur.fetchone()# 取得 `RETURNING id` 的結果
                job_id = row["id"]# 取得新案件的 ID

                # 執行第二個 SQL：INSERT 日誌
                await cur.execute(
                    """
                    INSERT INTO job_events (job_id, actor_id, event_type, message, description)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (job_id, client_id, event_type, event_msg, event_desc),
                )
        # `async with conn.transaction():` 區塊結束。
        # 如果程式能走到這裡，代表「交易包」中的所有 SQL 都成功了，資料庫會自動「提交 (Commit)」。
        return RedirectResponse(url="/clientJobs.html", status_code=302)
    except Exception as e:
        # 如果「交易包」中有任何錯誤，程式會跳到這裡，
        # `transaction` 會自動「復原 (Rollback)」，
        # 並且回傳 500 伺服器錯誤。
        return HTMLResponse(f"建立案件失敗：{e}", status_code=500)

@app.post("/bid/accept")
async def bid_accept(
    request: Request,
    job_id: int = Form(...),
    bid_id: int = Form(...),
    user=Depends(require_role("client")),
    conn=Depends(getDB),
):
    client_id = user["user_id"]
    client_username = user["username"]

    try:
        async with conn.transaction():
            async with conn.cursor() as cur:
                # 鎖住案件，確認歸屬與狀態 (必須是 pending)
                await cur.execute(
                    "SELECT id FROM jobs WHERE id = %s AND client_id = %s AND status = 'pending' FOR UPDATE",
                    (job_id, client_id)
                )
                job = await cur.fetchone()
                if not job:
                    raise HTTPException(status_code=403, detail="Job not found, not yours, or not in 'pending' state.")

                # 以 bid_id 反查 contractor
                await cur.execute(
                    "SELECT contractor_id, price FROM bids WHERE id=%s AND job_id=%s",
                    (bid_id, job_id)
                )
                bid = await cur.fetchone()
                if not bid:
                    raise HTTPException(status_code=404, detail="Bid not found for this job.")

                contractor_id = bid["contractor_id"]

                await cur.execute("SELECT username FROM users WHERE id = %s", (contractor_id,))
                contractor = await cur.fetchone()
                contractor_username = contractor["username"] if contractor else f"#{contractor_id}"

                await cur.execute(
                    "UPDATE jobs SET status = 'accepted', contractor_id = %s, updated_at = NOW() WHERE id = %s",
                    (contractor_id, job_id)
                )

                await cur.execute(
                    """
                    INSERT INTO job_events (job_id, actor_id, event_type, message, description)
                    VALUES (%s, %s, 'BID_SELECTED', %s, %s)
                    """,
                    (job_id, client_id, f"報價 #{bid_id}", f"委託人 {client_username} 選擇了承包人 {contractor_username} (報價ID: {bid_id}, 價格: {bid['price']})")
                )
    except HTTPException as e:
        return HTMLResponse(f"選標失敗：{e.detail}", status_code=e.status_code)
    except Exception as e:
        return HTMLResponse(f"選標失敗，伺服器錯誤：{e}", status_code=500)

    return RedirectResponse(url=f"/jobDetail.html?job_id={job_id}", status_code=302)

# ========== 承包人（contractor） ==========
@app.get("/contractor/jobs")
async def contractor_jobs(user=Depends(require_role("contractor")), conn=Depends(getDB)):
    contractor_id = user["user_id"]
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT
                j.id, j.title, j.status, j.created_at,
                u.username AS client_name,
                COALESCE(bc.cnt, 0) AS bid_count,
                mb.price AS my_bid_price
            FROM jobs j
            JOIN users u ON u.id = j.client_id
            LEFT JOIN LATERAL (
                SELECT COUNT(*)::int AS cnt FROM bids b WHERE b.job_id = j.id
            ) bc ON TRUE
            LEFT JOIN LATERAL (
                SELECT price FROM bids WHERE job_id = j.id AND contractor_id = %s LIMIT 1
            ) mb ON TRUE
            WHERE j.status = 'pending'
              AND j.client_id <> %s
            ORDER BY j.id DESC
            """,
            (contractor_id, contractor_id),
        )
        rows = await cur.fetchall()
    return {"contractor": contractor_id, "count": len(rows), "items": rows}

@app.post("/bid/new")
async def bid_new(
    request: Request,
    job_id: int = Form(...),
    price: int = Form(...),
    note: str = Form(""),
    user=Depends(require_role("contractor")),
    conn=Depends(getDB),
):
    contractor_id = user["user_id"]
    contractor_username = user["username"]

    if price < 0 or price > 999_999_999:
        return HTMLResponse(
            f"建立/更新報價失敗：金額需為 0~999,999,999<br><a href='/bidForm.html?job_id={job_id}'>回上一頁</a>",
            status_code=400,
        )
    try:
        async with conn.transaction():
            async with conn.cursor() as cur:
                # 驗證 job 開放中 (pending)，且不是自己的案
                await cur.execute("SELECT client_id, status FROM jobs WHERE id=%s FOR UPDATE", (job_id,))
                job = await cur.fetchone()
                if not job:
                    raise HTTPException(status_code=404, detail="Job not found")
                if job["status"] != "pending":
                    raise HTTPException(status_code=400, detail="此案件不開放投標")
                if job["client_id"] == contractor_id:
                    raise HTTPException(status_code=400, detail="不能投標自己的案件")

                await cur.execute(
                    """
                    INSERT INTO bids (job_id, contractor_id, price, note)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (job_id, contractor_id)
                    DO UPDATE SET price = EXCLUDED.price, note = EXCLUDED.note
                    """,
                    (job_id, contractor_id, price, note),
                )

                await cur.execute(
                    """
                    INSERT INTO job_events (job_id, actor_id, event_type, message, description)
                    VALUES (%s, %s, 'BID_SUBMITTED', %s, %s)
                    """,
                    (job_id, contractor_id, f"報價 ${price}", f"承包人 {contractor_username} 報價 ${price}。備註：{note}")
                )
    except HTTPException as e:
        return HTMLResponse(
            f"建立/更新報價失敗：{e.detail}<br><a href='/bidForm.html?job_id={job_id}'>回上一頁</a>",
            status_code=e.status_code,
        )
    except Exception as e:
        # [修正] 修正錯字 失败 -> 失敗
        return HTMLResponse(
            f"建立/更新報價失敗：{e}<br><a href='/bidForm.html?job_id={job_id}'>回上一頁</a>",
            status_code=500,
        )
    return RedirectResponse(url="/contractorMyJobs.html", status_code=302)

#給承包商用來查看「我投標的」和「我贏得的」所有工作的 API。
@app.get("/contractor/my-jobs")
async def contractor_my_jobs(user=Depends(require_role("contractor")), conn=Depends(getDB)):
    contractor_id = user["user_id"]
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT 
                j.id, j.title, j.status, j.updated_at,
                u.username AS client_name,
                b.price AS my_bid_price,
                (j.contractor_id = %s) AS am_i_winner
            FROM jobs j
            LEFT JOIN bids b ON b.job_id = j.id AND b.contractor_id = %s
            JOIN users u ON u.id = j.client_id
            WHERE (b.contractor_id = %s) OR (j.contractor_id = %s AND j.status <> 'invited')
            GROUP BY j.id, u.username, b.price
            ORDER BY j.updated_at DESC
            """,
            (contractor_id, contractor_id, contractor_id, contractor_id),
        )
        rows = await cur.fetchall()
    return {"contractor": contractor_id, "count": len(rows), "items": rows}

# [新增 API] 承包人：查看我的邀請
@app.get("/contractor/my-invitations")
async def contractor_my_invitations(user=Depends(require_role("contractor")), conn=Depends(getDB)):
    contractor_id = user["user_id"]
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT 
                j.id, j.title, j.budget, j.due_date, j.created_at,
                u.username AS client_name
            FROM jobs j
            JOIN users u ON u.id = j.client_id
            WHERE j.status = 'invited' 
              AND j.contractor_id = %s
            ORDER BY j.created_at DESC
            """,
            (contractor_id,),
        )
        rows = await cur.fetchall()
    return {"items": rows}

# [新增 API] 承包人：接受邀請
@app.post("/invitation/accept")
async def invitation_accept(
    job_id: int = Form(...),
    user=Depends(require_role("contractor")), 
    conn=Depends(getDB)
):
    contractor_id = user["user_id"]
    contractor_username = user["username"]
    
    try:
        async with conn.transaction():
            async with conn.cursor() as cur:
                # 驗證案件是否為 'invited' 且 'contractor_id' 是自己
                await cur.execute(
                    "SELECT 1 FROM jobs WHERE id = %s AND contractor_id = %s AND status = 'invited' FOR UPDATE",
                    (job_id, contractor_id)
                )
                job = await cur.fetchone()
                if not job:
                    raise HTTPException(status_code=403, detail="Invitation not found or not for you.")
                
                # 更新案件狀態
                await cur.execute(
                    "UPDATE jobs SET status = 'accepted', updated_at = NOW() WHERE id = %s",
                    (job_id,)
                )
                
                # 記錄事件
                await cur.execute(
                    """
                    INSERT INTO job_events (job_id, actor_id, event_type, message, description)
                    VALUES (%s, %s, 'INVITE_ACCEPTED', %s, %s)
                    """,
                    (job_id, contractor_id, "接受邀請", f"承包人 {contractor_username} 接受了案件邀請。")
                )
    except Exception as e:
        return HTMLResponse(f"接受邀請失敗：{e}", status_code=500)

    # 接受後，導向詳情頁（在那裡可以上傳檔案）
    return RedirectResponse(url=f"/jobDetail.html?job_id={job_id}", status_code=302)

# [新增 API] 承包人：婉拒邀請
@app.post("/invitation/decline")
async def invitation_decline(
    job_id: int = Form(...),
    user=Depends(require_role("contractor")), 
    conn=Depends(getDB)
):
    contractor_id = user["user_id"]
    contractor_username = user["username"]
    
    try:
        async with conn.transaction():
            async with conn.cursor() as cur:
                # 驗證案件是否為 'invited' 且 'contractor_id' 是自己
                await cur.execute(
                    "SELECT 1 FROM jobs WHERE id = %s AND contractor_id = %s AND status = 'invited' FOR UPDATE",
                    (job_id, contractor_id)
                )
                job = await cur.fetchone()
                if not job:
                    raise HTTPException(status_code=403, detail="Invitation not found or not for you.")
                
                # 更新案件狀態 -> 'pending' (公開), 並移除 contractor_id
                await cur.execute(
                    "UPDATE jobs SET status = 'pending', contractor_id = NULL, updated_at = NOW() WHERE id = %s",
                    (job_id,)
                )
                
                # 記錄事件
                await cur.execute(
                    """
                    INSERT INTO job_events (job_id, actor_id, event_type, message, description)
                    VALUES (%s, %s, 'INVITE_DECLINED', %s, %s)
                    """,
                    (job_id, contractor_id, "婉拒邀請", f"承包人 {contractor_username} 婉拒了案件邀請，案件轉為公開。")
                )
    except Exception as e:
        return HTMLResponse(f"婉拒邀請失敗：{e}", status_code=500)

    # 婉拒後，導回「我的邀請」列表
    return RedirectResponse(url="/contractorMyInvitations.html", status_code=302)


# ========== 通用：案件詳情 ==========
@app.get("/job/{job_id}/detail")
async def get_job_detail(job_id: int, user=Depends(session_user), conn=Depends(getDB)):
    user_id = user["user_id"]

    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT j.*, u.username AS client_name, u_con.username AS contractor_name
            FROM jobs j
            JOIN users u ON u.id = j.client_id
            LEFT JOIN users u_con ON j.contractor_id = u_con.id
            WHERE j.id = %s
            """,
            (job_id,)
        )
        job = await cur.fetchone()
        if not job:
            # [修正] 狀態碼 44 -> 404
            raise HTTPException(status_code=404, detail="Job not found")

        # 判斷我對此案的身分
        user_job_role = "visitor"
        if job["client_id"] == user_id:
            user_job_role = "client"
        elif job["contractor_id"] == user_id:
            # [修改] 如果我是 contractor_id，可能是 "invited" 或 "accepted" / "rejected" / "uploaded" / "closed" 狀態
            user_job_role = "contractor" # "contractor" 泛指得標者或被邀請者
        elif user["role"] == "contractor":
            await cur.execute("SELECT 1 FROM bids WHERE job_id = %s AND contractor_id = %s", (job_id, user_id))
            bid_exists = await cur.fetchone()
            if job["status"] == 'pending' or bid_exists:
                user_job_role = "visitor_contractor" # "visitor_contractor" 泛指潛在或已投標的承包人

        if user_job_role == "visitor":
            raise HTTPException(status_code=403, detail="Forbidden: You do not have access to this job.")

        bids = []
        winning_bid = None # "winning_bid" 用來儲存投標的報價

        if user_job_role == "client":
            if job["status"] == 'pending':
                await cur.execute(
                    """
                    SELECT b.id, b.price, b.note, b.contractor_id, u.username AS contractor_name, b.created_at
                    FROM bids b
                    JOIN users u ON u.id = b.contractor_id
                    WHERE b.job_id = %s
                    ORDER BY b.price ASC
                    """,
                    (job_id,)
                )
                bids = await cur.fetchall()
            elif job["status"] != 'pending' and job["status"] != 'invited':
                # [修改] 如果不是 pending 也不是 invited (例如 accepted, closed...)
                # 且 contractor_id 存在時，去 bids 表撈報價（如果他是投標來的）
                if job["contractor_id"]:
                    await cur.execute(
                        """
                        SELECT b.id, b.price, b.note, u.username AS contractor_name
                        FROM bids b
                        JOIN users u ON b.contractor_id = u.id
                        WHERE b.job_id = %s AND b.contractor_id = %s
                        LIMIT 1
                        """,
                        (job_id, job["contractor_id"])
                    )
                    winning_bid = await cur.fetchone()
            # 如果是 invited 狀態，bids 列表為空，winning_bid 也為 None (因為還沒報價)

        elif user_job_role in ("contractor", "visitor_contractor"):
            # 承包人（得標/被邀請/潛在）都只看自己的報價
            await cur.execute(
                """
                SELECT b.id, b.price, b.note, b.contractor_id, u.username AS contractor_name, b.created_at
                FROM bids b
                JOIN users u ON u.id = b.contractor_id
                WHERE b.job_id = %s AND b.contractor_id = %s
                """,
                (job_id, user_id)
            )
            bids = await cur.fetchall()
            if user_job_role == "contractor" and bids:
                winning_bid = bids[0] # 如果我是得標者且我有報價

        last_rejection = None
        # [修改] 改為在 'rejected' 狀態下檢查
        if user_job_role == "contractor" and job["status"] == "rejected":
            await cur.execute(
                "SELECT message FROM job_events WHERE job_id = %s AND event_type = 'JOB_REJECTED' ORDER BY created_at DESC LIMIT 1",
                (job_id,)
            )
            last_rejection = await cur.fetchone()

    # job 物件中已包含 contractor_name (可能是得標者或被邀請者)
    return {"job": job, "bids": bids, "user_job_role": user_job_role, "last_rejection": last_rejection, "winning_bid": winning_bid}

# ========== 承包人上傳檔案 ==========
@app.post("/job/upload")
async def job_upload(
    user=Depends(require_role("contractor")),
    job_id: int = Form(...),
    report_file: UploadFile = File(...),
    conn=Depends(getDB)
):
    contractor_id = user["user_id"]
    contractor_username = user["username"]

    # 白名單（測試友善）
    ext = os.path.splitext(report_file.filename)[1].lower()
    if ext not in [".pdf", ".zip", ".docx", ".pptx"]:
        return HTMLResponse("上傳失敗：檔案類型不允許（限 pdf/zip/docx/pptx）", status_code=400)

    uploads_dir = Path("uploads")
    uploads_dir.mkdir(exist_ok=True)

    try:
        async with conn.transaction():
            async with conn.cursor() as cur:
                # [修改] 允許 'accepted' 或 'rejected' 狀態時上傳
                await cur.execute(
                    "SELECT id FROM jobs WHERE id = %s AND contractor_id = %s AND (status = 'accepted' OR status = 'rejected') FOR UPDATE",
                    (job_id, contractor_id)
                )
                job = await cur.fetchone()
                if not job:
                    # [修改] 更新錯誤訊息
                    raise HTTPException(status_code=403, detail="Job not found, not assigned to you, or not in 'accepted'/'rejected' state.")

                await cur.execute(
                    "SELECT 1 FROM job_events WHERE job_id = %s AND event_type = 'JOB_REJECTED' LIMIT 1",
                    (job_id,)
                )
                is_re_upload = await cur.fetchone()

                safe_filename = f"job_{job_id}_user_{contractor_id}_{uuid.uuid4().hex}{ext}"
                file_path = uploads_dir / safe_filename
                try:
                    with file_path.open("wb") as buffer:
                        shutil.copyfileobj(report_file.file, buffer)
                finally:
                    report_file.file.close()

                await cur.execute(
                    "UPDATE jobs SET status = 'uploaded', report_file = %s, updated_at = NOW() WHERE id = %s",
                    (safe_filename, job_id)
                )

                event_type = "REPORT_RE_UPLOADED" if is_re_upload else "REPORT_UPLOADED"
                msg = ("重新上傳檔案 " if is_re_upload else "檔案 ") + report_file.filename
                desc = f"承包人 {contractor_username} {'重新' if is_re_upload else ''}上傳了檔案：{report_file.filename}"

                await cur.execute(
                    """
                    INSERT INTO job_events (job_id, actor_id, event_type, message, description)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (job_id, contractor_id, event_type, msg, desc)
                )

    except HTTPException as e:
        return HTMLResponse(f"上傳失敗：{e.detail}", status_code=e.status_code)
    except Exception as e:
        return HTMLResponse(f"上傳失敗，伺服器錯誤：{e}", status_code=500)

    return RedirectResponse(url=f"/jobDetail.html?job_id={job_id}", status_code=302)

# ========== 委託人驗收/退件 ==========
@app.post("/job/review")
async def job_review(
    user=Depends(require_role("client")),
    job_id: int = Form(...),
    decision: str = Form(...),
    message: str = Form(""),
    conn=Depends(getDB)
):
    client_id = user["user_id"]
    if decision not in ['closed', 'rejected']:
        raise HTTPException(status_code=400, detail="Invalid decision.")

    uploads_dir = Path("uploads")
    try:
        async with conn.transaction():
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id, report_file FROM jobs WHERE id = %s AND client_id = %s AND status = 'uploaded' FOR UPDATE",
                    (job_id, client_id)
                )
                job = await cur.fetchone()
                if not job:
                    raise HTTPException(status_code=403, detail="Job not found, not yours, or not in 'uploaded' state.")

                if decision == 'rejected':
                    # [修改] 將狀態更新為 'rejected'
                    await cur.execute(
                        "UPDATE jobs SET status = 'rejected', report_file = NULL, updated_at = NOW() WHERE id = %s",
                        (job_id,)
                    )
                    if job.get("report_file"):
                        try:
                            os.remove(uploads_dir / job["report_file"])
                        except OSError:
                            pass

                    await cur.execute(
                        """
                        INSERT INTO job_events (job_id, actor_id, event_type, message, description)
                        VALUES (%s, %s, 'JOB_REJECTED', %s, %s)
                        """,
                        (job_id, client_id, message, f"委託人 {user['username']} 退件。理由：{message}")
                    )

                else:  # 'closed'
                    await cur.execute(
                        "UPDATE jobs SET status = %s, updated_at = NOW() WHERE id = %s",
                        (decision, job_id)
                    )
                    await cur.execute(
                        """
                        INSERT INTO job_events (job_id, actor_id, event_type, message, description)
                        VALUES (%s, %s, 'JOB_CLOSED', %s, %s)
                        """,
                        (job_id, client_id, "驗收結案", f"委託人 {user['username']} 驗收結案。")
                    )
    except HTTPException as e:
        return HTMLResponse(f"審核失敗：{e.detail}", status_code=e.status_code)
    except Exception as e:
        return HTMLResponse(f"審核失敗，伺服器錯誤：{e}", status_code=500)

    return RedirectResponse(url=f"/jobDetail.html?job_id={job_id}", status_code=302)

# ========== 歷史紀錄 ==========
@app.get("/history")
async def get_history(user=Depends(session_user), conn=Depends(getDB)):
    user_id = user["user_id"]
    role = user["role"]

    if role == "client":
        query = """
            SELECT e.*, j.title AS job_title, u.username AS actor_name
            FROM job_events e
            JOIN jobs j ON e.job_id = j.id
            LEFT JOIN users u ON e.actor_id = u.id
            WHERE j.client_id = %s
            ORDER BY e.created_at DESC
            """
        params = (user_id,)
    else:
        query = """
            SELECT e.*, j.title AS job_title, u.username AS actor_name
            FROM job_events e
            JOIN jobs j ON e.job_id = j.id
            LEFT JOIN users u ON e.actor_id = u.id
            WHERE e.job_id IN (
                SELECT DISTINCT job_id FROM bids WHERE contractor_id = %s
                UNION
                SELECT DISTINCT id FROM jobs WHERE contractor_id = %s
            )
            AND (
                e.event_type <> 'BID_SUBMITTED'
                OR (e.event_type = 'BID_SUBMITTED' AND e.actor_id = %s)
            )
            ORDER BY e.created_at DESC
            """
        params = (user_id, user_id, user_id)

    async with conn.cursor() as cur:
        await cur.execute(query, params)
        events = await cur.fetchall()

    return {"items": events}

# ========== 靜態檔案 ==========
uploads_dir = Path("uploads")
uploads_dir.mkdir(exist_ok=True)
app.mount("/uploads", StaticFiles(directory=uploads_dir), name="uploads")

static_dir = Path("www")
static_dir.mkdir(exist_ok=True)
app.mount("/", StaticFiles(directory=str(static_dir)), name="static")

# ========== （可選）關閉連線池 ==========
try:
     from db import close_pool
     @app.on_event("shutdown")
     async def _shutdown():
         await close_pool()
except Exception:
     pass