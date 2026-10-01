"""
Victim API Service — Flask app that connects to PostgreSQL.
Serves as the middle tier of the target workload.
"""
import os
import sys
import time
import logging
from flask import Flask, jsonify, request
import psycopg2
from psycopg2 import pool
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger('api-service')

app = Flask(__name__)

DB_HOST = os.getenv('DB_HOST', 'postgres.workload.svc.cluster.local')
DB_PORT = int(os.getenv('DB_PORT', '5432'))
DB_NAME = os.getenv('DB_NAME', 'appdb')
DB_USER = os.getenv('DB_USER', 'appuser')
DB_PASSWORD = os.getenv('DB_PASSWORD', 'apppassword')

# Connection pool
db_pool = None


def get_db_pool():
    """Initialize the connection pool with retries."""
    global db_pool
    if db_pool is None:
        for attempt in range(5):
            try:
                db_pool = psycopg2.pool.SimpleConnectionPool(
                    minconn=1,
                    maxconn=10,
                    host=DB_HOST,
                    port=DB_PORT,
                    dbname=DB_NAME,
                    user=DB_USER,
                    password=DB_PASSWORD,
                    connect_timeout=5
                )
                logger.info("Database connection pool established")
                return db_pool
            except psycopg2.OperationalError as e:
                logger.warning(f"DB connection attempt {attempt + 1}/5 failed: {e}")
                time.sleep(2)
        logger.error("Failed to establish database connection pool after 5 attempts")
        raise RuntimeError("Database connection failed")
    return db_pool


@app.route('/health')
def health():
    """Health check endpoint."""
    return jsonify({"status": "healthy", "service": "api"})


@app.route('/ready')
def ready():
    """Readiness check — verifies DB connectivity."""
    try:
        pool_inst = get_db_pool()
        conn = pool_inst.getconn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.close()
        finally:
            pool_inst.putconn(conn)
        return jsonify({"status": "ready"})
    except Exception as e:
        logger.error(f"Readiness check failed: {e}")
        return jsonify({"status": "not_ready", "error": str(e)}), 503


@app.route('/api/items', methods=['GET'])
def list_items():
    """List all items from the database."""
    try:
        pool_inst = get_db_pool()
        conn = pool_inst.getconn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT id, name, description, created_at FROM items ORDER BY id")
            rows = cur.fetchall()
            cur.close()
            items = [
                {
                    "id": r[0],
                    "name": r[1],
                    "description": r[2],
                    "created_at": r[3].isoformat() if r[3] else None
                }
                for r in rows
            ]
            logger.info(f"Listed {len(items)} items")
            return jsonify({"items": items})
        finally:
            pool_inst.putconn(conn)
    except Exception as e:
        logger.error(f"Error listing items: {e}")
        return jsonify({"error": "Internal server error", "detail": str(e)}), 500


@app.route('/api/items', methods=['POST'])
def create_item():
    """Create a new item."""
    data = request.get_json()
    if not data or 'name' not in data:
        return jsonify({"error": "Missing required field: name"}), 400

    try:
        pool_inst = get_db_pool()
        conn = pool_inst.getconn()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO items (name, description) VALUES (%s, %s) RETURNING id, created_at",
                (data['name'], data.get('description', ''))
            )
            row = cur.fetchone()
            conn.commit()
            cur.close()
            logger.info(f"Created item: {data['name']} (id={row[0]})")
            return jsonify({
                "id": row[0],
                "name": data['name'],
                "description": data.get('description', ''),
                "created_at": row[1].isoformat() if row[1] else None
            }), 201
        finally:
            pool_inst.putconn(conn)
    except Exception as e:
        logger.error(f"Error creating item: {e}")
        return jsonify({"error": "Internal server error", "detail": str(e)}), 500


@app.route('/api/stress', methods=['POST'])
def stress():
    """Endpoint to simulate memory pressure for OOM testing."""
    size_mb = int(request.args.get('size_mb', 50))
    logger.warning(f"Stress test: allocating {size_mb}MB")
    # Allocate memory
    data = bytearray(size_mb * 1024 * 1024)
    # Hold it briefly
    time.sleep(2)
    return jsonify({"allocated_mb": size_mb, "bytes": len(data)})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=False)
