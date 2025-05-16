import os
from flask import Flask, render_template, request, redirect, url_for, flash
from pymongo import MongoClient, errors as pymongo_errors # імпортуємо помилки pymongo
from bson.objectid import ObjectId
from datetime import datetime, timezone

app = Flask(__name__)
app.secret_key = os.urandom(24) # Для flash-повідомлень

# --- Налаштування MongoDB ---
MONGO_URI = os.environ.get("MONGO_URI")

if not MONGO_URI:
    app.logger.error("----------------------------------------------------------------")
    app.logger.error("КРИТИЧНА ПОМИЛКА: Змінна середовища MONGO_URI не встановлена!")
    app.logger.error("Будь ласка, встановіть MONGO_URI з вашим рядком підключення до MongoDB Atlas.")
    app.logger.error("Наприклад, в налаштуваннях середовища на Render.com.")
    app.logger.error("Додаток не може працювати без підключення до бази даних.")
    app.logger.error("----------------------------------------------------------------")
    # Можна зупинити додаток або повернути помилку на всіх маршрутах
    # Для простоти, ми дозволимо йому запуститися, але він не зможе підключитися до БД.
    # Краще було б викликати raise SystemExit(...) або подібне.

# Назви бази даних та колекції можна залишити тут або теж винести в змінні середовища
DB_NAME = os.environ.get("MONGO_DB_NAME", "my_crud_app_db")
COLLECTION_NAME = os.environ.get("MONGO_COLLECTION_NAME", "items")

client = None
db = None
items_collection = None

# Ініціалізація з'єднання з базою даних
# Це краще робити так, щоб додаток не падав повністю при запуску,
# а помилки оброблялися при спробі доступу до БД.
def get_db_connection():
    global client, db, items_collection
    if not MONGO_URI:
        app.logger.error("MONGO_URI не встановлено. Неможливо підключитися до БД.")
        return None

    if client is None: # Ініціалізуємо клієнт тільки один раз
        try:
            app.logger.info(f"Attempting to connect to MongoDB with URI: {MONGO_URI[:20]}... (URI приховано)")
            client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000) # Додаємо таймаут
            client.admin.command('ping') # Перевірка з'єднання
            db = client[DB_NAME]
            items_collection = db[COLLECTION_NAME]
            app.logger.info(f"Successfully connected to MongoDB! DB: {DB_NAME}, Collection: {COLLECTION_NAME}")
        except pymongo_errors.ConnectionFailure as e:
            app.logger.error(f"MongoDB ConnectionFailure: {e}")
            client = db = items_collection = None # Скидаємо, щоб спробувати знову при наступному запиті
        except pymongo_errors.ConfigurationError as e:
            app.logger.error(f"MongoDB ConfigurationError (перевірте MONGO_URI): {e}")
            client = db = items_collection = None
        except Exception as e:
            app.logger.error(f"An unexpected error occurred while connecting to MongoDB: {e}")
            client = db = items_collection = None
    return items_collection


# --- CRUD операції для MongoDB ---
# Ці функції тепер будуть викликати get_db_connection()

def add_item_db(name, description):
    collection = get_db_connection()
    if not collection:
        return False
    try:
        item_doc = {
            "name": name,
            "description": description,
            "created_at": datetime.now(timezone.utc)
        }
        result = collection.insert_one(item_doc)
        return result.inserted_id is not None
    except Exception as e:
        app.logger.error(f"Error adding item to MongoDB: {e}")
        return False

def get_last_items_db(limit=10):
    collection = get_db_connection()
    if not collection:
        return []
    try:
        items_cursor = collection.find().sort("created_at", -1).limit(limit)
        items_list = []
        for item in items_cursor:
            item['created_at_formatted'] = item['created_at'].strftime('%d.%m.%Y %H:%M')
            items_list.append(item)
        return items_list
    except Exception as e:
        app.logger.error(f"Error fetching items from MongoDB: {e}")
        return []

def get_item_by_id_db(item_id_str):
    collection = get_db_connection()
    if not collection:
        return None
    try:
        return collection.find_one({"_id": ObjectId(item_id_str)})
    except Exception as e:
        app.logger.error(f"Error fetching item by ID {item_id_str} from MongoDB: {e}")
        return None

def update_item_db(item_id_str, name, description):
    collection = get_db_connection()
    if not collection:
        return False
    try:
        result = collection.update_one(
            {"_id": ObjectId(item_id_str)},
            {"$set": {"name": name, "description": description, "updated_at": datetime.now(timezone.utc)}} # Додамо час оновлення
        )
        return result.modified_count > 0
    except Exception as e:
        app.logger.error(f"Error updating item ID {item_id_str} in MongoDB: {e}")
        return False

def delete_item_db(item_id_str):
    collection = get_db_connection()
    if not collection:
        return False
    try:
        result = collection.delete_one({"_id": ObjectId(item_id_str)})
        return result.deleted_count > 0
    except Exception as e:
        app.logger.error(f"Error deleting item ID {item_id_str} in MongoDB: {e}")
        return False

# --- Маршрути Flask ---
@app.route('/', methods=['GET'])
@app.route('/edit/<item_id_str>', methods=['GET'])
def index(item_id_str=None):
    if not get_db_connection(): # Перевіряємо з'єднання перед тим як щось робити
        flash("Помилка підключення до бази даних. Будь ласка, перевірте налаштування або спробуйте пізніше.", "danger")
        # Відображаємо сторінку, але вона буде пустою або з повідомленням про помилку
        return render_template('index.html', items=[], item_to_edit=None, db_error=True)


    items = get_last_items_db()
    item_to_edit = None
    if item_id_str:
        item_to_edit = get_item_by_id_db(item_id_str)
        if not item_to_edit:
            flash(f"Запис з ID {item_id_str} не знайдено.", "danger")
            return redirect(url_for('index')) # Редирект якщо не знайдено
    return render_template('index.html', items=items, item_to_edit=item_to_edit)

@app.route('/add', methods=['POST'])
def add_item_route():
    if not get_db_connection():
        flash("Помилка підключення до бази даних. Неможливо додати запис.", "danger")
        return redirect(url_for('index'))

    name = request.form.get('name')
    description = request.form.get('description')

    if not name:
        flash("Поле 'Назва' не може бути порожнім.", "warning")
    elif add_item_db(name, description):
        flash("Запис успішно додано!", "success")
    else:
        flash("Помилка при додаванні запису.", "danger")
    return redirect(url_for('index'))

@app.route('/update/<item_id_str>', methods=['POST'])
def update_item_route(item_id_str):
    if not get_db_connection():
        flash("Помилка підключення до бази даних. Неможливо оновити запис.", "danger")
        return redirect(url_for('index'))

    name = request.form.get('name')
    description = request.form.get('description')

    if not name:
        flash("Поле 'Назва' не може бути порожнім.", "warning")
        # Якщо валідація не пройшла, потрібно повернути дані для редагування
        item_to_edit = get_item_by_id_db(item_id_str)
        items = get_last_items_db()
        return render_template('index.html', items=items, item_to_edit=item_to_edit, current_name=name, current_description=description)

    if update_item_db(item_id_str, name, description):
        flash("Запис успішно оновлено!", "success")
    else:
        if not get_item_by_id_db(item_id_str): # Перевірка, чи існує запис
             flash(f"Запис з ID {item_id_str} не знайдено для оновлення.", "danger")
        else:
             flash("Дані не були змінені або сталася помилка оновлення.", "info")
    return redirect(url_for('index'))

@app.route('/delete/<item_id_str>', methods=['POST'])
def delete_item_route(item_id_str):
    if not get_db_connection():
        flash("Помилка підключення до бази даних. Неможливо видалити запис.", "danger")
        return redirect(url_for('index'))

    if delete_item_db(item_id_str):
        flash("Запис успішно видалено!", "success")
    else:
        flash("Помилка при видаленні запису (можливо, його вже видалено).", "warning")
    return redirect(url_for('index'))

if __name__ == "__main__":
    # Логіка перевірки MONGO_URI вже є на початку файлу
    port = int(os.environ.get("PORT", 5001))
    app.run(host='0.0.0.0', port=port, debug=os.environ.get("FLASK_DEBUG", "False").lower() == "true")