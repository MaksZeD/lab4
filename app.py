import os
from flask import Flask, render_template, request, redirect, url_for, flash
from pymongo import MongoClient, errors as pymongo_errors
from bson.objectid import ObjectId
from datetime import datetime, timezone

app = Flask(__name__)
app.secret_key = os.urandom(24)

MONGO_URI = os.environ.get("MONGO_URI")

if not MONGO_URI:
    app.logger.error("----------------------------------------------------------------")
    app.logger.error("КРИТИЧНА ПОМИЛКА: Змінна середовища MONGO_URI не встановлена!")
    # ... (решта логування помилки)
    app.logger.error("----------------------------------------------------------------")

DB_NAME = os.environ.get("MONGO_DB_NAME", "my_crud_app_db")
COLLECTION_NAME = os.environ.get("MONGO_COLLECTION_NAME", "items")

client = None
db = None
items_collection = None

def get_db_connection():
    global client, db, items_collection
    if not MONGO_URI:
        app.logger.error("MONGO_URI не встановлено. Неможливо підключитися до БД.")
        return None

    if client is None or items_collection is None: # Перевіряємо, чи потрібно ініціалізувати
        try:
            app.logger.info(f"Attempting to (re)connect to MongoDB...")
            client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
            client.admin.command('ping')
            db = client[DB_NAME]
            items_collection = db[COLLECTION_NAME]
            app.logger.info(f"Successfully connected to MongoDB! DB: {DB_NAME}, Collection: {COLLECTION_NAME}")
        except pymongo_errors.ConnectionFailure as e:
            app.logger.error(f"MongoDB ConnectionFailure: {e}")
            client = db = items_collection = None
        except pymongo_errors.ConfigurationError as e:
            app.logger.error(f"MongoDB ConfigurationError (перевірте MONGO_URI): {e}")
            client = db = items_collection = None
        except Exception as e: # Включаючи помилки автентифікації, якщо вони тут виникнуть
            app.logger.error(f"An unexpected error occurred while connecting to MongoDB: {e}")
            client = db = items_collection = None
    return items_collection


def add_item_db(name, description):
    collection = get_db_connection()
    if collection is None:
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
    if collection is None:
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
    if collection is None:
        return None
    try:
        return collection.find_one({"_id": ObjectId(item_id_str)})
    except Exception as e:
        app.logger.error(f"Error fetching item by ID {item_id_str} from MongoDB: {e}")
        return None

def update_item_db(item_id_str, name, description):
    collection = get_db_connection()
    if collection is None:
        return False
    try:
        result = collection.update_one(
            {"_id": ObjectId(item_id_str)},
            {"$set": {"name": name, "description": description, "updated_at": datetime.now(timezone.utc)}}
        )
        return result.modified_count > 0
    except Exception as e:
        app.logger.error(f"Error updating item ID {item_id_str} in MongoDB: {e}")
        return False

def delete_item_db(item_id_str):
    collection = get_db_connection()
    if collection is None:
        return False
    try:
        result = collection.delete_one({"_id": ObjectId(item_id_str)})
        return result.deleted_count > 0
    except Exception as e:
        app.logger.error(f"Error deleting item ID {item_id_str} from MongoDB: {e}")
        return False

@app.route('/', methods=['GET'])
@app.route('/edit/<item_id_str>', methods=['GET'])
def index(item_id_str=None):
    # Отримуємо екземпляр колекції один раз на початку маршруту
    # get_db_connection() сама обробляє логіку перепідключення якщо client is None
    current_collection = get_db_connection()
    if current_collection is None:
        flash("Помилка підключення до бази даних. Будь ласка, перевірте налаштування або спробуйте пізніше.", "danger")
        return render_template('index.html', items=[], item_to_edit=None, db_error=True)

    items = get_last_items_db() # Ця функція викличе get_db_connection() всередині
    item_to_edit = None
    if item_id_str:
        item_to_edit = get_item_by_id_db(item_id_str) # І ця теж
        if not item_to_edit: # Тут item_to_edit буде None якщо запис не знайдено або помилка БД
            flash(f"Запис з ID {item_id_str} не знайдено.", "danger")
            return redirect(url_for('index'))
    return render_template('index.html', items=items, item_to_edit=item_to_edit)

@app.route('/add', methods=['POST'])
def add_item_route():
    if get_db_connection() is None:
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
    if get_db_connection() is None:
        flash("Помилка підключення до бази даних. Неможливо оновити запис.", "danger")
        return redirect(url_for('index'))

    name = request.form.get('name')
    description = request.form.get('description')

    if not name:
        flash("Поле 'Назва' не може бути порожнім.", "warning")
        item_to_edit = get_item_by_id_db(item_id_str)
        items = get_last_items_db()
        return render_template('index.html', items=items, item_to_edit=item_to_edit, current_name=name, current_description=description)

    if update_item_db(item_id_str, name, description):
        flash("Запис успішно оновлено!", "success")
    else:
        if get_item_by_id_db(item_id_str) is None:
             flash(f"Запис з ID {item_id_str} не знайдено для оновлення.", "danger")
        else:
             flash("Дані не були змінені або сталася помилка оновлення.", "info")
    return redirect(url_for('index'))

@app.route('/delete/<item_id_str>', methods=['POST'])
def delete_item_route(item_id_str):
    if get_db_connection() is None:
        flash("Помилка підключення до бази даних. Неможливо видалити запис.", "danger")
        return redirect(url_for('index'))

    if delete_item_db(item_id_str):
        flash("Запис успішно видалено!", "success")
    else:
        flash("Помилка при видаленні запису (можливо, його вже видалено).", "warning")
    return redirect(url_for('index'))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host='0.0.0.0', port=port, debug=os.environ.get("FLASK_DEBUG", "False").lower() == "true")