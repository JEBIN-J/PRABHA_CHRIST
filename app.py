import os
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, flash
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
    
    # Add default categories if empty
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM categories')
    if cursor.fetchone()[0] == 0:
        categories = ['Paintings', 'Sketches', 'Digital Art', 'Abstract']
        for cat in categories:
            conn.execute('INSERT INTO categories (name) VALUES (?)', (cat,))
    
    conn.commit()
    conn.close()

@app.route('/')
def index():
    conn = get_db_connection()
    artworks = conn.execute('SELECT a.*, c.name as category_name FROM artworks a LEFT JOIN categories c ON a.category_id = c.id ORDER BY created_at DESC').fetchall()
    categories = conn.execute('SELECT * FROM categories').fetchall()
    conn.close()
    return render_template('index.html', artworks=artworks, categories=categories)

@app.route('/profile')
def profile():
    return render_template('profile.html')

@app.route('/category/<int:category_id>')
def category_view(category_id):
    conn = get_db_connection()
    category = conn.execute('SELECT * FROM categories WHERE id = ?', (category_id,)).fetchone()
    artworks = conn.execute('SELECT * FROM artworks WHERE category_id = ? ORDER BY created_at DESC', (category_id,)).fetchall()
    categories = conn.execute('SELECT * FROM categories').fetchall()
    conn.close()
    return render_template('category.html', artworks=artworks, category=category, categories=categories)

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

if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5001)
