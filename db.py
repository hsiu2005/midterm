from psycopg_pool import AsyncConnectionPool  # 使用 connection pool，匯入的不是psycopg單一連線，而是psycopg_pool連線池
# Async 這個字首代表是非同步，才能跟async def的FastAPI完美配合，不會卡住伺服器
from psycopg.rows import dict_row             
#是輔助工具，預設情況下，psycopg 查詢資料庫會元組 (tuple)，必須用 row[0], row[1] 這種方式存取資料。
#dict_row 會讓查詢結果變成字典，方便用 row['id'], row['username'] 這種更直覺的方式存取。

# db.py
defaultDB = "midterm" #基本連線資訊
dbUser = "postgres"
dbPassword = "81305"
dbHost = "localhost"
dbPort = 5432

#postgresql的連線字串，把上面那幾個資料合併起來，讓 Python 知道怎麼連進資料庫。
#把設定的 dbUser, dbPassword 等變數組合成一個標準的連線字串(DSN)，psycopg_pool 才知道要連線到哪一台資料庫。
DATABASE_URL = f"dbname={defaultDB} user={dbUser} password={dbPassword} host={dbHost} port={dbPort}"
# DATABASE_URL = f"postgresql://{dbUser}:{dbPassword}@{dbHost}:{dbPort}/{defaultDB}"

#宣告 _pool 是一個全域變數，用來存整個 app 的連線池物件。
#None 表示一開始還沒建立。
#| None = None: 一開始是 None。代表連線池並不是在程式一啟動時就建立，而是延遲建立 (Lazy Creation)。
_pool: AsyncConnectionPool | None = None

#取得 DB 連線物件
#是整個檔案的核心，也是 main.py 中 Depends(getDB) 實際呼叫的地方。
async def getDB():
    global _pool
    if _pool is None:
        # lazy create, 等到 main.py 來呼叫時再啟用 _pool，好處是啟動伺服器時不會浪費連線資源。
        _pool = AsyncConnectionPool(
            conninfo=DATABASE_URL,
            kwargs={"row_factory": dict_row},  #把 dict_row 功能加進去的地方，讓這個池子所有的查詢預設都回傳字典。
            open=False  # 不直接開啟
        )
        await _pool.open()  #建立並開啟連線池。
    # 使用 with context manager，當結束時自動關閉連線
    async with _pool.connection() as conn: #每當 FastAPI 執行一個請求、依賴 getDB 時，就會從連線池取一個連線，執行 SQL，自動歸還給池子，能避免連線洩漏
        #_pool.connection()：這行指令會向連線池要一個可用的資料庫連線。
        #async with ... as conn：是一個非同步上下文管理器，它做了兩件最重要的事：
        #進入時：成功從池子裡取得一個連線，並把它命名為 conn。
        #離開時：不管你的 API 程式碼是成功還是出錯，async with 都會確保這個 conn 連線被自動歸還 (release) 給 _pool 連線池，而不是被關閉。
        
        #使用 yield generator 傳回連線物件
        #getDB 函式會執行到 yield conn，把 conn 這個可用的連線交給 (注入) 你的 API 函式
        #API 函式執行完畢後（無論成功或失敗），getDB 會從 yield 的地方繼續，也就是 async with 區塊的結尾，這時連線就會自動被歸還。
        yield conn

# 關閉 Pool（優雅關機），當伺服器關閉時，自動釋放連線資源，避免資料庫殘留 session。
async def close_pool():
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
#if _pool is not None:：檢查連線池是否被建立過。
#await _pool.close()：如果建立過，就呼叫 close()。這個指令會關閉池中所有的資料庫連線，並釋放資源。
