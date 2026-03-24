import psycopg
from langgraph.checkpoint.postgres import PostgresSaver

def setup():
    DB_URI = "host=localhost user=postgres password=password dbname=memomed port=5432"
    # 不使用with语句，避免自动创建事务块
    conn = psycopg.connect(DB_URI)
    try:
        # 设置为自动提交模式
        conn.autocommit = True
        checkpointer = PostgresSaver(conn)
        # 这一行会创建所有必要的表
        checkpointer.setup()
        print("✅ LangGraph 存档表已就绪！")
    finally:
        conn.close()

if __name__ == "__main__":
    setup()