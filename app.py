import os
import sqlite3
import time
from flask import Flask, render_template, request, redirect, url_for, flash, abort
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'supersecretkeyforprabhachris'
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB upload limit

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_db_connection():
    conn = sqlite3.connect('gallery.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS artworks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            image_path TEXT NOT NULL,
            category_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (category_id) REFERENCES categories (id)
        )
    ''')
    
    conn.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')

    # Add default categories if empty
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM categories')
    if cursor.fetchone()[0] == 0:
        categories = ['Paintings', 'Sketches', 'Digital Art', 'Abstract']
        for cat in categories:
            conn.execute('INSERT INTO categories (name) VALUES (?)', (cat,))
    
    conn.commit()
    conn.close()

DEFAULT_HERO_IMAGE = 'img/hero-portrait.jpg'  # path relative to /static


def get_setting(key, default=None):
    conn = get_db_connection()
    row = conn.execute('SELECT value FROM settings WHERE key = ?', (key,)).fetchone()
    conn.close()
    return row['value'] if row else default


def set_setting(key, value):
    conn = get_db_connection()
    conn.execute('INSERT INTO settings (key, value) VALUES (?, ?) '
                 'ON CONFLICT(key) DO UPDATE SET value = excluded.value', (key, value))
    conn.commit()
    conn.close()


@app.context_processor
def inject_hero_image():
    # Path (relative to /static) of the portrait shown in the home page hero.
    return {'hero_image': get_setting('hero_image', DEFAULT_HERO_IMAGE)}


ARTWORK_SQL = ('SELECT a.*, c.name AS category_name FROM artworks a '
               'LEFT JOIN categories c ON a.category_id = c.id')


@app.route('/')
def index():
    conn = get_db_connection()
    featured = conn.execute(ARTWORK_SQL + ' ORDER BY a.created_at DESC, a.id DESC LIMIT 6').fetchall()
    conn.close()
    return render_template('index.html', featured=featured)


@app.route('/about')
def about():
    return render_template('about.html')


@app.route('/gallery')
def gallery():
    conn = get_db_connection()
    artworks = conn.execute(ARTWORK_SQL + ' ORDER BY a.created_at DESC').fetchall()
    categories = conn.execute('SELECT * FROM categories').fetchall()
    conn.close()
    return render_template('gallery.html', artworks=artworks, categories=categories)


@app.route('/journey')
def journey():
    return render_template('journey.html')


@app.route('/exhibitions')
def exhibitions():
    return render_template('exhibitions.html')


@app.route('/contact')
def contact():
    return render_template('contact.html')


@app.route('/profile')
def profile():
    # The old "The Artist" page now lives at /about
    return redirect(url_for('about'))


@app.route('/category/<int:category_id>')
def category_view(category_id):
    conn = get_db_connection()
    category = conn.execute('SELECT * FROM categories WHERE id = ?', (category_id,)).fetchone()
    if category is None:
        conn.close()
        abort(404)
    artworks = conn.execute(ARTWORK_SQL + ' WHERE a.category_id = ? ORDER BY a.created_at DESC',
                            (category_id,)).fetchall()
    categories = conn.execute('SELECT * FROM categories').fetchall()
    conn.close()
    return render_template('category.html', artworks=artworks, category=category, categories=categories)


# Hidden: change the hero portrait on the home page
@app.route('/secret-art-add-prabha/hero', methods=['POST'])
def secret_hero():
    file = request.files.get('file')
    if not file or file.filename == '' or not allowed_file(file.filename):
        flash('Please choose a PNG, JPG or GIF image for the hero portrait.')
        return redirect(url_for('secret_add'))

    ext = file.filename.rsplit('.', 1)[1].lower()
    filename = 'hero_portrait_%d.%s' % (int(time.time()), ext)  # new name busts browser cache
    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
    set_setting('hero_image', 'uploads/' + filename)
    flash('Hero portrait updated!')
    return redirect(url_for('index'))


@app.route('/secret-art-add-prabha/hero/reset', methods=['POST'])
def secret_hero_reset():
    set_setting('hero_image', DEFAULT_HERO_IMAGE)
    flash('Hero portrait reset to the default.')
    return redirect(url_for('index'))


# Hidden upload page
@app.route('/secret-art-add-prabha', methods=['GET', 'POST'])
def secret_add():
    conn = get_db_connection()
    if request.method == 'POST':
        title = request.form.get('title')
        category_id = request.form.get('category_id')
        file = request.files.get('file')
        
        if not title or not file or file.filename == '':
            flash('Title and Image are required!')
            return redirect(request.url)
        
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            
            conn.execute('INSERT INTO artworks (title, image_path, category_id) VALUES (?, ?, ?)',
                         (title, filename, category_id))
            conn.commit()
            conn.close()
            flash('Art added successfully!')
            return redirect(url_for('index'))
            
    categories = conn.execute('SELECT * FROM categories').fetchall()
    conn.close()
    return render_template('secret_add.html', categories=categories)

init_db()

if __name__ == '__main__':
    app.run(debug=True, port=5001)
