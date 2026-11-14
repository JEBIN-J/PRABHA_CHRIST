import os
import re
import secrets
import sqlite3
import sys
import time
from functools import wraps
from getpass import getpass

from flask import Flask, render_template, request, redirect, url_for, flash, abort, session, g
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
# Set a long random SECRET_KEY in the environment in production.
app.secret_key = os.environ.get('SECRET_KEY', 'supersecretkeyforprabhachris')
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
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

    conn.execute('''
        CREATE TABLE IF NOT EXISTS inquiries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            inquiry_type TEXT,
            subject TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            is_superuser INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP
        )
    ''')
    # inquiries.is_read was added later — add it to existing databases
    cols = [r['name'] for r in conn.execute('PRAGMA table_info(inquiries)')]
    if 'is_read' not in cols:
        conn.execute('ALTER TABLE inquiries ADD COLUMN is_read INTEGER NOT NULL DEFAULT 0')

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


# ---------------------------------------------------------------- auth
def current_user():
    if 'user' not in g:
        g.user = None
        uid = session.get('user_id')
        if uid:
            conn = get_db_connection()
            g.user = conn.execute('SELECT id, username, is_superuser FROM users WHERE id = ?', (uid,)).fetchone()
            conn.close()
    return g.user


def superuser_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if user is None:
            return redirect(url_for('login', next=request.path))
        if not user['is_superuser']:
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def csrf_token():
    if '_csrf' not in session:
        session['_csrf'] = secrets.token_urlsafe(32)
    return session['_csrf']


@app.before_request
def check_csrf():
    # Every POST except the public contact form must carry the session's CSRF token.
    if request.method == 'POST' and request.endpoint not in ('contact',):
        if not secrets.compare_digest(request.form.get('_csrf', ''), session.get('_csrf', '-')):
            abort(400, 'Your session expired — please reload the page and try again.')


def unread_messages():
    conn = get_db_connection()
    n = conn.execute('SELECT COUNT(*) FROM inquiries WHERE is_read = 0').fetchone()[0]
    conn.close()
    return n


@app.context_processor
def inject_auth():
    return {'current_user': current_user(), 'csrf_token': csrf_token, 'unread_messages': unread_messages}


def create_superuser(username, password):
    conn = get_db_connection()
    existing = conn.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
    pw_hash = generate_password_hash(password)
    if existing:
        conn.execute('UPDATE users SET password_hash = ?, is_superuser = 1 WHERE id = ?', (pw_hash, existing['id']))
    else:
        conn.execute('INSERT INTO users (username, password_hash, is_superuser) VALUES (?, ?, 1)', (username, pw_hash))
    conn.commit()
    conn.close()
    return bool(existing)


@app.cli.command('createsuperuser')
def createsuperuser_command():
    """Create (or reset) an admin account:  flask --app app createsuperuser"""
    _createsuperuser_prompt()


def _createsuperuser_prompt():
    username = input('Username: ').strip()
    while not re.fullmatch(r'[A-Za-z0-9_.@-]{3,40}', username or ''):
        username = input('Username (3-40 letters, digits or _ . @ -): ').strip()
    while True:
        pw = getpass('Password: ')
        if len(pw) < 8:
            print('Password must be at least 8 characters.')
            continue
        if getpass('Password (again): ') != pw:
            print('Passwords did not match.')
            continue
        break
    updated = create_superuser(username, pw)
    print('Superuser "%s" %s.' % (username, 'updated' if updated else 'created'))


def safe_next(target):
    # only allow redirects back into this site
    return target if target and target.startswith('/') and not target.startswith('//') else None


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user() and current_user()['is_superuser']:
        return redirect(url_for('dashboard'))
    error = None
    username = ''
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        if user and check_password_hash(user['password_hash'], password) and user['is_superuser']:
            conn.execute('UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?', (user['id'],))
            conn.commit()
            conn.close()
            session.clear()
            session['user_id'] = user['id']
            session.permanent = bool(request.form.get('remember'))
            flash('Welcome back, %s!' % user['username'])
            return redirect(safe_next(request.form.get('next')) or url_for('dashboard'))
        conn.close()
        time.sleep(0.6)  # slow down password guessing
        error = 'Invalid username or password.'
    return render_template('login.html', error=error, username=username, next=request.args.get('next', ''))


@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    flash('You have been logged out.')
    return redirect(url_for('index'))


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


INQUIRY_TYPES = ['Commission a Painting', 'Purchase an Artwork', 'Exhibition / Collaboration', 'General Question']


@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        form = {k: (request.form.get(k) or '').strip() for k in ('name', 'email', 'inquiry_type', 'subject', 'message')}
        if not all(form[k] for k in ('name', 'email', 'subject', 'message')) or '@' not in form['email']:
            flash('Please fill in your name, a valid email, a subject and your message.')
            return render_template('contact.html', form=form, inquiry_types=INQUIRY_TYPES)
        conn = get_db_connection()
        conn.execute('INSERT INTO inquiries (name, email, inquiry_type, subject, message) VALUES (?, ?, ?, ?, ?)',
                     (form['name'], form['email'], form['inquiry_type'] or None, form['subject'], form['message']))
        conn.commit()
        conn.close()
        flash('Thank you, %s — your message has been sent. I will get back to you soon.' % form['name'])
        return redirect(url_for('contact'))
    return render_template('contact.html', form={}, inquiry_types=INQUIRY_TYPES)


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


# ---------------------------------------------------------------- admin dashboard
def save_upload(file, prefix):
    ext = file.filename.rsplit('.', 1)[1].lower()
    base = secure_filename(file.filename.rsplit('.', 1)[0])[:40] or 'image'
    filename = '%s_%d_%s.%s' % (prefix, int(time.time()), base, ext)
    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
    return filename


@app.route('/dashboard')
@superuser_required
def dashboard():
    conn = get_db_connection()
    stats = {
        'artworks': conn.execute('SELECT COUNT(*) FROM artworks').fetchone()[0],
        'categories': conn.execute('SELECT COUNT(*) FROM categories').fetchone()[0],
        'inquiries': conn.execute('SELECT COUNT(*) FROM inquiries').fetchone()[0],
        'unread': conn.execute('SELECT COUNT(*) FROM inquiries WHERE is_read = 0').fetchone()[0],
    }
    by_cat = conn.execute('SELECT c.name, COUNT(a.id) AS n FROM categories c LEFT JOIN artworks a '
                          'ON a.category_id = c.id GROUP BY c.id ORDER BY c.id').fetchall()
    month = "strftime('%Y-%m', created_at) = strftime('%Y-%m', 'now')"
    stats['art_month'] = conn.execute('SELECT COUNT(*) FROM artworks WHERE ' + month).fetchone()[0]
    stats['inq_month'] = conn.execute('SELECT COUNT(*) FROM inquiries WHERE ' + month).fetchone()[0]
    recent_art = conn.execute(ARTWORK_SQL + ' ORDER BY a.created_at DESC, a.id DESC LIMIT 6').fetchall()
    recent_inq = conn.execute('SELECT * FROM inquiries ORDER BY created_at DESC, id DESC LIMIT 5').fetchall()
    conn.close()
    hour = time.localtime().tm_hour
    greeting = 'Good morning' if hour < 12 else 'Good afternoon' if hour < 17 else 'Good evening'
    return render_template('admin/dashboard.html', stats=stats, by_cat=by_cat, greeting=greeting,
                           today=time.strftime('%A, %d %B %Y'),
                           recent_art=recent_art, recent_inq=recent_inq, active='dashboard')


@app.route('/dashboard/artworks', methods=['GET', 'POST'])
@superuser_required
def dash_artworks():
    conn = get_db_connection()
    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        category_id = request.form.get('category_id')
        file = request.files.get('file')
        if not title or not file or file.filename == '':
            flash('Please give the artwork a title and choose an image.')
        elif not allowed_file(file.filename):
            flash('Images must be PNG, JPG or GIF.')
        else:
            filename = save_upload(file, 'art')
            conn.execute('INSERT INTO artworks (title, image_path, category_id) VALUES (?, ?, ?)',
                         (title, filename, category_id))
            conn.commit()
            flash('"%s" was added to the gallery.' % title)
        conn.close()
        return redirect(url_for('dash_artworks'))
    artworks = conn.execute(ARTWORK_SQL + ' ORDER BY a.created_at DESC, a.id DESC').fetchall()
    categories = conn.execute('SELECT * FROM categories').fetchall()
    conn.close()
    return render_template('admin/artworks.html', artworks=artworks, categories=categories, active='artworks')


@app.route('/dashboard/artworks/<int:art_id>/edit', methods=['POST'])
@superuser_required
def dash_artwork_edit(art_id):
    title = (request.form.get('title') or '').strip()
    if not title:
        flash('Title cannot be empty.')
        return redirect(url_for('dash_artworks'))
    conn = get_db_connection()
    conn.execute('UPDATE artworks SET title = ?, category_id = ? WHERE id = ?',
                 (title, request.form.get('category_id'), art_id))
    conn.commit()
    conn.close()
    flash('Artwork updated.')
    return redirect(url_for('dash_artworks'))


@app.route('/dashboard/artworks/<int:art_id>/delete', methods=['POST'])
@superuser_required
def dash_artwork_delete(art_id):
    conn = get_db_connection()
    art = conn.execute('SELECT * FROM artworks WHERE id = ?', (art_id,)).fetchone()
    if art:
        conn.execute('DELETE FROM artworks WHERE id = ?', (art_id,))
        conn.commit()
        # remove the image file only if it was uploaded from the dashboard and nothing else uses it
        still_used = conn.execute('SELECT 1 FROM artworks WHERE image_path = ?', (art['image_path'],)).fetchone()
        if art['image_path'].startswith('art_') and not still_used:
            try:
                os.remove(os.path.join(app.config['UPLOAD_FOLDER'], art['image_path']))
            except OSError:
                pass
        flash('"%s" was removed from the gallery.' % art['title'])
    conn.close()
    return redirect(url_for('dash_artworks'))


def time_ago(ts):
    """'2026-11-14 13:50:00' (UTC, from SQLite) -> 'just now' / '5 min ago' / '3 h ago' / '2 days ago' / '14 Nov'"""
    try:
        t = time.mktime(time.strptime(ts[:19], '%Y-%m-%d %H:%M:%S')) - time.timezone
    except (TypeError, ValueError):
        return ts or ''
    d = time.time() - t
    if d < 60:
        return 'just now'
    if d < 3600:
        return '%d min ago' % (d // 60)
    if d < 86400:
        return '%d h ago' % (d // 3600)
    if d < 7 * 86400:
        n = int(d // 86400)
        return '%d day%s ago' % (n, '' if n == 1 else 's')
    return time.strftime('%d %b %Y', time.localtime(t))


app.jinja_env.filters['ago'] = time_ago


@app.route('/dashboard/messages')
@superuser_required
def dash_messages():
    show = request.args.get('show', 'all')
    conn = get_db_connection()
    sql = 'SELECT * FROM inquiries' + (' WHERE is_read = 0' if show == 'unread' else '') + ' ORDER BY created_at DESC, id DESC'
    inquiries = conn.execute(sql).fetchall()
    selected = None
    sel_id = request.args.get('id', type=int)
    if sel_id:
        selected = conn.execute('SELECT * FROM inquiries WHERE id = ?', (sel_id,)).fetchone()
    elif inquiries:
        selected = inquiries[0]
    if selected and not selected['is_read'] and sel_id:
        # opening a message marks it as read
        conn.execute('UPDATE inquiries SET is_read = 1 WHERE id = ?', (selected['id'],))
        conn.commit()
        selected = conn.execute('SELECT * FROM inquiries WHERE id = ?', (selected['id'],)).fetchone()
        inquiries = conn.execute(sql).fetchall()
    counts = {
        'all': conn.execute('SELECT COUNT(*) FROM inquiries').fetchone()[0],
        'unread': conn.execute('SELECT COUNT(*) FROM inquiries WHERE is_read = 0').fetchone()[0],
    }
    types = [r[0] for r in conn.execute('SELECT DISTINCT inquiry_type FROM inquiries WHERE inquiry_type IS NOT NULL ORDER BY 1')]
    conn.close()
    return render_template('admin/messages.html', inquiries=inquiries, selected=selected, show=show,
                           counts=counts, types=types, active='messages')


@app.route('/dashboard/messages/<int:msg_id>/<action>', methods=['POST'])
@superuser_required
def dash_message_action(msg_id, action):
    conn = get_db_connection()
    if action == 'read':
        conn.execute('UPDATE inquiries SET is_read = 1 WHERE id = ?', (msg_id,))
    elif action == 'unread':
        conn.execute('UPDATE inquiries SET is_read = 0 WHERE id = ?', (msg_id,))
    elif action == 'delete':
        conn.execute('DELETE FROM inquiries WHERE id = ?', (msg_id,))
        flash('Message deleted.')
    else:
        conn.close()
        abort(404)
    conn.commit()
    conn.close()
    show = request.form.get('show') if request.form.get('show') in ('all', 'unread') else 'all'
    if action == 'delete':
        return redirect(url_for('dash_messages', show=show))
    return redirect(url_for('dash_messages', show=show, **({'id': msg_id} if action == 'read' else {})))


@app.route('/dashboard/settings', methods=['GET', 'POST'])
@superuser_required
def dash_settings():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'hero':
            file = request.files.get('file')
            if not file or file.filename == '' or not allowed_file(file.filename):
                flash('Please choose a PNG, JPG or GIF image for the hero portrait.')
            else:
                set_setting('hero_image', 'uploads/' + save_upload(file, 'hero'))
                flash('Home page portrait updated.')
        elif action == 'hero_reset':
            set_setting('hero_image', DEFAULT_HERO_IMAGE)
            flash('Home page portrait reset to the default.')
        elif action == 'password':
            user = current_user()
            conn = get_db_connection()
            row = conn.execute('SELECT password_hash FROM users WHERE id = ?', (user['id'],)).fetchone()
            new = request.form.get('new_password') or ''
            if not check_password_hash(row['password_hash'], request.form.get('current_password') or ''):
                flash('Your current password is not correct.')
            elif len(new) < 8 or new != request.form.get('confirm_password'):
                flash('New password must be at least 8 characters and match the confirmation.')
            else:
                conn.execute('UPDATE users SET password_hash = ? WHERE id = ?', (generate_password_hash(new), user['id']))
                conn.commit()
                flash('Password changed.')
            conn.close()
        return redirect(url_for('dash_settings'))
    return render_template('admin/settings.html', active='settings')


# Old hidden admin address — now behind login
@app.route('/secret-art-add-prabha')
def secret_add():
    return redirect(url_for('dashboard'))


init_db()

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'createsuperuser':
        _createsuperuser_prompt()      # python app.py createsuperuser
    else:
        app.run(debug=True, port=5001)
