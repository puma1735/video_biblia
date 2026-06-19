# app.py - VERSIÓN COMPLETA CON SISTEMA DE ETIQUETAS
from flask import Flask, render_template, request, jsonify, send_file
from flask_cors import CORS
import requests
import json
import os
import sqlite3
from datetime import datetime
import hashlib
import re
from urllib.parse import quote
from PIL import Image
from io import BytesIO
import time

app = Flask(__name__)
CORS(app)

# Configuración
DOWNLOAD_FOLDER = 'videos_database'
THUMBNAILS_FOLDER = 'thumbnails'
DB_FILE = 'tiktok_videos.db'

os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
os.makedirs(THUMBNAILS_FOLDER, exist_ok=True)

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # Tabla de videos
    c.execute('''CREATE TABLE IF NOT EXISTS videos
                 (id TEXT PRIMARY KEY,
                  titulo TEXT,
                  autor TEXT,
                  url_original TEXT,
                  url_descarga TEXT,
                  thumbnail TEXT,
                  thumbnail_local TEXT,
                  likes INTEGER,
                  vistas INTEGER,
                  duracion INTEGER,
                  fecha_descarga TEXT,
                  archivo_local TEXT,
                  hashtags TEXT,
                  tamanio_bytes INTEGER,
                  estado TEXT,
                  etiquetas TEXT)''')
    
    # Tabla de etiquetas disponibles
    c.execute('''CREATE TABLE IF NOT EXISTS etiquetas
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  nombre TEXT UNIQUE,
                  color TEXT,
                  fecha_creacion TEXT)''')
    
    # Insertar etiquetas por defecto si no existen
    etiquetas_default = [
        ('Virgen María', '#3b82f6'),
        ('Papa', '#f59e0b'),
        ('Oraciones', '#8b5cf6'),
        ('Versículos', '#10b981'),
        ('Dar Gracias', '#ec4899'),
        ('Hoy día', '#ef4444')
    ]
    
    for nombre, color in etiquetas_default:
        try:
            c.execute('INSERT INTO etiquetas (nombre, color, fecha_creacion) VALUES (?, ?, ?)',
                     (nombre, color, datetime.now().isoformat()))
        except sqlite3.IntegrityError:
            pass  # Ya existe
    
    # Verificar si existe la columna etiquetas en videos
    c.execute("PRAGMA table_info(videos)")
    columnas = [col[1] for col in c.fetchall()]
    
    if 'etiquetas' not in columnas:
        c.execute('ALTER TABLE videos ADD COLUMN etiquetas TEXT DEFAULT "[]"')
        print("✅ Columna 'etiquetas' agregada a la tabla videos")
    
    conn.commit()
    conn.close()

init_db()

class TikTokDownloader:
    """Downloader usando APIs que realmente funcionan"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def buscar_por_url_manual(self, urls_manuales):
        """Procesa URLs ingresadas manualmente"""
        videos = []
        
        for i, url in enumerate(urls_manuales, 1):
            try:
                print(f"\n📝 Procesando URL {i}/{len(urls_manuales)}")
                print(f"   {url}")
                
                info = self.obtener_info_video(url)
                
                if info:
                    videos.append(info)
                    print(f"   ✅ OK: {info.get('titulo', '')[:50]}...")
                else:
                    print(f"   ⚠️  No se pudo obtener info")
                    
            except Exception as e:
                print(f"   ❌ Error: {e}")
                continue
        
        return videos
    
    def obtener_info_video(self, url_tiktok):
        """Obtiene información de un video de TikTok"""
        
        video_id_match = re.search(r'/video/(\d+)', url_tiktok)
        if not video_id_match:
            return None
        
        video_id = video_id_match.group(1)
        
        try:
            print(f"   🔄 Intentando Tikwm...")
            info = self._info_con_tikwm(url_tiktok)
            if info:
                info['id'] = video_id
                info['url_video'] = url_tiktok
                return info
        except Exception as e:
            print(f"   ⚠️  Tikwm: {e}")
        
        try:
            print(f"   🔄 Intentando SnapTik...")
            info = self._info_con_snaptik(url_tiktok)
            if info:
                info['id'] = video_id
                info['url_video'] = url_tiktok
                return info
        except Exception as e:
            print(f"   ⚠️  SnapTik: {e}")
        
        print(f"   📌 Creando entrada básica...")
        return {
            'id': video_id,
            'titulo': f'Video TikTok {video_id}',
            'autor': 'unknown',
            'autor_nombre': 'Unknown',
            'thumbnail': '',
            'thumbnail_local': None,
            'url_video': url_tiktok,
            'duracion': 0,
            'likes': 0,
            'vistas': 0,
            'url_descarga': '',
            'url_descarga_hd': '',
        }
    
    def _info_con_tikwm(self, url):
        """Obtiene info usando Tikwm"""
        api_url = 'https://www.tikwm.com/api/'
        
        response = self.session.post(
            api_url,
            data={'url': url, 'hd': 1},
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            timeout=15
        )
        
        data = response.json()
        
        if data.get('code') != 0:
            return None
        
        video_data = data.get('data', {})
        author = video_data.get('author', {})
        
        def fix_url(u):
            if not u:
                return ''
            if u.startswith('//'):
                return f'https:{u}'
            if u.startswith('/'):
                return f'https://www.tikwm.com{u}'
            return u
        
        thumbnail_url = fix_url(video_data.get('cover', ''))
        play_url = fix_url(video_data.get('play', ''))
        hdplay_url = fix_url(video_data.get('hdplay', ''))
        
        thumb_local = None
        if thumbnail_url:
            thumb_local = self._descargar_thumbnail(
                thumbnail_url, 
                video_data.get('id', str(int(time.time())))
            )
        
        return {
            'titulo': video_data.get('title', 'Sin título')[:150],
            'autor': author.get('unique_id', 'unknown'),
            'autor_nombre': author.get('nickname', 'Unknown'),
            'thumbnail': thumbnail_url,
            'thumbnail_local': thumb_local,
            'duracion': video_data.get('duration', 0),
            'likes': video_data.get('digg_count', 0),
            'vistas': video_data.get('play_count', 0),
            'comentarios': video_data.get('comment_count', 0),
            'url_descarga': play_url,
            'url_descarga_hd': hdplay_url,
        }
    
    def _info_con_snaptik(self, url):
        """Obtiene info usando SnapTik"""
        from bs4 import BeautifulSoup
        
        response = self.session.get('https://snaptik.app/es')
        
        response = self.session.post(
            'https://snaptik.app/abc2.php',
            data={'url': url, 'lang': 'es'},
            headers={'Referer': 'https://snaptik.app/es'},
            timeout=15
        )
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        download_url = None
        
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            if 'download' in href.lower() or '.mp4' in href:
                download_url = href
                break
        
        if not download_url:
            video_urls = re.findall(r'(https://[^\s"\'<>]+\.mp4[^\s"\'<>]*)', response.text)
            if video_urls:
                download_url = video_urls[0]
        
        if not download_url:
            return None
        
        return {
            'titulo': 'Video TikTok',
            'autor': 'unknown',
            'autor_nombre': 'Unknown',
            'thumbnail': '',
            'thumbnail_local': None,
            'duracion': 0,
            'likes': 0,
            'vistas': 0,
            'url_descarga': download_url,
            'url_descarga_hd': download_url,
        }
    
    def _descargar_thumbnail(self, url, video_id):
        """Descarga thumbnail como JPG"""
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            
            img = Image.open(BytesIO(response.content))
            
            if img.mode in ('RGBA', 'LA', 'P'):
                bg = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                bg.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = bg
            elif img.mode != 'RGB':
                img = img.convert('RGB')
            
            img.thumbnail((800, 800), Image.Resampling.LANCZOS)
            
            filename = f"{video_id}_thumb.jpg"
            filepath = os.path.join(THUMBNAILS_FOLDER, filename)
            img.save(filepath, 'JPEG', quality=85)
            
            return filename
            
        except Exception as e:
            print(f"      ⚠️  Error thumbnail: {e}")
            return None
    
    def descargar_video(self, video_info):
        """Descarga el video"""
        video_id = video_info.get('id', '')
        
        try:
            url_descarga = video_info.get('url_descarga_hd') or video_info.get('url_descarga')
            
            if not url_descarga:
                print(f"   🔄 Obteniendo URL de descarga...")
                url_original = video_info.get('url_video', '')
                
                info = self._info_con_tikwm(url_original)
                if not info:
                    info = self._info_con_snaptik(url_original)
                
                if info:
                    url_descarga = info.get('url_descarga_hd') or info.get('url_descarga')
                    video_info.update(info)
            
            if not url_descarga:
                return {
                    'success': False,
                    'id': video_id,
                    'error': 'No se pudo obtener URL de descarga'
                }
            
            print(f"   ⬇️  Descargando desde: {url_descarga[:60]}...")
            
            response = self.session.get(
                url_descarga,
                stream=True,
                timeout=60,
                headers={
                    'Referer': 'https://www.tiktok.com/',
                    'Accept': 'video/mp4,video/*,*/*'
                }
            )
            response.raise_for_status()
            
            filename = f"{video_id}_{hashlib.md5(url_descarga.encode()).hexdigest()[:8]}.mp4"
            filepath = os.path.join(DOWNLOAD_FOLDER, filename)
            
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            file_size = os.path.getsize(filepath)
            
            if file_size < 50000:
                os.remove(filepath)
                return {
                    'success': False,
                    'id': video_id,
                    'error': f'Archivo muy pequeño ({file_size} bytes)'
                }
            
            print(f"   ✅ Descargado: {file_size/1024/1024:.2f}MB")
            
            self._guardar_en_bd(video_info, filepath, file_size)
            
            return {
                'success': True,
                'id': video_id,
                'filename': filename,
                'size': file_size
            }
            
        except Exception as e:
            print(f"   ❌ Error: {e}")
            return {
                'success': False,
                'id': video_id,
                'error': str(e)
            }
    
    def _guardar_en_bd(self, video_info, filepath, file_size):
        """Guarda en BD"""
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        
        c.execute('''INSERT OR REPLACE INTO videos 
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                  (
                      video_info.get('id'),
                      video_info.get('titulo', '')[:200],
                      video_info.get('autor', ''),
                      video_info.get('url_video', ''),
                      video_info.get('url_descarga', ''),
                      video_info.get('thumbnail', ''),
                      video_info.get('thumbnail_local'),
                      video_info.get('likes', 0),
                      video_info.get('vistas', 0),
                      video_info.get('duracion', 0),
                      datetime.now().isoformat(),
                      filepath,
                      json.dumps([]),
                      file_size,
                      'downloaded',
                      json.dumps([])  # etiquetas vacías por defecto
                  ))
        
        conn.commit()
        conn.close()

downloader = TikTokDownloader()

# ==================== RUTAS DE LA APLICACIÓN ====================

@app.route('/')
def index():
    return render_template('index_manual.html')

@app.route('/api/process-urls', methods=['POST'])
def process_urls():
    """Procesa URLs ingresadas manualmente"""
    try:
        data = request.json
        urls = data.get('urls', [])
        
        if not urls:
            return jsonify({'success': False, 'error': 'No hay URLs'})
        
        print(f"\n{'='*60}")
        print(f"📝 PROCESANDO {len(urls)} URLs")
        print(f"{'='*60}")
        
        videos = downloader.buscar_por_url_manual(urls)
        
        print(f"\n✅ Procesados: {len(videos)}/{len(urls)} videos\n")
        
        return jsonify({
            'success': True,
            'videos': videos,
            'total': len(videos)
        })
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/preview', methods=['POST'])
def preview_video():
    """Preview de video"""
    try:
        data = request.json
        video_info = data.get('video', {})
        
        url = video_info.get('url_descarga_hd') or video_info.get('url_descarga')
        
        if url:
            return jsonify({'success': True, 'url': url})
        
        url_original = video_info.get('url_video', '')
        if url_original:
            info = downloader._info_con_tikwm(url_original)
            if not info:
                info = downloader._info_con_snaptik(url_original)
            
            if info:
                url = info.get('url_descarga_hd') or info.get('url_descarga')
                if url:
                    return jsonify({'success': True, 'url': url})
        
        return jsonify({'success': False, 'error': 'No se pudo obtener URL'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/download', methods=['POST'])
def download_videos():
    """Descarga videos"""
    try:
        data = request.json
        videos = data.get('videos', [])
        
        if not videos:
            return jsonify({'success': False, 'error': 'No hay videos'})
        
        print(f"\n{'='*60}")
        print(f"📥 DESCARGANDO {len(videos)} VIDEOS")
        print(f"{'='*60}")
        
        resultados = []
        
        for i, video in enumerate(videos, 1):
            print(f"\n[{i}/{len(videos)}] {video.get('titulo', '')[:50]}...")
            resultado = downloader.descargar_video(video)
            resultados.append(resultado)
        
        exitos = sum(1 for r in resultados if r['success'])
        
        print(f"\n{'='*60}")
        print(f"✅ {exitos}/{len(resultados)} exitosos")
        print(f"{'='*60}\n")
        
        return jsonify({
            'success': True,
            'resultados': resultados,
            'total': len(resultados),
            'exitosos': exitos
        })
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/delete-videos', methods=['POST'])
def delete_videos():
    """Elimina videos de la base de datos y archivos"""
    try:
        data = request.json
        video_ids = data.get('video_ids', [])
        
        if not video_ids:
            return jsonify({'success': False, 'error': 'No hay videos seleccionados'})
        
        print(f"\n{'='*60}")
        print(f"🗑️  ELIMINANDO {len(video_ids)} VIDEOS")
        print(f"{'='*60}")
        
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        
        eliminados = 0
        errores = []
        
        for video_id in video_ids:
            try:
                c.execute('SELECT archivo_local, thumbnail_local FROM videos WHERE id = ?', (video_id,))
                result = c.fetchone()
                
                if result:
                    archivo_video = result[0]
                    archivo_thumb = result[1]
                    
                    if archivo_video and os.path.exists(archivo_video):
                        os.remove(archivo_video)
                        print(f"  ✅ Eliminado video: {os.path.basename(archivo_video)}")
                    
                    if archivo_thumb:
                        thumb_path = os.path.join(THUMBNAILS_FOLDER, archivo_thumb)
                        if os.path.exists(thumb_path):
                            os.remove(thumb_path)
                            print(f"  ✅ Eliminado thumb: {archivo_thumb}")
                    
                    c.execute('DELETE FROM videos WHERE id = ?', (video_id,))
                    eliminados += 1
                    print(f"  ✅ Eliminado de BD: {video_id}")
                else:
                    errores.append(f"Video {video_id} no encontrado")
                    print(f"  ⚠️  No encontrado: {video_id}")
                    
            except Exception as e:
                errores.append(f"Error en {video_id}: {str(e)}")
                print(f"  ❌ Error en {video_id}: {e}")
        
        conn.commit()
        conn.close()
        
        print(f"\n{'='*60}")
        print(f"✅ ELIMINADOS: {eliminados}/{len(video_ids)}")
        if errores:
            print(f"⚠️  ERRORES: {len(errores)}")
        print(f"{'='*60}\n")
        
        return jsonify({
            'success': True,
            'eliminados': eliminados,
            'total': len(video_ids),
            'errores': errores
        })
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/stats')
def get_stats():
    """Obtiene estadísticas de la biblioteca"""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        
        c.execute('SELECT COUNT(*) FROM videos')
        total_videos = c.fetchone()[0]
        
        c.execute('SELECT SUM(tamanio_bytes) FROM videos')
        total_bytes = c.fetchone()[0] or 0
        
        conn.close()
        
        return jsonify({
            'success': True,
            'total_videos': total_videos,
            'total_mb': round(total_bytes / 1024 / 1024, 2),
            'total_gb': round(total_bytes / 1024 / 1024 / 1024, 2)
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/thumbnails/<filename>')
def serve_thumbnail(filename):
    filepath = os.path.join(THUMBNAILS_FOLDER, filename)
    if os.path.exists(filepath):
        return send_file(filepath, mimetype='image/jpeg')
    return '', 404

@app.route('/api/database')
def get_database():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    c.execute('SELECT * FROM videos ORDER BY fecha_descarga DESC')
    videos = c.fetchall()
    
    conn.close()
    
    videos_list = []
    for v in videos:
        # Manejar la columna etiquetas (índice 15)
        etiquetas = json.loads(v[15]) if len(v) > 15 and v[15] else []
        
        videos_list.append({
            'id': v[0],
            'titulo': v[1],
            'autor': v[2],
            'thumbnail_local': v[6],
            'likes': v[7],
            'vistas': v[8],
            'duracion': v[9],
            'fecha_descarga': v[10],
            'tamanio_mb': v[13] / 1024 / 1024 if v[13] else 0,
            'etiquetas': etiquetas
        })
    
    return jsonify({'videos': videos_list})

@app.route('/api/video/<video_id>')
def get_video(video_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    c.execute('SELECT archivo_local FROM videos WHERE id = ?', (video_id,))
    result = c.fetchone()
    
    conn.close()
    
    if result and os.path.exists(result[0]):
        return send_file(result[0], mimetype='video/mp4')
    
    return jsonify({'error': 'Video no encontrado'}), 404

@app.route('/api/export')
def export_database():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    c.execute('SELECT * FROM videos')
    videos = c.fetchall()
    
    conn.close()
    
    api_data = {
        'version': '1.0',
        'total_videos': len(videos),
        'ultima_actualizacion': datetime.now().isoformat(),
        'videos': []
    }
    
    for v in videos:
        etiquetas = json.loads(v[15]) if len(v) > 15 and v[15] else []
        
        api_data['videos'].append({
            'id': v[0],
            'titulo': v[1],
            'autor': v[2],
            'thumbnail': f"/thumbnails/{v[6]}" if v[6] else '',
            'likes': v[7],
            'vistas': v[8],
            'duracion': v[9],
            'tamanio_mb': round(v[13] / 1024 / 1024, 2) if v[13] else 0,
            'url_video': f"/api/video/{v[0]}",
            'etiquetas': etiquetas
        })
    
    with open('api_videos.json', 'w', encoding='utf-8') as f:
        json.dump(api_data, f, indent=2, ensure_ascii=False)
    
    return send_file('api_videos.json', as_attachment=True)

# ==================== ENDPOINTS DE ETIQUETAS ====================

@app.route('/api/etiquetas')
def get_etiquetas():
    """Obtiene todas las etiquetas disponibles"""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        
        c.execute('SELECT id, nombre, color FROM etiquetas ORDER BY nombre')
        etiquetas = c.fetchall()
        
        conn.close()
        
        etiquetas_list = []
        for e in etiquetas:
            etiquetas_list.append({
                'id': e[0],
                'nombre': e[1],
                'color': e[2]
            })
        
        return jsonify({'success': True, 'etiquetas': etiquetas_list})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/etiquetas/crear', methods=['POST'])
def crear_etiqueta():
    """Crea una nueva etiqueta"""
    try:
        data = request.json
        nombre = data.get('nombre', '').strip()
        color = data.get('color', '#667eea')
        
        if not nombre:
            return jsonify({'success': False, 'error': 'Nombre vacío'})
        
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        
        try:
            c.execute('INSERT INTO etiquetas (nombre, color, fecha_creacion) VALUES (?, ?, ?)',
                     (nombre, color, datetime.now().isoformat()))
            conn.commit()
            etiqueta_id = c.lastrowid
            
            print(f"✅ Etiqueta creada: {nombre} (ID: {etiqueta_id})")
            
            return jsonify({
                'success': True,
                'etiqueta': {
                    'id': etiqueta_id,
                    'nombre': nombre,
                    'color': color
                }
            })
        except sqlite3.IntegrityError:
            return jsonify({'success': False, 'error': 'Ya existe una etiqueta con ese nombre'})
        finally:
            conn.close()
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/etiquetas/editar', methods=['POST'])
def editar_etiqueta():
    """Edita una etiqueta existente"""
    try:
        data = request.json
        etiqueta_id = data.get('id')
        nombre = data.get('nombre', '').strip()
        color = data.get('color', '#667eea')
        
        if not nombre:
            return jsonify({'success': False, 'error': 'Nombre vacío'})
        
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        
        try:
            c.execute('UPDATE etiquetas SET nombre = ?, color = ? WHERE id = ?',
                     (nombre, color, etiqueta_id))
            conn.commit()
            
            print(f"✅ Etiqueta actualizada: {nombre} (ID: {etiqueta_id})")
            
            return jsonify({'success': True})
        except sqlite3.IntegrityError:
            return jsonify({'success': False, 'error': 'Ya existe una etiqueta con ese nombre'})
        finally:
            conn.close()
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/etiquetas/eliminar', methods=['POST'])
def eliminar_etiqueta():
    """Elimina una etiqueta"""
    try:
        data = request.json
        etiqueta_id = data.get('id')
        
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        
        # Obtener nombre de la etiqueta
        c.execute('SELECT nombre FROM etiquetas WHERE id = ?', (etiqueta_id,))
        result = c.fetchone()
        
        if not result:
            conn.close()
            return jsonify({'success': False, 'error': 'Etiqueta no encontrada'})
        
        nombre_etiqueta = result[0]
        
        # Eliminar de todos los videos que la tienen
        c.execute('SELECT id, etiquetas FROM videos')
        videos = c.fetchall()
        
        for video_id, etiquetas_json in videos:
            if etiquetas_json:
                etiquetas = json.loads(etiquetas_json)
                if nombre_etiqueta in etiquetas:
                    etiquetas.remove(nombre_etiqueta)
                    c.execute('UPDATE videos SET etiquetas = ? WHERE id = ?',
                             (json.dumps(etiquetas), video_id))
        
        # Eliminar la etiqueta
        c.execute('DELETE FROM etiquetas WHERE id = ?', (etiqueta_id,))
        
        conn.commit()
        conn.close()
        
        print(f"✅ Etiqueta eliminada: {nombre_etiqueta}")
        
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/video/actualizar-etiquetas', methods=['POST'])
def actualizar_etiquetas_video():
    """Actualiza las etiquetas de un video"""
    try:
        data = request.json
        video_id = data.get('video_id')
        etiquetas = data.get('etiquetas', [])
        
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        
        c.execute('UPDATE videos SET etiquetas = ? WHERE id = ?',
                 (json.dumps(etiquetas), video_id))
        
        conn.commit()
        conn.close()
        
        print(f"✅ Etiquetas actualizadas para video {video_id}: {etiquetas}")
        
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/videos/filtrar', methods=['POST'])
def filtrar_videos():
    """Filtra videos por etiquetas"""
    try:
        data = request.json
        etiquetas_filtro = data.get('etiquetas', [])
        
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        
        c.execute('SELECT * FROM videos ORDER BY fecha_descarga DESC')
        videos = c.fetchall()
        conn.close()
        
        videos_list = []
        for v in videos:
            etiquetas_video = json.loads(v[15]) if len(v) > 15 and v[15] else []
            
            # Si hay filtro, verificar que tenga al menos una etiqueta del filtro
            if etiquetas_filtro:
                if not any(etiq in etiquetas_video for etiq in etiquetas_filtro):
                    continue
            
            videos_list.append({
                'id': v[0],
                'titulo': v[1],
                'autor': v[2],
                'thumbnail_local': v[6],
                'likes': v[7],
                'vistas': v[8],
                'duracion': v[9],
                'fecha_descarga': v[10],
                'tamanio_mb': v[13] / 1024 / 1024 if v[13] else 0,
                'etiquetas': etiquetas_video
            })
        
        return jsonify({'success': True, 'videos': videos_list})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# ==================== INICIAR APLICACIÓN ====================

if __name__ == '__main__':
    print("\n" + "="*60)
    print("🎵 TikTok Video Manager - VERSIÓN COMPLETA CON ETIQUETAS")
    print("="*60)
    print("\n🌐 Servidor: http://localhost:5000")
    print("📁 Videos:", DOWNLOAD_FOLDER)
    print("🖼️  Thumbnails:", THUMBNAILS_FOLDER)
    print("💾 Base de datos:", DB_FILE)
    print("\n✨ CARACTERÍSTICAS:")
    print("   • Descarga de videos sin marca de agua")
    print("   • Sistema de etiquetas personalizado")
    print("   • Filtrado por etiquetas")
    print("   • Gestión completa de biblioteca")
    print("   • Exportación a JSON para API")
    print("\n💡 INSTRUCCIONES:")
    print("   1. Abre TikTok.com en tu navegador")
    print("   2. Busca videos que te gusten")
    print("   3. Copia las URLs de los videos")
    print("   4. Pégalas en la aplicación web")
    print("   5. Descarga y organiza con etiquetas")
    print("   6. Exporta tu biblioteca como JSON")
    print("\n")
    app.run(debug=True, host='0.0.0.0', port=5000, threaded=True)