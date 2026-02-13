from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import mysql.connector
from mysql.connector import Error
import datetime

app = Flask(__name__)
CORS(app)

# --- КОНФИГУРАЦИЯ БД ---
DB_CONFIG = {
    'host': 'localhost',
    'database': 'restaurant_db',
    'user': 'root',
    'password': '1234'  # <--- ТВОЙ ПАРОЛЬ ОТ MYSQL
}

# --- МЕНЮ ---
MENU_ITEMS = [
    {"id": 1, "name": "Борщ", "price": 350, "category": "Супы"},
    {"id": 2, "name": "Паста Карбонара", "price": 550, "category": "Горячее"},
    {"id": 3, "name": "Стейк Рибай", "price": 1200, "category": "Горячее"},
    {"id": 4, "name": "Цезарь с курицей", "price": 450, "category": "Салаты"},
    {"id": 5, "name": "Кола", "price": 150, "category": "Напитки"},
    {"id": 6, "name": "Чизкейк", "price": 300, "category": "Десерты"},
]


def get_db_connection():
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        return conn
    except Error as e:
        print(f"Error: {e}")
        return None


# --- ГЛАВНАЯ СТРАНИЦА ---
@app.route('/')
def index():
    return render_template('index.html')


# --- API: АВТОРИЗАЦИЯ ---
@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')

    if username == 'guest':
        return jsonify({"message": "Вход выполнен", "user": {"id": 0, "username": "Гость", "role": "гость"}}), 200

    conn = get_db_connection()
    if not conn: return jsonify({"message": "Ошибка БД"}), 500
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, username, role FROM users WHERE username = %s AND password = %s", (username, password))
    user = cursor.fetchone()
    conn.close()

    if user:
        return jsonify({"message": "Вход выполнен", "user": user}), 200
    return jsonify({"message": "Неверные данные"}), 401


# --- API: СТАТИСТИКА ---
@app.route('/api/stats', methods=['GET'])
def get_stats():
    conn = get_db_connection()
    if not conn: return jsonify({}), 500
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM tables WHERE status='свободен'")
    free = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM tables WHERE status='занят'")
    busy = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM reservations WHERE DATE(reservation_datetime) = CURDATE()")
    today_res = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM orders WHERE status='открыт'")
    active_orders = cursor.fetchone()[0]
    conn.close()
    return jsonify({
        "free_tables": free,
        "busy_tables": busy,
        "today_reservations": today_res,
        "active_orders": active_orders
    })


# --- API: СТОЛИКИ ---
@app.route('/api/tables', methods=['GET'])
def get_tables():
    conn = get_db_connection()
    if not conn: return jsonify([]), 500
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM tables")
    tables = cursor.fetchall()
    conn.close()
    return jsonify(tables)


@app.route('/api/tables/<int:table_id>', methods=['PUT'])
def update_table(table_id):
    data = request.json
    status = data.get('status')
    conn = get_db_connection()
    if not conn: return jsonify({"message": "Ошибка БД"}), 500
    cursor = conn.cursor()
    cursor.execute("UPDATE tables SET status = %s WHERE id = %s", (status, table_id))
    conn.commit()
    conn.close()
    return jsonify({"message": "Updated"}), 200


# --- API: БРОНИРОВАНИЕ ---
@app.route('/api/reservations', methods=['GET'])
def get_reservations():
    conn = get_db_connection()
    if not conn: return jsonify([]), 500
    cursor = conn.cursor(dictionary=True)
    query = """
            SELECT r.id, r.client_name, r.reservation_datetime, t.table_number
            FROM reservations r
                     JOIN tables t ON r.table_id = t.id
            ORDER BY r.reservation_datetime \
            """
    cursor.execute(query)
    data = cursor.fetchall()
    conn.close()
    for row in data:
        row['reservation_datetime'] = row['reservation_datetime'].strftime('%Y-%m-%d %H:%M')
    return jsonify(data)


@app.route('/api/reservations', methods=['POST'])
def add_reservation():
    data = request.json
    conn = get_db_connection()
    if not conn: return jsonify({"message": "Ошибка БД"}), 500
    cursor = conn.cursor()
    user_id = data.get('user_id')
    if user_id == 0: user_id = None

    try:
        cursor.execute(
            "INSERT INTO reservations (client_name, reservation_datetime, table_id, created_by) VALUES (%s, %s, %s, %s)",
            (data['client_name'], data['datetime'], data['table_id'], user_id)
        )
        cursor.execute("UPDATE tables SET status = 'занят' WHERE id = %s", (data['table_id'],))
        conn.commit()
        return jsonify({"message": "Created"}), 201
    except Error as e:
        conn.rollback()
        print("SQL Error:", e)
        return jsonify({"message": str(e)}), 500
    finally:
        conn.close()


@app.route('/api/reservations/<int:id>', methods=['DELETE'])
def delete_reservation(id):
    conn = get_db_connection()
    if not conn: return jsonify({"message": "Ошибка БД"}), 500
    cursor = conn.cursor()
    cursor.execute("DELETE FROM reservations WHERE id = %s", (id,))
    conn.commit()
    conn.close()
    return jsonify({"message": "Deleted"}), 200


# --- API: МЕНЮ И ЗАКАЗЫ ---
@app.route('/api/menu', methods=['GET'])
def get_menu():
    return jsonify(MENU_ITEMS)


@app.route('/api/orders', methods=['GET'])
def get_orders():
    conn = get_db_connection()
    if not conn: return jsonify([]), 500
    cursor = conn.cursor(dictionary=True)
    # Загружаем ВСЕ заказы (и открытые, и закрытые), сортируем по новизне
    query = """
            SELECT o.id, \
                   t.table_number, \
                   o.status, \
                   o.order_datetime,
                   GROUP_CONCAT(CONCAT(oi.dish_name, ' x', oi.quantity) SEPARATOR ', ') as dishes
            FROM orders o
                     JOIN tables t ON o.table_id = t.id
                     JOIN order_items oi ON o.id = oi.order_id
            GROUP BY o.id
            ORDER BY o.order_datetime DESC \
            """
    cursor.execute(query)
    orders = cursor.fetchall()
    conn.close()

    for o in orders:
        if o['order_datetime']:
            o['order_datetime'] = o['order_datetime'].strftime('%H:%M')
    return jsonify(orders)


@app.route('/api/orders', methods=['POST'])
def create_order():
    data = request.json
    table_id = data.get('table_id')
    cart = data.get('cart')
    user_id = data.get('user_id')
    if user_id == 0: user_id = None

    if not cart: return jsonify({"message": "Empty"}), 400

    conn = get_db_connection()
    if not conn: return jsonify({"message": "Error"}), 500
    cursor = conn.cursor()

    try:
        cursor.execute("INSERT INTO orders (table_id, created_by, status) VALUES (%s, %s, 'открыт')",
                       (table_id, user_id))
        order_id = cursor.lastrowid
        for item in cart:
            cursor.execute("INSERT INTO order_items (order_id, dish_name, quantity) VALUES (%s, %s, %s)",
                           (order_id, item['name'], item['quantity']))
        cursor.execute("UPDATE tables SET status = 'занят' WHERE id = %s", (table_id,))
        conn.commit()
        return jsonify({"message": "OK"}), 201
    except Error as e:
        conn.rollback()
        print("Order Error:", e)
        return jsonify({"message": str(e)}), 500
    finally:
        conn.close()


@app.route('/api/orders/<int:id>/close', methods=['PUT'])
def close_order(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE orders SET status = 'закрыт' WHERE id = %s", (id,))
    conn.commit()
    conn.close()
    return jsonify({"message": "Closed"}), 200


if __name__ == '__main__':
    app.run(debug=True, port=5000)