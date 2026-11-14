"""One-off helper: add the sample artworks that ship in static/uploads to the gallery.

Safe to re-run — images already in the database are skipped.
Run:  venv/bin/python seed_samples.py
"""
import sqlite3

SAMPLES = [
    # (file in static/uploads, title, category name)
    ('art_oil_1.png', 'Crimson Horizon', 'Paintings'),
    ('art_oil_2.png', 'The Velvet Scholar', 'Paintings'),
    ('art_water_1.png', 'Garden of Quiet Hours', 'Paintings'),
    ('art_sketch_1.png', 'Motion in Charcoal', 'Sketches'),
    ('art_digital_1.png', 'Golden Constellations', 'Digital Art'),
    ('art_abstract_1.png', 'Gilded Fragments', 'Abstract'),
    ('maroon_abstraction.png', 'Maroon Abstraction', 'Abstract'),
]

conn = sqlite3.connect('gallery.db')
cats = {name: cid for cid, name in conn.execute('SELECT id, name FROM categories')}
added = 0
for filename, title, cat in SAMPLES:
    if conn.execute('SELECT 1 FROM artworks WHERE image_path = ?', (filename,)).fetchone():
        continue
    conn.execute('INSERT INTO artworks (title, image_path, category_id) VALUES (?, ?, ?)',
                 (title, filename, cats[cat]))
    added += 1
conn.commit()
conn.close()
print('added %d artwork(s)' % added)
