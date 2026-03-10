from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import mysql.connector
from mysql.connector import Error

app = Flask(__name__)
CORS(app)

# --- КОНФИГУРАЦИЯ БД ---
DB_CONFIG = {
    'host': 'localhost',
    'database': 'restaurant_db',
    'user': 'root',
    'password': '1234'  # <--- ВАШ ПАРОЛЬ ОТ MYSQL
}


def get_db_connection():
    try:
        return mysql.connector.connect(**DB_CONFIG)
    except Error as e:
        print(f"Ошибка БД: {e}")
        return None


@app.route('/')
def index():
    return render_template('index.html')


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

    if user: return jsonify({"message": "Вход выполнен", "user": user}), 200
    return jsonify({"message": "Неверные данные"}), 401


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
    return jsonify(
        {"free_tables": free, "busy_tables": busy, "today_reservations": today_res, "active_orders": active_orders})


@app.route('/api/tables', methods=['GET'])
def get_tables():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM tables")
    tables = cursor.fetchall()
    conn.close()
    return jsonify(tables)


@app.route('/api/tables/<int:table_id>', methods=['PUT'])
def update_table(table_id):
    status = request.json.get('status')
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE tables SET status = %s WHERE id = %s", (status, table_id))
    conn.commit()
    conn.close()
    return jsonify({"message": "Обновлено"}), 200


@app.route('/api/reservations', methods=['GET', 'POST'])
def handle_reservations():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'GET':
        cursor.execute("""
                       SELECT r.id, r.client_name, r.client_phone, r.reservation_datetime, t.table_number
                       FROM reservations r
                                JOIN tables t ON r.table_id = t.id
                       ORDER BY r.reservation_datetime
                       """)
        data = cursor.fetchall()
        for row in data:
            if row['reservation_datetime']:
                row['reservation_datetime'] = row['reservation_datetime'].strftime('%Y-%m-%d %H:%M')
        conn.close()
        return jsonify(data)

    elif request.method == 'POST':
        data = request.json
        user_id = data.get('user_id') if data.get('user_id') != 0 else None
        try:
            cursor.execute("""
                           INSERT INTO reservations (client_name, client_phone, reservation_datetime, table_id, created_by)
                           VALUES (%s, %s, %s, %s, %s)
                           """,
                           (data['client_name'], data['client_phone'], data['datetime'], data['table_id'], user_id))
            cursor.execute("UPDATE tables SET status = 'занят' WHERE id = %s", (data['table_id'],))
            conn.commit()
            return jsonify({"message": "Бронь создана"}), 201
        except Error as e:
            conn.rollback()
            return jsonify({"message": str(e)}), 500
        finally:
            conn.close()


@app.route('/api/reservations/<int:id>', methods=['DELETE'])
def delete_reservation(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM reservations WHERE id = %s", (id,))
    conn.commit()
    conn.close()
    return jsonify({"message": "Удалено"}), 200


@app.route('/api/menu', methods=['GET', 'POST'])
def handle_menu():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    if request.method == 'GET':
        cursor.execute("SELECT * FROM menu ORDER BY category, name")
        menu = cursor.fetchall()
        conn.close()
        return jsonify(menu)
    elif request.method == 'POST':
        data = request.json
        try:
            cursor.execute("INSERT INTO menu (name, price, category) VALUES (%s, %s, %s)",
                           (data['name'], data['price'], data['category']))
            conn.commit()
            return jsonify({"message": "Блюдо добавлено"}), 201
        except Error:
            conn.rollback()
            return jsonify({"message": "Ошибка или блюдо уже существует"}), 400
        finally:
            conn.close()


@app.route('/api/menu/<int:id>', methods=['DELETE'])
def delete_menu_item(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM menu WHERE id = %s", (id,))
    conn.commit()
    conn.close()
    return jsonify({"message": "Блюдо удалено"}), 200


@app.route('/api/orders', methods=['GET', 'POST'])
def handle_orders():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'GET':
        cursor.execute("""
                       SELECT o.id,
                              t.table_number,
                              o.status,
                              o.order_datetime,
                              GROUP_CONCAT(CONCAT(oi.dish_name, ' x', oi.quantity) SEPARATOR ', ') as dishes
                       FROM orders o
                                JOIN tables t ON o.table_id = t.id
                                JOIN order_items oi ON o.id = oi.order_id
                       GROUP BY o.id
                       ORDER BY o.order_datetime DESC
                       """)
        orders = cursor.fetchall()
        for o in orders:
            if o['order_datetime']:
                o['order_datetime'] = o['order_datetime'].strftime('%H:%M')
        conn.close()
        return jsonify(orders)

    elif request.method == 'POST':
        data = request.json
        cart = data.get('cart', [])
        user_id = data.get('user_id') if data.get('user_id') != 0 else None

        if not cart: return jsonify({"message": "Корзина пуста"}), 400

        try:
            cursor.execute("INSERT INTO orders (table_id, created_by, status) VALUES (%s, %s, 'открыт')",
                           (data['table_id'], user_id))
            order_id = cursor.lastrowid
            for item in cart:
                cursor.execute("INSERT INTO order_items (order_id, dish_name, quantity) VALUES (%s, %s, %s)",
                               (order_id, item['name'], item['quantity']))
            cursor.execute("UPDATE tables SET status = 'занят' WHERE id = %s", (data['table_id'],))
            conn.commit()
            return jsonify({"message": "Заказ оформлен"}), 201
        except Error as e:
            conn.rollback()
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
    return jsonify({"message": "Заказ закрыт"}), 200


if __name__ == '__main__':
    app.run(debug=True, port=5000)